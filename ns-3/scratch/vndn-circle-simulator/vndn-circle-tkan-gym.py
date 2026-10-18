#!/usr/bin/env python3.8
"""VNDN circle TKAN-LSTM ns3-gym inference controller.

用途 / Purpose
--------------
接收 RSU 通过 ns3-gym 发来的最近 10 个车辆状态，加载训练好的 TKAN-LSTM
checkpoint，返回每个候选 RSU 的 softmax 概率。前两名概率差不超过 0.10，
或者第二名概率达到 0.10 时，由 C++ 的 VndnRsu 同时选择两条回程路径。

The script receives an ordered vehicle-state sequence from ns-3, reconstructs
the TKAN-LSTM architecture from checkpoint metadata, loads ``state_dict``, and
returns a probability for every candidate RSU. C++ selects two return paths
when their gap is at most 0.10 or the runner-up probability is at least 0.10.

模型文件说明 / Checkpoint format
--------------------------------
训练生成的 ``.pt`` 是 checkpoint 字典，不包含可直接执行的 Python 模型对象。
它保存了 ``model_parameters``、归一化参数、标签映射和 ``state_dict``。因此本
脚本从训练文件导入 CircleTKANLSTM，按元数据重建结构后再加载权重。

使用方法 / Usage
----------------
终端 1，在 ``~/ndnSIM/ns-3`` 启动 Python 控制器：

    python3.8 scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py \
      --port 5555

终端 2，使用相同端口启动仿真：

    ./waf --run "vndn-circle-simulator \
      --rsu-forward-strategy=3 --open-gym-port=5555 --log"

可通过 ``--model-file`` 使用其他 circle TKAN-LSTM checkpoint。
"""

import argparse
import importlib.util
from numbers import Integral
import sys
from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import torch


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
NS3_ROOT = SCRIPT_DIRECTORY.parents[1]
AI_CIRCLE_DIRECTORY = (
    NS3_ROOT / "contrib" / "vndn-nn-rd" / "ai-training" / "circle"
)
# 三个场景的训练入口同名；按绝对文件加载，避免已经导入 grid/spidermap
# 的训练模块时，Python 的模块缓存把 circle 模型绑定到另一训练入口。
_TRAINING_MODULE_NAME = "_vndn_circle_tkan_training"
if _TRAINING_MODULE_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _TRAINING_MODULE_NAME, AI_CIRCLE_DIRECTORY / "train_tkan_lstm.py"
    )
    _training_module = importlib.util.module_from_spec(_spec)
    sys.modules[_TRAINING_MODULE_NAME] = _training_module
    _spec.loader.exec_module(_training_module)
CircleTKANLSTM = sys.modules[_TRAINING_MODULE_NAME].CircleTKANLSTM
FEATURE_NAMES = ("x", "y", "speed", "acceleration", "angle", "lane_index")
SCENARIO_LABELS = {"circle": (0, 1), "grid": tuple(range(7)), "spidermap": tuple(range(7))}


DEFAULT_MODEL_FILE = (
    NS3_ROOT
    / "data"
    / "models"
    / "circle"
    / "tkan-lstm"
    / "20260813-202805"
    / "tkan-lstm-circle-noforward-20260813-202805.pt"
)


def parse_arguments(argv=None, scenario="circle", require_model_file=False) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VNDN {} TKAN-LSTM ns3-gym 推理控制器".format(scenario)
    )
    parser.add_argument("--port", type=int, default=5555, help="ns3-gym TCP port")
    parser.add_argument(
        "--model-file", type=Path, required=require_model_file,
        default=None if require_model_file else DEFAULT_MODEL_FILE,
    )
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default="auto"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable ns3-gym bridge debug output"
    )
    return parser.parse_args(argv)


def select_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("请求使用 CUDA，但当前 PyTorch 不支持 CUDA")
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(requested)


def load_model(
    model_file: Path, device: torch.device, expected_scenario="circle"
) -> tuple:
    """按 checkpoint 元数据重建模型 / Rebuild model from checkpoint metadata."""
    model_file = model_file.expanduser().resolve()
    if not model_file.is_file():
        raise FileNotFoundError("模型文件不存在 / model not found: {}".format(model_file))

    # 本地训练生成的可信 checkpoint；显式参数也避免 PyTorch 的默认值警告。
    # This is a trusted local checkpoint; make the intended pickle mode explicit.
    checkpoint = torch.load(str(model_file), map_location=device, weights_only=False)
    validate_checkpoint(checkpoint, expected_scenario)

    parameters = checkpoint["model_parameters"]
    model = CircleTKANLSTM(
        input_size=int(parameters["input_size"]),
        hidden_size=int(parameters["hidden_size"]),
        output_size=int(parameters["output_size"]),
        grid_size=int(parameters["grid_size"]),
        spline_order=int(parameters["spline_order"]),
        dropout=float(parameters["dropout"]),
    ).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model, checkpoint, model_file


