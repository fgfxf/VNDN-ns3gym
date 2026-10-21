#!/usr/bin/env python3.8
"""方阵 场景的七类 TKAN-LSTM 离线训练 / Seven-RSU offline training.

每车 CSV: x,y,speed,acceleration,angle,lane_index,result_rsu_id。
只从显式 --data-root 日期目录发现已完成车辆的 NoForward 数据。无效行被
排除并切断时间片段；窗口不跨车辆、run 或无效行。完整 run 划分 train/val，
只在训练集拟合归一化，训练窗口目标必须覆盖 RSU 0..6。

    python3.8 contrib/vndn-nn-rd/ai-training/grid/train_tkan_lstm.py \
      --data-root data/grid-vanet-test/20261018 --device cpu --epochs 100

沿用 circle 的独立训练文件结构，仅共享 efficient_kan.KANLinear。
"""

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


# 路径与开源 KAN 库 / Paths and the open-source KAN dependency.
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
NS3_ROOT = SCRIPT_DIRECTORY.parents[3]
AI_TRAINING_ROOT = SCRIPT_DIRECTORY.parent
EFFICIENT_KAN_FILE = AI_TRAINING_ROOT / "efficient_kan" / "kan.py"
if not EFFICIENT_KAN_FILE.is_file():
    raise ImportError(
        "找不到 efficient_kan / efficient_kan was not found: {}".format(
            EFFICIENT_KAN_FILE
        )
    )
sys.path.insert(0, str(AI_TRAINING_ROOT))
from efficient_kan.kan import KANLinear  # noqa: E402


FEATURE_NAMES = ("x", "y", "speed", "acceleration", "angle", "lane_index")
LABEL_NAME = "result_rsu_id"
SCENARIO = "grid"
EXPECTED_LABELS = tuple(range(7))
DEFAULT_OUTPUT_ROOT = NS3_ROOT / "data" / "models" / SCENARIO / "tkan-lstm"


@dataclass(frozen=True)
class SequenceFile:
    """One vehicle/run: retained rows plus the original contiguous segment lengths."""

    run_directory: Path
    csv_path: Path
    values: np.ndarray
    segment_lengths: Tuple[int, ...] = ()
    discarded_by_reason: Dict[str, int] = field(default_factory=dict)
    original_row_count: int = 0

    def segments(self) -> Iterable[np.ndarray]:
        offset = 0
        for length in self.segment_lengths or ((len(self.values),) if len(self.values) else ()):
            yield self.values[offset:offset + length]
            offset += length


def read_simulation_config(path: Path) -> Dict[str, str]:
    """Read the simulation's key=value configuration."""
    config = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            config[key.strip()] = value.strip()
    return config


def validate_data_root(data_root: Path) -> Path:
    """Reject another known scenario's canonical directory; custom roots are allowed.

    A path cannot certify provenance: current CSV/config files have no scenario
    metadata. The operator must check that custom/moved data came from this map.
    """
    data_root = data_root.expanduser().resolve()
    known_directories = {
        "circle-simple": "circle", "grid-vanet-test": "grid",
        "fgfxf-spider-map": "spidermap",
    }
    try:
        relative = data_root.relative_to(NS3_ROOT / "data")
    except ValueError:
        relative = None
    if relative and relative.parts:
        recorded_scenario = known_directories.get(relative.parts[0])
        if recorded_scenario and recorded_scenario != SCENARIO:
            raise ValueError("data-root scenario mismatch: expected {}, got {} ({})".format(
                SCENARIO, recorded_scenario, data_root))
    if not data_root.is_dir():
        raise ValueError("data-root directory does not exist: {}".format(data_root))
    return data_root


