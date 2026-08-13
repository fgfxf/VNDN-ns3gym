#!/usr/bin/env python3.8
"""Circle 场景 TKAN-LSTM 训练程序 / Circle TKAN-LSTM trainer.

模型说明 / Model
----------------
TKAN-LSTM 将普通 LSTM 门控中的线性映射替换为 KANLinear，形成 KAN+LSTM。
KANLinear 使用从旧工程整理到当前训练目录的开源 efficient_kan 实现：
``contrib/vndn-nn-rd/ai-training/efficient_kan/kan.py``，本文件不重复实现 KAN。

输入与标签 / Input and label
----------------------------
``training-tag-<obu>.csv`` 每行格式如下，最后一列是分类标签：
``x,y,speed,acceleration,angle,lane_index,result_rsu_id``

每个 CSV 保持为独立时间序列，滑动窗口不会跨越不同仿真或不同车辆。
训练/验证按完整仿真目录划分，避免相邻窗口泄漏到验证集。窗口内部的时间
顺序不会打乱；仅训练阶段会打乱相互独立的窗口批次。

使用方法 / Usage
----------------
在 ``~/ndnSIM/ns-3`` 下运行默认的 100 epoch 训练：

    python3.8 contrib/vndn-nn-rd/ai-training/circle/train_tkan_lstm.py \
      --data-root data/circle-simple/20260812 \
      --forward-strategy NoForward \
      --epochs 100

查看全部参数 / Show all options:

    python3.8 contrib/vndn-nn-rd/ai-training/circle/train_tkan_lstm.py --help

模型默认保存在：
``data/models/circle/tkan-lstm/YYYYMMDD-HHMMSS/``。
文件名包含场景、模型、转发策略以及年月日时分秒。
"""

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass
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
DEFAULT_DATA_ROOT = NS3_ROOT / "data" / "circle-simple" / "20260812"
DEFAULT_OUTPUT_ROOT = NS3_ROOT / "data" / "models" / "circle" / "tkan-lstm"


@dataclass(frozen=True)
class SequenceFile:
    """一辆车在一次仿真中的有序数据 / One ordered OBU simulation trace."""

    run_directory: Path
    csv_path: Path
    values: np.ndarray


def read_simulation_config(path: Path) -> Dict[str, str]:
    """读取 key=value 仿真配置 / Read a key=value simulation config."""
    config = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            config[key.strip()] = value.strip()
    return config


def load_sequence_file(run_directory: Path, csv_path: Path) -> SequenceFile:
    """读取并验证七列 CSV / Load and validate a seven-column CSV."""
    values = np.loadtxt(str(csv_path), delimiter=",", dtype=np.float32, ndmin=2)
    expected_columns = len(FEATURE_NAMES) + 1
    if values.shape[1] != expected_columns:
        raise ValueError(
            "{} 应有 {} 列，实际为 {} 列 / expected {} columns, got {}".format(
                csv_path,
                expected_columns,
                values.shape[1],
                expected_columns,
                values.shape[1],
            )
        )
    if not np.isfinite(values).all():
        raise ValueError("{} 包含 NaN 或无穷大 / contains NaN or infinity".format(csv_path))
    labels = values[:, -1]
    if not np.equal(labels, labels.astype(np.int64)).all():
        raise ValueError("{} 包含非整数 RSU 标签 / non-integer label".format(csv_path))
    return SequenceFile(run_directory, csv_path, values)


def discover_sequences(
    data_root: Path, forward_strategy: str = "NoForward"
) -> List[SequenceFile]:
    """发现已完成且策略匹配的数据 / Discover complete matching runs.

    ``training-tag-x-stats.txt`` 只在车辆结束时生成，因此用作完成标记，
    避免读取 run-vndn-circle.sh 正在追加的半截 CSV。
    The stats file is a completion marker that excludes a live partial CSV.
    """
    sequences = []
    for config_path in sorted(data_root.glob("*/simulation-config.txt")):
        config = read_simulation_config(config_path)
        if config.get("RsuForwardStrategy") != forward_strategy:
            continue
        run_directory = config_path.parent
        training_directory = run_directory / "ai-training"
        for csv_path in sorted(training_directory.glob("training-tag-*.csv")):
            if csv_path.name.endswith("-rtt.csv"):
                continue
            stats_path = csv_path.with_name(csv_path.stem + "-stats.txt")
            if not stats_path.is_file() or csv_path.stat().st_size == 0:
                continue
            sequences.append(load_sequence_file(run_directory, csv_path))
    if not sequences:
        raise ValueError(
            "在 {} 下没有找到策略为 {} 的完整训练数据 / no completed matching data".format(
                data_root, forward_strategy
            )
        )
    return sequences


def split_by_run(
    sequences: Sequence[SequenceFile], validation_ratio: float
) -> Tuple[List[SequenceFile], List[SequenceFile]]:
    """按完整仿真划分，防止重叠窗口泄漏 / Split complete runs."""
    if not 0.0 < validation_ratio < 1.0:
        raise ValueError("validation-ratio 必须在 0 和 1 之间")
    run_directories = sorted({item.run_directory for item in sequences})
    if len(run_directories) < 2:
        raise ValueError("至少需要两次已完成仿真 / at least two completed runs are required")
    validation_count = max(1, int(math.ceil(len(run_directories) * validation_ratio)))
    validation_runs = set(run_directories[-validation_count:])
    train = [item for item in sequences if item.run_directory not in validation_runs]
    validation = [item for item in sequences if item.run_directory in validation_runs]
    return train, validation


