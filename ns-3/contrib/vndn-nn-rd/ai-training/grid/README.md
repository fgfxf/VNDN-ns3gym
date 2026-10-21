# 方阵 TKAN-LSTM 离线训练

2026-10-21批次采用实际hello观测快照与统一回程时刻标签，详见
[正式数据集、训练与评估流程](../FORMAL_PIPELINE.md)。
下面旧CSV流程保留兼容，不能直接作为该批正式论文数据入口。

本目录从 grid 场景的 `training-tag-<obu>.csv` 训练七类服务 RSU 分类器。
它沿用 [circle](../circle/) 的独立 `train_tkan_lstm.py` 结构，包含数据处理、
TKAN-LSTM、训练及 checkpoint 保存；仅复用 [efficient_kan](../efficient_kan/kan.py)
中的 `KANLinear`。这是离线监督学习，ns3-gym 用于推理通信。

所有命令均在 `/home/fgfxf/ndnSIM/ns-3` 执行。复用已有 waf 配置；日常采样和推理
无需重新运行 `./waf configure`。任何可能触发 waf 的命令前必须 `export JOBS=4`。

## 1. 采集 NoForward 数据

先完成至少两次原路返回仿真。下面展示两轮固定、可区分种子的采样；正式训练通常需要
更多 run 和更丰富的车辆状态，数量应根据有效窗口与标签覆盖确定。

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
(
  for run in 1 2; do
    ./waf --run "vndn-grid-simulator --s=230 --rsu-forward-strategy=0 --sumo-gui=0 --save-data=1 --RngSeed=1 --RngRun=$run --sumo-seed=$run --srand-seed=$run" || exit "$?"
  done
)
```

也可运行现有批量采样脚本（当前默认 NoForward）：

```bash
export JOBS=4
./scratch/vndn-grid-simulator/run-vndn-grid.sh 10
```

该脚本目前只接收运行次数，不能用它传入 `--rsu-forward-strategy=3`。它在单轮失败
或 300 秒超时后仍可能继续，整体退出码不能证明采样成功。核对每轮完成状态和退出码，
排除失败/超时 run 后再训练。不要在采样仍在进行时开始读取同一日期目录。

数据位于 `data/grid-vanet-test/<日期>/<run>/ai-training/`。每行必须是以下七列，无表头：

```text
x,y,speed,acceleration,angle,lane_index,result_rsu_id
```

最后一列是请求结果出现时的 RSU，合法编号为 `0–6`。只接收配置
`RsuForwardStrategy=NoForward`（可由 `--forward-strategy` 改变）的 run；忽略 RTT、
零字节文件及没有同名 `-stats.txt` 的车辆 CSV。stats 只表示该车输出已结束，不能证明
整轮仿真成功。目录名和编号也不能证明数据来自正确路网：当前 CSV/config 没有场景
元数据。程序拒绝误用另外两个场景在本仓库内的标准数据路径，但允许移动后的自定义
路径；自定义路径的场景来源必须由实验记录确认，并原样进入训练摘要。

## 2. Python 3.8 环境与训练

依赖与 circle 相同；已有可用环境时无需重复安装：

```bash
python3.8 -m pip install --user \
  -r contrib/vndn-nn-rd/ai-training/grid/requirements-python38.txt
```

日期必须显式指定。以下日期仅为示例，请换成已成功完成采样的实际目录：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 \
  contrib/vndn-nn-rd/ai-training/grid/train_tkan_lstm.py \
  --data-root data/grid-vanet-test/20261019 \
  --forward-strategy NoForward --epochs 100 --device cpu --seed 20261019
```

`--device auto`（默认）优先 CUDA，否则 CPU；`--device cuda` 在 CUDA 不可用时明确失败。
其他默认值与 circle 保持一致：batch size 256、hidden size 32、grid size 5、spline order 3、
dropout 0.1、stride 2、learning rate 0.001、validation ratio 0.2、patience 15；默认 seed
仍为 20260812，实验时建议像上例一样显式记录。`--help` 显示全部参数。
当前 C++ 接口固定 `10×6`，因此 `--sequence-length` 仅接受 10，输出固定为 RSU `0–6`
七类。若后续改变接口，应同时修改并测试训练、Python 推理与 C++ 观测。