def load_sequence_file(run_directory: Path, csv_path: Path) -> SequenceFile:
    """Discard identifiable invalid numeric rows and preserve every temporal break.

    Malformed CSV/column counts and unreadable text are errors. Validation uses
    float64 before float32 conversion so near-integer invalid labels stay invalid.
    Each rejected row is assigned exactly one reason, in the order below.
    """
    expected_columns = len(FEATURE_NAMES) + 1
    values = []
    lengths = []
    segment_length = 0
    row_count = 0
    discarded = {
        "nonfinite_feature": 0, "nonfinite_label": 0,
        "noninteger_label": 0, "out_of_range_label": 0,
    }
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, columns in enumerate(csv.reader(stream, strict=True), 1):
                if len(columns) != expected_columns:
                    raise ValueError("{}:{} expected {} columns, got {}".format(
                        csv_path, line_number, expected_columns, len(columns)))
                try:
                    row = np.asarray([float(value) for value in columns], dtype=np.float64)
                except ValueError as error:
                    raise ValueError("{}:{} contains nonnumeric CSV values".format(
                        csv_path, line_number)) from error
                row_count += 1
                with np.errstate(over="ignore", invalid="ignore"):
                    features = row[:-1].astype(np.float32)
                label = row[-1]
                reason = None
                if not np.isfinite(features).all():
                    reason = "nonfinite_feature"
                elif not np.isfinite(label):
                    reason = "nonfinite_label"
                elif label != np.floor(label):
                    reason = "noninteger_label"
                elif label not in EXPECTED_LABELS:
                    reason = "out_of_range_label"
                if reason is not None:
                    discarded[reason] += 1
                    if segment_length:
                        lengths.append(segment_length)
                        segment_length = 0
                    continue
                values.append(row.astype(np.float32))
                segment_length += 1
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError("{} could not be read as CSV: {}".format(csv_path, error)) from error
    if segment_length:
        lengths.append(segment_length)
    retained = np.asarray(values, dtype=np.float32).reshape(-1, expected_columns)
    return SequenceFile(run_directory, csv_path, retained, tuple(lengths), discarded, row_count)


def discover_sequences(
    data_root: Path, forward_strategy: str = "NoForward", report: Dict = None,
) -> List[SequenceFile]:
    """Select strategy-matching, nonempty OBU CSVs with per-vehicle stats markers.

    Stats only certify that vehicle output is closed, not that the whole run
    succeeded. Check the simulation exit status before using a date directory.
    """
    sequences = []
    statistics = {
        "config_count": 0, "ignored_strategy_runs": 0, "ignored_rtt_files": 0,
        "ignored_empty_files": 0, "ignored_unfinished_files": 0, "selected_files": 0,
    }
    for config_path in sorted(data_root.glob("*/simulation-config.txt")):
        statistics["config_count"] += 1
        config = read_simulation_config(config_path)
        if config.get("RsuForwardStrategy") != forward_strategy:
            statistics["ignored_strategy_runs"] += 1
            continue
        run_directory = config_path.parent
        for csv_path in sorted((run_directory / "ai-training").glob("training-tag-*.csv")):
            if csv_path.name.endswith("-rtt.csv"):
                statistics["ignored_rtt_files"] += 1
                continue
            if not csv_path.with_name(csv_path.stem + "-stats.txt").is_file():
                statistics["ignored_unfinished_files"] += 1
                continue
            if csv_path.stat().st_size == 0:
                statistics["ignored_empty_files"] += 1
                continue
            sequences.append(load_sequence_file(run_directory, csv_path))
            statistics["selected_files"] += 1
    if report is not None:
        report.update(statistics)
    if not sequences:
        raise ValueError("{}: no completed matching data for strategy {} ({})".format(
            data_root, forward_strategy, statistics))
    return sequences


def split_by_run(
    sequences: Sequence[SequenceFile], validation_ratio: float,
) -> Tuple[List[SequenceFile], List[SequenceFile]]:
    """Assign complete runs to one split; chronological final runs form validation."""
    if not 0.0 < validation_ratio < 1.0:
        raise ValueError("validation-ratio must be between 0 and 1")
    runs = sorted({item.run_directory for item in sequences})
    if len(runs) < 2:
        raise ValueError("at least two completed runs are required")
    validation_count = max(1, int(math.ceil(len(runs) * validation_ratio)))
    if validation_count >= len(runs):
        raise ValueError("validation-ratio leaves no training runs; reduce it or collect more runs")
    validation_runs = set(runs[-validation_count:])
    return ([item for item in sequences if item.run_directory not in validation_runs],
            [item for item in sequences if item.run_directory in validation_runs])


def label_values(sequences: Iterable[SequenceFile]) -> List[int]:
    labels = set()
    for item in sequences:
        labels.update(item.values[:, -1].astype(np.int64).tolist())
    return sorted(labels)


def normalization_statistics(sequences: Sequence[SequenceFile]) -> Tuple[np.ndarray, np.ndarray]:
    """Fit normalization to retained training rows only, never validation rows."""
    features = [item.values[:, :-1] for item in sequences if len(item.values)]
    if not features:
        raise ValueError("training split has no valid rows after filtering")
    features = np.concatenate(features, axis=0)
    mean = features.mean(axis=0, dtype=np.float64).astype(np.float32)
    deviation = features.std(axis=0, dtype=np.float64).astype(np.float32)
    deviation[deviation < 1e-8] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(deviation).all():
        raise ValueError("nonfinite training normalization statistics")
    return mean, deviation