def validate_checkpoint(checkpoint: Dict, expected_scenario: str) -> None:
    """Validate the model's scenario and fixed C++ 10×6 observation contract."""
    if expected_scenario not in SCENARIO_LABELS:
        raise ValueError("unsupported scenario: {}".format(expected_scenario))
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be a dictionary")
    required = {
        "model_parameters",
        "state_dict",
        "feature_names",
        "label_values",
        "normalization_mean",
        "normalization_std",
    }
    missing = required.difference(checkpoint)
    if missing:
        raise ValueError("checkpoint 缺少字段 / missing keys: {}".format(sorted(missing)))

    # 保留旧 circle checkpoint 的无 scenario 元数据兼容性；新七类场景
    # 必须明确标记名称，不能靠相同的输出维度推断场景。
    scenario = checkpoint.get("scenario", "circle" if expected_scenario == "circle" else None)
    if scenario != expected_scenario:
        raise ValueError(
            "checkpoint scenario must be {!r}, got {!r}".format(expected_scenario, scenario)
        )
    parameters = checkpoint["model_parameters"]
    if not isinstance(parameters, dict):
        raise ValueError("model_parameters must be a dictionary")
    expected_labels = SCENARIO_LABELS[expected_scenario]
    for field, expected in (
        ("input_size", len(FEATURE_NAMES)), ("sequence_length", 10),
        ("output_size", len(expected_labels)),
    ):
        actual = parameters.get(field)
        if isinstance(actual, bool) or not isinstance(actual, Integral) or actual != expected:
            raise ValueError("{} must be {}, got {!r}".format(field, expected, actual))
    if list(checkpoint["feature_names"]) != list(FEATURE_NAMES):
        raise ValueError("feature_names must match the C++ order: {}".format(FEATURE_NAMES))
    labels = checkpoint["label_values"]
    if (
        not isinstance(labels, (list, tuple))
        or len(labels) != len(expected_labels)
        or any(isinstance(label, bool) or not isinstance(label, Integral) for label in labels)
        or set(labels) != set(expected_labels)
    ):
        raise ValueError("label_values must contain each RSU exactly once: {}".format(expected_labels))
    for field in ("normalization_mean", "normalization_std"):
        try:
            values = np.asarray(checkpoint[field], dtype=np.float32)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid {}: {}".format(field, error)) from error
        if values.shape != (len(FEATURE_NAMES),) or not np.isfinite(values).all():
            raise ValueError("{} must contain six finite values".format(field))
        if field == "normalization_std" and not (values > 0).all():
            raise ValueError("normalization_std must be strictly positive")


def probabilities_for_candidates(
    observation: Dict[str, Sequence],
    model: CircleTKANLSTM,
    checkpoint: Dict,
    device: torch.device,
) -> np.ndarray:
    """推理并按 C++ 给出的候选 RSU 顺序排列概率。"""
    parameters = checkpoint["model_parameters"]
    sequence_length = int(parameters["sequence_length"])
    input_size = int(parameters["input_size"])
    features = np.asarray(observation["features"], dtype=np.float32).reshape(
        sequence_length, input_size
    )
    candidate_rsu_ids = np.asarray(observation["rsu_ids"], dtype=np.int64)
    mean = np.asarray(checkpoint["normalization_mean"], dtype=np.float32)
    standard_deviation = np.asarray(
        checkpoint["normalization_std"], dtype=np.float32
    )
    normalized = (features - mean) / standard_deviation

    inputs = torch.from_numpy(normalized).unsqueeze(0).to(device)
    with torch.no_grad():
        logits = model(inputs)
        label_probabilities = torch.softmax(logits, dim=1)[0].cpu().numpy()

    label_to_index = {
        int(label): index for index, label in enumerate(checkpoint["label_values"])
    }
    probabilities = np.zeros(len(candidate_rsu_ids), dtype=np.float32)
    for index, rsu_id in enumerate(candidate_rsu_ids):
        model_index = label_to_index.get(int(rsu_id))
        if model_index is not None:
            probabilities[index] = label_probabilities[model_index]

    probability_sum = float(probabilities.sum())
    if probability_sum <= 0.0:
        raise ValueError(
            "候选 RSU 与模型标签没有交集 / candidate RSUs do not match model labels: "
            "candidates={}, labels={}".format(
                candidate_rsu_ids.tolist(), checkpoint["label_values"]
            )
        )
    # 如果未来拓扑只暴露模型标签的子集，应在可用候选中重新归一化。
    # Renormalize when only a subset of trained labels exists in the topology.
    probabilities /= probability_sum
    # Python 端只返回与候选 RSU 顺序一致的概率，不在这里截断候选。
    # 是否启用双路径由 C++ 协议层统一决定，避免推理端和仿真端规则不一致。
    return probabilities


def main(argv=None, expected_scenario="circle", require_model_file=False) -> int:
    arguments = parse_arguments(argv, expected_scenario, require_model_file)
    device = select_device(arguments.device)
    model, checkpoint, model_file = load_model(
        arguments.model_file, device, expected_scenario=expected_scenario
    )
    print("Model / 模型: {}".format(model_file))
    print("Device / 设备: {}".format(device))
    print("Labels / 标签: {}".format(checkpoint["label_values"]))
    print("Waiting for ns-3 / 等待仿真连接: tcp://localhost:{}".format(arguments.port))

    # 离线加载/验证不依赖 Gym，也不会创建 socket；元数据错误在连接前报告。
    from ns3gym import ns3env

    environment = ns3env.Ns3Env(
        port=arguments.port,
        stepTime=0.0,
        startSim=False,
        simSeed=0,
        simArgs={},
        debug=arguments.debug,
    )
    observation = environment.reset()
    decision_count = 0
    try:
        while True:
            action = probabilities_for_candidates(
                observation, model, checkpoint, device
            )
            candidate_ids = np.asarray(observation["rsu_ids"], dtype=np.int64)
            obu_id = int(np.asarray(observation["obu_id"])[0])
            print(
                "Decision {} / 决策 {}: OBU={} probabilities={}".format(
                    decision_count,
                    decision_count,
                    obu_id,
                    {
                        int(rsu_id): round(float(probability), 6)
                        for rsu_id, probability in zip(candidate_ids, action)
                    },
                )
            )
            observation, reward, done, info = environment.step(action)
            decision_count += 1
            if done:
                break
    except KeyboardInterrupt:
        print("Ctrl-C -> Exit / 用户终止")
    finally:
        environment.close()
    print("Done / 完成，共 {} 次决策".format(decision_count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