def label_values(sequences: Iterable[SequenceFile]) -> List[int]:
    """按数值排序分类标签 / Return sorted label values."""
    labels = set()
    for item in sequences:
        labels.update(item.values[:, -1].astype(np.int64).tolist())
    return sorted(labels)


def normalization_statistics(
    sequences: Sequence[SequenceFile],
) -> Tuple[np.ndarray, np.ndarray]:
    """只用训练集计算标准化参数 / Fit normalization on training data only."""
    features = np.concatenate([item.values[:, :-1] for item in sequences], axis=0)
    mean = features.mean(axis=0, dtype=np.float64).astype(np.float32)
    standard_deviation = features.std(axis=0, dtype=np.float64).astype(np.float32)
    standard_deviation[standard_deviation < 1e-8] = 1.0
    return mean, standard_deviation


def make_windows(
    sequences: Sequence[SequenceFile],
    sequence_length: int,
    stride: int,
    mean: np.ndarray,
    standard_deviation: np.ndarray,
    labels: Sequence[int],
) -> Tuple[np.ndarray, np.ndarray]:
    """构造有序滑动窗口，最后时刻标签作为输出 / Build ordered windows."""
    if sequence_length < 1 or stride < 1:
        raise ValueError("sequence-length 和 stride 必须为正数")
    label_to_index = {value: index for index, value in enumerate(labels)}
    windows = []
    targets = []
    for item in sequences:
        if len(item.values) < sequence_length:
            continue
        features = (item.values[:, :-1] - mean) / standard_deviation
        for start in range(0, len(features) - sequence_length + 1, stride):
            stop = start + sequence_length
            label = int(item.values[stop - 1, -1])
            if label not in label_to_index:
                raise ValueError("验证集出现训练集中没有的标签 / unseen label: {}".format(label))
            windows.append(features[start:stop])
            targets.append(label_to_index[label])
    if not windows:
        raise ValueError("无法构造时间窗口 / no sequence window could be constructed")
    return (
        np.ascontiguousarray(np.stack(windows).astype(np.float32)),
        np.asarray(targets, dtype=np.int64),
    )


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


class CircleTKANLSTM(nn.Module):
    """Circle 驻留 RSU 时间序列分类器 / Serving-RSU sequence classifier."""

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
        description="使用 training-tag-x.csv 训练 circle TKAN-LSTM / Train circle TKAN-LSTM"
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--forward-strategy", default="NoForward")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--sequence-length", type=int, default=10)
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
    correct = 0
    sample_count = 0
    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            predictions = model(inputs)
            total_loss += criterion(predictions, targets).item() * len(targets)
            correct += (predictions.argmax(dim=1) == targets).sum().item()
            sample_count += len(targets)
    return total_loss / sample_count, correct / sample_count


def checkpoint_payload(
    model: CircleTKANLSTM,
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
        "scenario": "circle",
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
    arguments = parse_arguments()
    if arguments.epochs < 1 or arguments.batch_size < 1:
        raise ValueError("epochs 和 batch-size 必须为正数")
    set_random_seed(arguments.seed)
    device = select_device(arguments.device)

    # 数据准备 / Data preparation.
    sequences = discover_sequences(arguments.data_root.resolve(), arguments.forward_strategy)
    train_sequences, validation_sequences = split_by_run(
        sequences, arguments.validation_ratio
    )
    labels = label_values(train_sequences)
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

    model = CircleTKANLSTM(
        len(FEATURE_NAMES),
        arguments.hidden_size,
        len(labels),
        arguments.grid_size,
        arguments.spline_order,
        arguments.dropout,
    ).to(device)

    # 类别权重由训练集自动计算 / Balance classes using training frequencies.
    counts = np.bincount(train_targets, minlength=len(labels)).astype(np.float32)
    class_weights = counts.sum() / (len(labels) * counts)
    criterion = nn.CrossEntropyLoss(weight=torch.from_numpy(class_weights).to(device))
    optimizer = torch.optim.Adam(model.parameters(), lr=arguments.learning_rate)

    # 输出目录和模型名都包含秒 / Timestamp includes date, hour, minute and second.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    strategy_slug = arguments.forward_strategy.lower().replace("_", "-")
    output_directory = arguments.output_root.resolve() / timestamp
    output_directory.mkdir(parents=True, exist_ok=False)
    model_path = output_directory / (
        "tkan-lstm-circle-{}-{}.pt".format(strategy_slug, timestamp)
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
        sample_count = 0
        for inputs, targets in train_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            optimizer.zero_grad()
            predictions = model(inputs)
            loss = criterion(predictions, targets)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(targets)
            sample_count += len(targets)

        train_loss = total_loss / sample_count
        validation_loss, validation_accuracy = evaluate(
            model, validation_loader, criterion, device
        )
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
        "model_path": str(model_path),
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