def summarize_sequences(sequences: Sequence[SequenceFile], sequence_length: int, stride: int) -> Dict:
    """Counts include invalid rows, short segments and target classes per source CSV."""
    if sequence_length < 1 or stride < 1:
        raise ValueError("sequence-length and stride must be positive")
    summary = {
        "row_count": 0, "valid_row_count": 0, "discarded_row_count": 0,
        "discarded_by_reason": {name: 0 for name in (
            "nonfinite_feature", "nonfinite_label", "noninteger_label", "out_of_range_label")},
        "segment_count": 0, "short_segment_count": 0, "window_count": 0,
        "class_counts": {str(label): 0 for label in EXPECTED_LABELS}, "files": [],
    }
    for sequence in sequences:
        segments = list(sequence.segments())
        counts = {str(label): 0 for label in EXPECTED_LABELS}
        for segment in segments:
            for index in range(sequence_length - 1, len(segment), stride):
                counts[str(int(segment[index, -1]))] += 1
        item = {
            "csv_path": str(sequence.csv_path), "run_directory": str(sequence.run_directory),
            "row_count": sequence.original_row_count or len(sequence.values),
            "valid_row_count": len(sequence.values),
            "discarded_row_count": sum(sequence.discarded_by_reason.values()),
            "discarded_by_reason": dict(sequence.discarded_by_reason),
            "segment_count": len(segments),
            "short_segment_count": sum(len(segment) < sequence_length for segment in segments),
            "window_count": sum(counts.values()), "class_counts": counts,
        }
        summary["files"].append(item)
        for name in ("row_count", "valid_row_count", "discarded_row_count", "segment_count",
                     "short_segment_count", "window_count"):
            summary[name] += item[name]
        for reason, count in item["discarded_by_reason"].items():
            summary["discarded_by_reason"][reason] += count
        for label, count in counts.items():
            summary["class_counts"][label] += count
    return summary


def make_windows(
    sequences: Sequence[SequenceFile], sequence_length: int, stride: int,
    mean: np.ndarray, standard_deviation: np.ndarray, labels: Sequence[int],
) -> Tuple[np.ndarray, np.ndarray]:
    """Window each contiguous segment; use the final row's result-time RSU label."""
    if sequence_length < 1 or stride < 1:
        raise ValueError("sequence-length and stride must be positive")
    label_to_index = {value: index for index, value in enumerate(labels)}
    windows, targets = [], []
    for item in sequences:
        for segment in item.segments():
            if len(segment) < sequence_length:
                continue
            features = ((segment[:, :-1].astype(np.float64) - mean) / standard_deviation).astype(np.float32)
            if not np.isfinite(features).all():
                raise ValueError("{} contains nonfinite normalized features".format(item.csv_path))
            for start in range(0, len(features) - sequence_length + 1, stride):
                stop = start + sequence_length
                label = int(segment[stop - 1, -1])
                if label not in label_to_index:
                    raise ValueError("unseen label: {}".format(label))
                windows.append(features[start:stop])
                targets.append(label_to_index[label])
    if not windows:
        raise ValueError("no sequence window could be constructed after filtering")
    return (np.ascontiguousarray(np.stack(windows), dtype=np.float32),
            np.asarray(targets, dtype=np.int64))


def class_weights_for_targets(targets: np.ndarray, labels: Sequence[int]) -> np.ndarray:
    """Require all seven classes among actual train targets before dividing counts."""
    counts = np.bincount(targets, minlength=len(labels))
    missing = [int(label) for label, count in zip(labels, counts) if count == 0]
    if missing:
        raise ValueError("training window targets missing RSU labels {}; collect more data "
                         "or adjust stride/split (raw CSV labels are insufficient)".format(missing))
    weights = (counts.sum() / (len(labels) * counts)).astype(np.float32)
    if not np.isfinite(weights).all():
        raise ValueError("nonfinite class weights")
    return weights


