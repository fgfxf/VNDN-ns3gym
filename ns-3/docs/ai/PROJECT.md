# 项目事实与导航

更新日期：2026-10-18。供后续 AI 修改前建立上下文；开发与验证约束以适用的 `AGENTS.md` 为准。

## 用户确认的定位

- 本项目是基于 ns-3 / ndnSIM、SUMO 和 ns3-gym 的车联网实验，研究车辆切换边缘基站时，NDN Data 回程沿原路径返回导致无法送达车辆的问题。
- 当前方案已经采用**离线监督训练 + 模型推理**实现：根据车辆状态估计 Data 回程时适合接收的基站，由上级边缘路由器向选定基站转发；目标可以是原基站，也可以是其他基站。
- 用户已明确上述方案就是当前完成方案；不要将“强化学习”写成当前实现或待完成目标。是否使用 ns3-gym 不能作为强化学习的判据。
- 主项目是 `/home/fgfxf/ndnSIM/ns-3`，由 AI 重新实现；`/home/fgfxf/ndnSIM/ns-3_old` 是用户此前手写版本，只读参考，不能用旧实现覆盖当前协议。
- “源码实现已完成”是用户提供的项目状态；正确性、性能和学术结论仍需对应测试与实验支持。

## 已核实的架构与回程流程

代码主模块为 [`contrib/vndn-nn-rd`](../../contrib/vndn-nn-rd/)。其 [wscript](../../contrib/vndn-nn-rd/wscript) 依赖 `core`、`network`、`mobility`、`wave`、`ndnSIM`、`traci`、`opengym`。

1. SUMO 提供道路交通与车辆移动，TraCI 将车辆创建、退出及移动状态接入 ns-3。
2. 车辆 OBU 通过无线链路接入 RSU；RSU 通过有线链路连接上级 Router，Router 再连接内容 Server。
3. OBU 请求经当前 RSU 上行。神经网络策略下，RSU 从车辆 hello 状态历史中提取最近 10 步输入，不足时以最早状态左侧填充。
4. 每步六维特征按 `x, y, speed, acceleration, angle, laneIndex` 排列；ns3-gym 传输状态和候选 RSU 编号，Python 推理返回按候选顺序排列的概率。
5. C++ 选择概率最高的 RSU；当前默认规则下，前两名概率差不超过 0.10，或第二名概率至少 0.10 时，选择两条回程路径。
6. RSU 经 `/vndn/control/neural-route` 通知 Router；Router 经 `/vndn/control/neural-pit` 为目标 RSU 预备无线 PIT，Data 返回时向选定 RSU 转发，再送往车辆。

这不是只改应用层的项目。NFD 的 `forwarder.cpp`、`strategy.cpp` 对 `/vndn/control` 具有特定的 CS、PIT 和记录清理规则；修改协议必须考虑这些底层行为。

## 三个场景与策略

| 场景 | C++ 入口（相对 ns-3） | SUMO 资源目录（`contrib/vndn-nn-rd/traces/` 下） | 当前默认值 |
|---|---|---|---|
| 圆圈 | `scratch/vndn-circle-simulator/vndn-circle-main.cc` | `circle-simple` | 80 秒，2 RSU，NeuralNetwork |
| 方阵 | `scratch/vndn-grid-simulator/vndn-grid-main.cc` | `grid-vanet-test` | 230 秒，7 RSU，NoForward |
| 蜘蛛网 | `scratch/vndn-spidermap-simulator/vndn-spidermap-main.cc` | `fgfxf-spider-map` | 230 秒，7 RSU，NoForward |

方阵和蜘蛛网复用 [`scratch/vndn-map-simulator-common.h`](../../scratch/vndn-map-simulator-common.h)，各自的全部 RSU 连接同一个 Router；不要从旧版照搬跨 Router 或 RSU–RSU 旁路结构。

`--rsu-forward-strategy` 的编号统一为：`0=NoForward`、`1=VTDF`、`2=RealTimeVTDF`、`3=NeuralNetwork`。场景默认值不同，比较实验必须显式记录策略。

所有 waf 构建、运行和可能触发构建的测试前，必须 `export JOBS=4` 限制并行数。NeuralNetwork 场景需要相同端口的 Python 控制器，默认 gym 端口为 5555；只启动仿真可能等待连接。

## 离线训练与在线推理

