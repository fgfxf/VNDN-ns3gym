#!/usr/bin/env python3.8
"""grid 场景的 TKAN-LSTM ns3-gym 入口 / grid inference entry point.

grid 有 7 个 RSU，不能误用只包含 circle 两类标签的模型，因此必须显式提供
grid 训练产生的 checkpoint：

    python3.8 scratch/vndn-grid-simulator/vndn-grid-tkan-gym.py \
      --port 5555 --model-file data/models/grid/tkan-lstm/<model>.pt

推理协议与 checkpoint 重建逻辑复用 circle 已验证的控制器；模型结构仍使用
``efficient_kan.KANLinear``，此入口不会自行实现 KAN。
"""

import runpy
import sys
from pathlib import Path


_CONTROLLER_PATH = (
    Path(__file__).resolve().parents[1]
    / "vndn-circle-simulator"
    / "vndn-circle-tkan-gym.py"
)
_CONTROLLER = runpy.run_path(str(_CONTROLLER_PATH))
probabilities_for_candidates = _CONTROLLER["probabilities_for_candidates"]


def load_model(model_file, device, require_formal=False, allow_validation_only=False):
    """Load a seven-RSU grid checkpoint without opening a Gym connection."""
    return _CONTROLLER["load_model"](
        model_file, device, expected_scenario="grid", require_formal=require_formal,
        allow_validation_only=allow_validation_only)


def main(argv=None):
    return _CONTROLLER["main"](argv, expected_scenario="grid", require_model_file=True)


if __name__ == "__main__":
    sys.exit(main())