class TKANLSTMCell(nn.Module):
    """使用开源 KANLinear 代替线性门控映射的 LSTM 单元。"""

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        grid_size: int = 5,
        spline_order: int = 3,
    ) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        # 一次输出四个门，等价于四个独立 KAN 层，但只计算一次样条基函数。
        # One projection emits four gates and avoids repeated spline evaluation.
        self.gates = KANLinear(
            input_size + hidden_size,
            4 * hidden_size,
            grid_size=grid_size,
            spline_order=spline_order,
        )

    def forward(
        self,
        inputs: torch.Tensor,
        state: Tuple[torch.Tensor, torch.Tensor],
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        previous_hidden, previous_cell = state
        gates = self.gates(torch.cat((inputs, previous_hidden), dim=-1))
        forget, incoming, candidate, output = gates.chunk(4, dim=-1)
        cell = (
            torch.sigmoid(forget) * previous_cell
            + torch.sigmoid(incoming) * torch.tanh(candidate)
        )
        hidden = torch.sigmoid(output) * torch.tanh(cell)
        return hidden, cell


class GridTKANLSTM(nn.Module):
    """方阵 七类 RSU 时间序列分类器 / Serving-RSU sequence classifier."""

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        output_size: int,
        grid_size: int = 5,
        spline_order: int = 3,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        self.cell = TKANLSTMCell(input_size, hidden_size, grid_size, spline_order)
        self.normalization = nn.LayerNorm(hidden_size)
        self.dropout = nn.Dropout(dropout)
        # 旧实现同样使用 KANLinear 作为最终分类映射。
        # Match the old implementation by using KAN for classification too.
        self.classifier = KANLinear(
            hidden_size,
            output_size,
            grid_size=grid_size,
            spline_order=spline_order,
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        if inputs.dim() != 3:
            raise ValueError("输入形状应为 [batch, sequence, feature]")
        batch_size = inputs.size(0)
        hidden = inputs.new_zeros((batch_size, self.hidden_size))
        cell = inputs.new_zeros((batch_size, self.hidden_size))
        for timestep in range(inputs.size(1)):
            hidden, cell = self.cell(inputs[:, timestep, :], (hidden, cell))
        return self.classifier(self.dropout(self.normalization(hidden)))


def parse_arguments() -> argparse.Namespace:
    """定义用户可配置参数 / Define command-line options."""
    parser = argparse.ArgumentParser(
        description="使用 training-tag-x.csv 训练 grid TKAN-LSTM / Train grid TKAN-LSTM"
    )
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Completed simulation date directory; provenance must be verified")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--forward-strategy", default="NoForward")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--sequence-length", type=int, default=10, choices=(10,),
                        help="Current C++ gym interface requires 10 timesteps")
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--grid-size", type=int, default=5)
    parser.add_argument("--spline-order", type=int, default=3)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--validation-ratio", type=float, default=0.2)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return parser.parse_args()


def select_device(requested: str) -> torch.device:
    """自动使用 CUDA，否则使用 CPU / Prefer CUDA when available."""
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("请求使用 CUDA，但当前 PyTorch 不支持 CUDA")
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(requested)