完整 run 按目录排序，最后约 20% 作为验证集；同一个 run 的所有车辆和片段只属于一个
集合。至少需要两次 run，验证比例不能使训练集为空。只用训练集有效行计算归一化；
训练窗口批次打乱，窗口内时序不打乱，验证窗口不打乱。

可识别的数值无效行被丢弃：非有限/不能表示为 float32 的特征、非有限标签、非整数标签、
越界标签（含 -1）。每行按上述顺序只计入一个原因，并在原位置切断时间片段：

```text
连续有效段 A → 无效行 → 连续有效段 B
```

A/B 各自构造窗口，不能先删行再跨断点拼接，也不会跨车辆或 run。读取失败、乱码、
非数值内容、列数错误（含空白行）会明确报错；不会静默丢弃整个损坏文件。数据本身没有
时间戳，无法识别文件未记录的时间间隔，仅能保证不跨已识别的无效行和车辆/run 边界。

训练前必须满足两个集合各有有效窗口，且**训练窗口的最后一行目标覆盖全部七类**。
仅在 CSV 的前几行出现过某类不足以满足条件。缺类时给出具体编号，停止训练，避免
除零权重或不完整模型；请补采数据，或经记录后调整 stride / run 划分比例。

## 3. 输出与推理

默认保存位置（微秒部分防止同秒重复训练覆盖）：

```text
data/models/grid/tkan-lstm/<YYYYMMDD-HHMMSS-ffffff>/
├── tkan-lstm-grid-noforward-<YYYYMMDD-HHMMSS-ffffff>.pt
├── training-history.csv
└── training-summary.json
```

每次创建新目录，不覆盖已有模型。`--output-root` 可指定其他输出根目录。
checkpoint 保存 circle 兼容的权重布局、`scenario=grid`、七类标签、六维特征顺序、
归一化和模型参数。训练按验证准确率保存最佳权重；history 保留每轮损失与验证准确率。
train/validation loss 以每个目标的类别权重总和作为分母汇总，不将批次均值按样本数
再次平均；同一固定模型与验证数据的报告损失不应因 batch size 而改变。
summary 记录绝对数据路径、完整 train/validation run 清单、参数/seed/device、最佳轮次、
分类权重、每类目标数、按文件/集合/整体的丢弃原因和行数、有效/过短片段数、窗口数，
以及文件发现时的排除计数。训练失败时，筛选计数仍打印到终端；未完成训练不会标记为成功。

终端 1：将模型路径替换为本次实际 `.pt`，启动对应控制器。

```bash
python3.8 scratch/vndn-grid-simulator/vndn-grid-tkan-gym.py \
  --model-file /absolute/path/to/grid-model.pt --port 5555 --device cpu
```

终端 2：显式启用神经网络策略。

```bash
export JOBS=4
./waf --run "vndn-grid-simulator --s=230 --rsu-forward-strategy=3 --open-gym-port=5555 --sumo-gui=0 --save-data=1 --RngSeed=1 --RngRun=1 --sumo-seed=1 --srand-seed=1"
```

控制器检查场景、标签完整性、`10×6` 输入和归一化参数。方阵不能使用其他场景的
checkpoint，包括另一个七基站场景。每次控制器收到 `Done` 即退出，一次启动只服务一轮
仿真；下一轮应重新启动控制器。两端 gym 端口必须一致，同机顺序运行以避免 SUMO/gym
端口冲突。结束后确认本轮控制器和 SUMO 均已退出。

## 测试及证据边界

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 -m unittest discover \
  -s contrib/vndn-nn-rd/ai-training/grid/tests -p 'test_*.py' -v
```

测试覆盖筛选、断点、run/车辆隔离、训练归一化、真实窗口类别覆盖、模型前反向传播和
合成数据上的 `1 epoch CPU 训练 → 保存 .pt → 实际控制器加载 → 候选概率映射`。
冒烟测试固定 seed=20261018，用临时目录，自动清理产物，不使用或覆盖历史实验数据。
该验证不证明模型泛化、SUMO/ns3-gym 跨进程交付或切换收益；正式采样、长训练和科研
对照实验需使用真实场景数据另行执行。统一入口见 [验证指南](../../../../docs/ai/VALIDATION.md)。
