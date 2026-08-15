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


if not any(argument == "--model-file" or argument.startswith("--model-file=")
           for argument in sys.argv[1:]):
    raise SystemExit(
        "grid 必须通过 --model-file 指定包含 7 个 RSU 标签的 checkpoint / "
        "a grid checkpoint with all seven RSU labels is required"
    )

controller = (
    Path(__file__).resolve().parents[1]
    / "vndn-circle-simulator"
    / "vndn-circle-tkan-gym.py"
)
runpy.run_path(str(controller), run_name="__main__")