def set_random_seed(seed: int) -> None:
    """固定训练随机性 / Seed Python, NumPy and PyTorch."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> Tuple[float, float]:
    """计算验证损失和准确率 / Compute validation loss and accuracy."""
    model.eval()
    total_loss = 0.0
    total_weight = 0.0
    correct = 0
    sample_count = 0
    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            predictions = model(inputs)
            # Weighted CE's mean denominator is target weight, not batch size.
            batch_weight = (criterion.weight[targets].sum().item()
                            if criterion.weight is not None else len(targets))
            total_loss += criterion(predictions, targets).item() * batch_weight
            total_weight += batch_weight
            correct += (predictions.argmax(dim=1) == targets).sum().item()
            sample_count += len(targets)
    return total_loss / total_weight, correct / sample_count


def checkpoint_payload(
    model: GridTKANLSTM,
    arguments: argparse.Namespace,
    labels: Sequence[int],
    mean: np.ndarray,
    standard_deviation: np.ndarray,
    epoch: int,
    validation_accuracy: float,
) -> Dict:
    """权重和推理所需元数据一起保存 / Save weights with inference metadata."""
    return {
        "model_type": "TKAN-LSTM",
        "scenario": SCENARIO,
        "forward_strategy": arguments.forward_strategy,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "efficient_kan_source": str(EFFICIENT_KAN_FILE),
        "feature_names": list(FEATURE_NAMES),
        "label_name": LABEL_NAME,
        "label_values": list(labels),
        "normalization_mean": mean.tolist(),
        "normalization_std": standard_deviation.tolist(),
        "model_parameters": {
            "input_size": len(FEATURE_NAMES),
            "hidden_size": arguments.hidden_size,
            "output_size": len(labels),
            "grid_size": arguments.grid_size,
            "spline_order": arguments.spline_order,
            "dropout": arguments.dropout,
            "sequence_length": arguments.sequence_length,
        },
        "best_epoch": epoch,
        "validation_accuracy": validation_accuracy,
        "state_dict": model.state_dict(),
    }


def main() -> int:
    """加载数据、训练、验证并保存最佳模型 / Run the complete pipeline."""
    if any(value == "--dataset-manifest" or value.startswith("--dataset-manifest=")
           for value in sys.argv[1:]):
        from formal_training import train
        train(sys.argv[1:], "grid", GridTKANLSTM)
        return 0
    arguments = parse_arguments()
    if any(getattr(arguments, name) < 1 for name in (
        "epochs", "batch_size", "stride", "hidden_size", "grid_size", "spline_order"
    )):
        raise ValueError("epochs, batch-size, stride, hidden-size, grid-size and spline-order must be positive")
    if not math.isfinite(arguments.learning_rate) or arguments.learning_rate <= 0:
        raise ValueError("learning-rate must be finite and positive")
    if not 0.0 <= arguments.dropout < 1.0 or arguments.patience < 0:
        raise ValueError("dropout must be in [0, 1), patience must be nonnegative")
    arguments.data_root = validate_data_root(arguments.data_root)
    arguments.output_root = arguments.output_root.expanduser().resolve()
    set_random_seed(arguments.seed)
    device = select_device(arguments.device)

    # 数据准备 / Data preparation.
    discovery = {}
    sequences = discover_sequences(arguments.data_root, arguments.forward_strategy, discovery)
    filtering = summarize_sequences(sequences, arguments.sequence_length, arguments.stride)
    print("Discovery / 文件筛选: {}".format(json.dumps(discovery, ensure_ascii=False)))
    print("Filtering / 数据筛选: {}".format(json.dumps(
        {key: value for key, value in filtering.items() if key != "files"}, ensure_ascii=False)))
    train_sequences, validation_sequences = split_by_run(sequences, arguments.validation_ratio)
    labels = list(EXPECTED_LABELS)
    train_filtering = summarize_sequences(train_sequences, arguments.sequence_length, arguments.stride)
    validation_filtering = summarize_sequences(validation_sequences, arguments.sequence_length, arguments.stride)
    for split_name, report in (("training", train_filtering), ("validation", validation_filtering)):
        if not report["window_count"]:
            raise ValueError("{} split: no sequence window could be constructed after filtering "
                             "(valid rows={}, short segments={})".format(
                                 split_name, report["valid_row_count"], report["short_segment_count"]))
    mean, standard_deviation = normalization_statistics(train_sequences)
    train_inputs, train_targets = make_windows(
        train_sequences,
        arguments.sequence_length,
        arguments.stride,
        mean,
        standard_deviation,
        labels,
    )
    validation_inputs, validation_targets = make_windows(
        validation_sequences,
        arguments.sequence_length,
        arguments.stride,
        mean,
        standard_deviation,
        labels,
    )

    class_weights = class_weights_for_targets(train_targets, labels)

    # 窗口内部时序保持不变；只打乱独立训练窗口。
    # Timesteps stay ordered; only independent training windows are shuffled.
    train_generator = torch.Generator().manual_seed(arguments.seed)
    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(train_inputs), torch.from_numpy(train_targets)),
        batch_size=arguments.batch_size,
        shuffle=True,
        generator=train_generator,
    )
    validation_loader = DataLoader(
        TensorDataset(
            torch.from_numpy(validation_inputs), torch.from_numpy(validation_targets)
        ),
        batch_size=arguments.batch_size,
        shuffle=False,
    )

    model = GridTKANLSTM(
        len(FEATURE_NAMES),
        arguments.hidden_size,
        len(labels),
        arguments.grid_size,
        arguments.spline_order,
        arguments.dropout,
    ).to(device)

    # 类别权重由训练集自动计算 / Balance classes using training frequencies.
    criterion = nn.CrossEntropyLoss(weight=torch.from_numpy(class_weights).to(device))
    optimizer = torch.optim.Adam(model.parameters(), lr=arguments.learning_rate)

    # 输出目录和模型名都包含秒 / Timestamp includes date, hour, minute and second.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    strategy_slug = arguments.forward_strategy.lower().replace("_", "-")
    output_directory = arguments.output_root.resolve() / timestamp
    output_directory.mkdir(parents=True, exist_ok=False)
    model_path = output_directory / (
        "tkan-lstm-grid-{}-{}.pt".format(strategy_slug, timestamp)
    )
    history_path = output_directory / "training-history.csv"
    summary_path = output_directory / "training-summary.json"

    print("Python: {}".format(sys.version.split()[0]))
    print("Device / 设备: {}".format(device))
    print("efficient_kan: {}".format(EFFICIENT_KAN_FILE))
    print(
        "Runs / 仿真次数: train={}, validation={}".format(
            len({item.run_directory for item in train_sequences}),
            len({item.run_directory for item in validation_sequences}),
        )
    )
    print(
        "Windows / 窗口数: train={}, validation={}".format(
            len(train_targets), len(validation_targets)
        )
    )
    print("Labels / 标签: {}".format(labels))
    print("Output / 输出: {}".format(output_directory))

    # 训练并按验证准确率保存最佳 checkpoint / Train and keep the best checkpoint.
    best_accuracy = -1.0
    best_epoch = 0
    epochs_without_improvement = 0
    history = []
    for epoch in range(1, arguments.epochs + 1):
        model.train()
        total_loss = 0.0
        total_weight = 0.0
        for inputs, targets in train_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            optimizer.zero_grad()
            predictions = model(inputs)
            loss = criterion(predictions, targets)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite training loss at epoch {}".format(epoch))
            loss.backward()
            if any(parameter.grad is not None and not torch.isfinite(parameter.grad).all()
                   for parameter in model.parameters()):
                raise ValueError("nonfinite training gradient at epoch {}".format(epoch))
            optimizer.step()
            batch_weight = criterion.weight[targets].sum().item()
            total_loss += loss.item() * batch_weight
            total_weight += batch_weight

        train_loss = total_loss / total_weight
        validation_loss, validation_accuracy = evaluate(
            model, validation_loader, criterion, device
        )
        if not all(math.isfinite(value) for value in (train_loss, validation_loss, validation_accuracy)):
            raise ValueError("nonfinite training/validation metrics at epoch {}".format(epoch))
        history.append((epoch, train_loss, validation_loss, validation_accuracy))
        print(
            "Epoch [{}/{}] train_loss={:.6f} val_loss={:.6f} val_accuracy={:.4%}".format(
                epoch,
                arguments.epochs,
                train_loss,
                validation_loss,
                validation_accuracy,
            )
        )

        if validation_accuracy > best_accuracy:
            best_accuracy = validation_accuracy
            best_epoch = epoch
            epochs_without_improvement = 0
            torch.save(
                checkpoint_payload(
                    model,
                    arguments,
                    labels,
                    mean,
                    standard_deviation,
                    epoch,
                    validation_accuracy,
                ),
                str(model_path),
            )
        else:
            epochs_without_improvement += 1
        if arguments.patience > 0 and epochs_without_improvement >= arguments.patience:
            print("验证准确率连续 {} 轮未提高，提前停止".format(arguments.patience))
            break

    # 保存训练曲线原始数据和摘要 / Save history and a machine-readable summary.
    with history_path.open("w", encoding="utf-8", newline="") as history_file:
        writer = csv.writer(history_file)
        writer.writerow(("epoch", "train_loss", "validation_loss", "validation_accuracy"))
        writer.writerows(history)

    summary = {
        "scenario": SCENARIO,
        "model_path": str(model_path),
        "data_root": str(arguments.data_root),
        "provenance_note": "Scenario is selected by the trainer; input CSV/config has no scenario metadata.",
        "device": str(device),
        "discovery": discovery,
        "filtering": filtering,
        "train_filtering": train_filtering,
        "validation_filtering": validation_filtering,
        "train_runs": sorted(str(item) for item in {sequence.run_directory for sequence in train_sequences}),
        "validation_runs": sorted(str(item) for item in {sequence.run_directory for sequence in validation_sequences}),
        "train_class_counts": train_filtering["class_counts"],
        "validation_class_counts": validation_filtering["class_counts"],
        "class_weights": class_weights.tolist(),
        "best_epoch": best_epoch,
        "best_validation_accuracy": best_accuracy,
        "train_run_count": len({item.run_directory for item in train_sequences}),
        "validation_run_count": len({item.run_directory for item in validation_sequences}),
        "train_window_count": len(train_targets),
        "validation_window_count": len(validation_targets),
        "arguments": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(arguments).items()
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Best model / 最佳模型: {}".format(model_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