- OBU 输出每车 `training-tag-<obu>.csv`、RTT 和统计文件；训练行包含请求发送时的六维状态，以及 DATA/TIMEOUT 结果出现时的服务 RSU 编号。
- [训练说明](../../contrib/vndn-nn-rd/ai-training/circle/README.md) 和 [训练代码](../../contrib/vndn-nn-rd/ai-training/circle/train_tkan_lstm.py) 定义 TKAN-LSTM 服务 RSU 分类器；KAN 投影来自共享的 `ai-training/efficient_kan/kan.py`。
- 训练使用交叉熵与 Adam。窗口保持时间顺序，不跨车辆或运行边界；训练与验证按完整运行划分，归一化参数只从训练数据估计。
- 数据选择默认只接受 `simulation-config.txt` 标记为 NoForward 的运行，并等待每车 `-stats.txt` 完成标记；RTT 文件不作为训练输入。
- 窗口最后一条样本的 RSU 标签作为分类输出。标签来自请求结果时刻，不能仅凭窗口索引将其描述为“当前基站标签”。
- checkpoint 保存模型结构参数、标签映射、归一化参数及权重。Python 控制器重建模型并执行 softmax 推理，不进行在线训练。
- `VndnRsu::GetNeuralReward()` 当前恒返回 0；gym 在本方案中承担仿真与推理桥接。
- 仿真输出位于 `data/<scenario>/<日期>/<时间>/`；circle 模型默认写入 `data/models/circle/tkan-lstm/<时间戳>/`。路径中的示例日期或模型不是永久可用承诺。

## 模型与场景兼容性

圆圈控制器 [`vndn-circle-tkan-gym.py`](../../scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py) 有默认 checkpoint 路径，运行前必须核实文件存在并匹配本次实验。

方阵与蜘蛛网的控制器复用圆圈推理逻辑，但强制显式传入 `--model-file`；应分别使用对应场景、覆盖全部 7 个 RSU 标签的 checkpoint，不能把圆圈的两类模型当作可用替代。启动参数检查不等于训练数据、标签覆盖和模型效果已验证。

## 关键文件导航

| 关注点 | 文件 |
|---|---|
| 车辆请求、切换、数据记录 | [apps/vndn-obu.cc](../../contrib/vndn-nn-rd/apps/vndn-obu.cc) |
| RSU 状态、gym、回程决策 | [apps/vndn-rsu.cc](../../contrib/vndn-nn-rd/apps/vndn-rsu.cc) |
| Router 控制与 Data 回程 | [apps/vndn-router.cc](../../contrib/vndn-nn-rd/apps/vndn-router.cc) |
| 最近 RSU 与单双路径选择 | [model/vndn-rsu-forwarding-policy.cc](../../contrib/vndn-nn-rd/model/vndn-rsu-forwarding-policy.cc) |
| NFD 控制报文特殊行为 | [forwarder.cpp](../../src/ndnSIM/NFD/daemon/fw/forwarder.cpp)、[strategy.cpp](../../src/ndnSIM/NFD/daemon/fw/strategy.cpp) |
| SUMO 与 gym 集成 | [src/traci](../../src/traci/)、[src/opengym](../../src/opengym/) |
| 圆圈训练与模型 | [ai-training/circle](../../contrib/vndn-nn-rd/ai-training/circle/) |

## 现有覆盖及证据边界

- [C++ 测试](../../contrib/vndn-nn-rd/test/vndn-rsu-forwarding-policy-test.cc) 注册 `vndn-rsu-forwarding-policy` 和 `vndn-neural-return-selection` 两个套件，覆盖最近 RSU、空候选、单双路径选择和候选/概率长度不匹配等行为。
- [Python 测试](../../contrib/vndn-nn-rd/ai-training/circle/tests/test_circle_tkan.py) 覆盖窗口顺序与运行边界、模型输出形状及反向传播。
- 这些单元测试的存在不证明三场景端到端回程、PIT 生命周期、模型泛化或切换收益已验证；实际执行结果应进入变更记录。
- 本文初始化依据是本次可见对话、当前源码及本地 Git 历史；没有读取或声称分析全部历史聊天。
- 近期 Git 记录提供演进线索：`858cbda` 修复 RTVTDF，`f5f92b5` 添加训练代码，`0a2973d` 添加神经网络决策，`74145ce` 修复神经网络问题，`e1d0bd6` 添加更多场景。提交标题不能替代测试和实验结果。
- 构建和测试的实际执行证据见 [CHANGELOG.md](CHANGELOG.md)；源码核对本身不能认证性能优势或论文结论。
