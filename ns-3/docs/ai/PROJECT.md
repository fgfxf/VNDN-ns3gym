# 项目事实与导航

更新日期：2026-10-21。供后续 AI 修改前建立上下文；开发与验证约束以适用的 `AGENTS.md` 为准。

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

2026-10-20 用户批准了交付缺陷的正式修复，修改已落实到 Router cc/h 和两个传输层文件。
Router 对已有有效神经回程的 pending 业务请求，在网络 Face 收包后清除匹配 PIT 的网络 in-record，
保留本地应用 in-record、服务器 out-record 和原有定时器。这样即使默认 BestRoute2 抑制了重复 Interest
向应用的再次投递，服务器 Data 仍先交给 Router 应用，由应用附加目标 OBU 标签后发往选定 RSU。
晚到的神经路由指令也清理已经留下的网络下游；Stop 断开收包订阅。

`GenericLinkService` 在分片前读取完整包的非零目标 MAC，通过发送 endpoint 传给每个分片；
`NetDeviceTransport` 的非 P2P 分支优先使用该 endpoint，endpoint 为零时保留原 LP 标签处理。
P2P 设备仍按原路径发送，本地传输和接收重组未修改。此修复沿用项目已有的八字节
`ns3::Address` 编码约定，未修改模型权重、概率选择阈值或增加应用补救策略。
作用范围与实际验收见 [正式修复记录](NEURAL_DELIVERY_FIX_20261020.md)，
修改前定位与隔离原型见 [原计划](NEURAL_DELIVERY_FIX_PLAN_20261020.md)。

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

2026-10-21新增正式实验入口：`--training-snapshots`与实验配置的`training_snapshots`布尔字段
启用RSU被动观测，输出`training-observations.jsonl`及`face-roles.json`。
输入由在线Gym与采样共用的函数构造，保留真实hello接收时间、空/短历史和多源请求身份。
`tools/experiments/build_training_dataset.py`按显式run清单及train/validation/evaluation划分，
将Router回程Face收到的首个业务Data与车辆关联事件匹配；过期、未知、失联等标签排除并报告，
请求性能分母不因此改变。每个源RSU仅用该请求第一次合格观测，不按结果行重新滑窗。

三场景训练器通过`--dataset-manifest`调用共享`formal_training.py`，保持各自模型入口及
共享`efficient_kan`；使用mmap数据、train归一化/类别权重、验证macro-F1优先选模及早停。
正式checkpoint保存观测/标签契约、split及源码/数据哈希、初始化种子和固定选择阈值。
控制器`--require-formal-contract`拒绝旧契约或错场景模型；
临时模型需要明确`--allow-validation-only`，不能用于正式统计。
实验C++另输出`neural-decisions.jsonl`，记录实际接受的float概率、目标站及fallback，
完成标记核对记录数。真实模型运行器同时封存`controller-decisions.jsonl`，
保留完整Python概率和预期选站，核对其行数与C++动作计数。
实验编排入口为`tools/experiments/campaign.py`，训练/评估/图集阶段入口为
`campaign_workflow.py`；阶段依赖、输入、源码、模型与产物均验证哈希，失败attempt保留。
上述入口的真实三场景验收与正式数据进度见
[执行记录](RETRAIN_EXECUTION_20261021.md)，不能把工具实现完成视作新模型已经训练完成。

以下为保留的旧CSV兼容模式，其标签语义与新正式契约不同：

- OBU 输出每车 `training-tag-<obu>.csv`、RTT 和统计文件；训练行包含请求发送时的六维状态，以及 DATA/TIMEOUT 结果出现时的服务 RSU 编号。
- 三个场景分别在 `ai-training/circle/`、`ai-training/grid/`、`ai-training/spidermap/` 内维护完整的训练脚本、测试、README 和 Python 3.8 依赖。训练与模型实现各自独立，KAN 投影共享 `ai-training/efficient_kan/kan.py`。
- 训练说明：[圆圈](../../contrib/vndn-nn-rd/ai-training/circle/README.md)、[方阵](../../contrib/vndn-nn-rd/ai-training/grid/README.md)、[蜘蛛网](../../contrib/vndn-nn-rd/ai-training/spidermap/README.md)。三个训练器沿用相同 TKAN-LSTM 网络和 checkpoint 权重结构。
- 训练使用交叉熵与 Adam。窗口保持时间顺序，不跨车辆或运行边界；训练与验证按完整运行划分，归一化参数只从训练数据估计。
- 数据选择默认只接受 `simulation-config.txt` 标记为 NoForward 的运行，并等待每车 `-stats.txt` 完成标记；RTT 文件不作为训练输入。
- 窗口最后一条样本的 RSU 标签作为分类输出。标签来自请求结果时刻，不能仅凭窗口索引将其描述为“当前基站标签”。
- checkpoint 保存模型结构参数、标签映射、归一化参数及权重。Python 控制器重建模型并执行 softmax 推理，不进行在线训练。
- `VndnRsu::GetNeuralReward()` 当前恒返回 0；gym 在本方案中承担仿真与推理桥接。
- 仿真输出位于 `data/<scenario>/<日期>/<时间>/`；模型默认写入 `data/models/<circle|grid|spidermap>/tkan-lstm/<时间戳>/`，附训练历史和摘要。路径中的示例日期或模型不是永久可用承诺。

方阵和蜘蛛网训练必须显式提供 `--data-root` 日期目录，分别对应 `data/grid-vanet-test/<日期>` 和 `data/fgfxf-spider-map/<日期>`，默认只选择 NoForward 数据。新增训练器将无效行（例如失联标签 -1、越界标签或非有限数值）作为序列断点，报告排除量，不允许窗口跨越断点。训练与验证仍按完整 run 隔离；有效训练窗口目标必须覆盖全部 0–6 基站，否则报错提示补采。输入配置当前没有可信的场景标识字段，使用者仍须核对采样来源。

至少两个 run 是划分训练/验证集的技术下限，不代表科研样本量充分。每车 stats 也不证明整轮仿真成功；正式训练前需核实采样进程完成状态。

## 模型与场景兼容性

圆圈控制器 [`vndn-circle-tkan-gym.py`](../../scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py) 有默认 checkpoint 路径，运行前必须核实文件存在并匹配本次实验。

方阵与蜘蛛网的控制器复用圆圈推理逻辑，并要求显式传入 `--model-file`。连接 Gym 前校验场景、完整七类标签、模型输入输出维度、10 步序列、特征顺序和归一化参数，拒绝圆圈模型及另一个七基站场景的模型。校验通过只证明接口匹配，不证明训练数据来源或模型效果。

两个场景的 `run-vndn-*.sh` 默认运行 NoForward；带模型仿真需显式指定 `--rsu-forward-strategy=3`。当前 Python 控制器收到 done 后退出，一次启动服务一轮仿真；批量运行十轮不会自动重启十次控制器。

## 关键文件导航

旧论文的八张参考图、输入清单、RTT/流量统计、旧 KAN 混淆矩阵及与当前实现的差异，见
[旧实验与出图记录](LEGACY_EXPERIMENTS.md)。该记录依据 `ns-3_old/旧的实验效果图/` 的用户整理材料；
保留历史处理口径与待核实事项，不将旧结果视为当前重写版的性能验收。

导师新增的 Interest 数量、车速、车辆数量三组扫描及五指标出图设计，见
[实验对比与出图方案](EXPERIMENT_COMPARISON_PLAN.md)。用户确认二次转发包含所有额外业务 Data 副本，
控制负载覆盖本项目新增控制协议，网络/控制主图采用累计发送 Mbit；文档保留原始完整设计及与当前采集范围的差别，正式对比实验尚未执行。

后续用户批准了**不修改底层的采集实现**，操作与当前统计口径见
[实验采集使用说明](EXPERIMENT_COLLECTION.md)。三个场景新增可选 `--experiment-config`；
独立 SUMO 输入及显式请求计划控制车辆数、速度设置和首次业务请求总数。应用记录每个请求的生成和唯一终态，
测量结束后继续排空。新入口不依赖旧 `--obu-frequency` 的随机发包间隔。

`tools/experiments/` 提供输入生成、串行四算法运行、完整性检查和逐轮汇总，产物与旧训练 CSV 分开。
采集器订阅现有 L3 TraceSource，只累计网络 Face 的出站 Interest/Data `wireEncode()` 字节；
Nack 单列次数。控制子集包含 hello、p2p-handshake、search/find、neural-route/neural-pit；
封装业务 Data 的 forward 计入网络负载，不能整包算纯控制负载。
额外 Data 指标是应用可观察的预测额外路径、补救转送和同一无线方向重复提交，
不涵盖所有隐式 NFD 副本，也不证明设备实际接受或发送成功。论文必须保留这些限定。

上述采集工作当时未修改 `src/` 的传输、转发、策略或重组代码，也未改变既有模型权重。
随后获准的交付修复涉及两个传输层文件，统计口径仍是 L3 出站字节及应用显式提交次数，
不能将分片目的地址修复后的 L3 数值解释为完整 MAC 开销。
未指定实验配置时仍使用旧运行入口；正式出图、独立重复和效应统计需要另外验收。

| 关注点 | 文件 |
|---|---|
| 车辆请求、切换、数据记录 | [apps/vndn-obu.cc](../../contrib/vndn-nn-rd/apps/vndn-obu.cc) |
| RSU 状态、gym、回程决策 | [apps/vndn-rsu.cc](../../contrib/vndn-nn-rd/apps/vndn-rsu.cc) |
| Router 控制与 Data 回程 | [apps/vndn-router.cc](../../contrib/vndn-nn-rd/apps/vndn-router.cc) |
| 分片目的地址传递与设备发送 | [generic-link-service.cpp](../../src/ndnSIM/NFD/daemon/face/generic-link-service.cpp)、[ndn-net-device-transport.cpp](../../src/ndnSIM/model/ndn-net-device-transport.cpp) |
| 最近 RSU 与单双路径选择 | [model/vndn-rsu-forwarding-policy.cc](../../contrib/vndn-nn-rd/model/vndn-rsu-forwarding-policy.cc) |
| NFD 控制报文特殊行为 | [forwarder.cpp](../../src/ndnSIM/NFD/daemon/fw/forwarder.cpp)、[strategy.cpp](../../src/ndnSIM/NFD/daemon/fw/strategy.cpp) |
| SUMO 与 gym 集成 | [src/traci](../../src/traci/)、[src/opengym](../../src/opengym/) |
| 圆圈训练与模型 | [ai-training/circle](../../contrib/vndn-nn-rd/ai-training/circle/) |
| 方阵训练与模型 | [ai-training/grid](../../contrib/vndn-nn-rd/ai-training/grid/) |
| 蜘蛛网训练与模型 | [ai-training/spidermap](../../contrib/vndn-nn-rd/ai-training/spidermap/) |

## 现有覆盖及证据边界

- [C++ 测试](../../contrib/vndn-nn-rd/test/vndn-rsu-forwarding-policy-test.cc) 注册 `vndn-rsu-forwarding-policy` 和 `vndn-neural-return-selection` 两个套件，覆盖最近 RSU、空候选、单双路径选择和候选/概率长度不匹配等行为。
- [Python 测试](../../contrib/vndn-nn-rd/ai-training/circle/tests/test_circle_tkan.py) 覆盖窗口顺序与运行边界、模型输出形状及反向传播。
- 新场景训练测试覆盖数据筛选、无效断点、七类窗口、checkpoint 和临时七类数据的一轮 CPU 训练；[推理测试](../../contrib/vndn-nn-rd/ai-training/tests/test_tkan_inference.py) 验证场景/标签兼容性及候选概率映射。各目录独立进程运行，避免同名训练模块相互干扰。
- 新增 `vndn-experiment-config`、`vndn-experiment-recorder`、`vndn-l3-experiment-tracer` 三个 C++ 套件，
  及 `tools/experiments/tests/` 的输入、运行和汇总测试；统一回归入口执行上述测试。
- [Router PIT 测试](../../contrib/vndn-nn-rd/test/vndn-router-neural-pit-test.cc) 的十例使用真实 P2P、NFD 和 Router 应用，
  覆盖默认 BestRoute2 抑制窗口内的重复请求、单双目标、晚路由指令、非神经/无 pending/不同 selector/非业务请求、
  Stop 销毁、Nack 和超时后重试。
- [分片目的地址测试](../../contrib/vndn-nn-rd/test/vndn-fragment-destination-test.cc) 的十九例覆盖真实 GLS 分片与逆序重组、
  endpoint/标签优先级、设备发送地址、无标签与零目标控制包、P2P、本地 AppLinkService 和 InternalForwarderTransport。
  记录设备发送调用不等于验证 WiFi 空口交付或 MAC 重试。
- 2026-10-20 正式修复后的统一回归包含构建、七个 C++ 套件和五组 Python 测试，共十三步骤全部通过，
  见 [单元报告](../../build/validation/20261020T154751.173146Z-c470c777/report.json)。
  Router 测试明确使用 CS-miss、静态 P2P Face；动态新增 Face、CS-hit、
  按 Name 聚合之外的完整多 selector 应用语义及开启 LP 可靠重传后的目的地址保持，不在该保证内。
- 单元通过不证明三场景端到端交付、模型泛化或神经方案的性能非劣性；场景证据与限制统一记录于
  [正式修复记录](NEURAL_DELIVERY_FIX_20261020.md)，不能以套件数量代替实验结论。
- 本文初始化依据是本次可见对话、当前源码及本地 Git 历史；没有读取或声称分析全部历史聊天。
- 近期 Git 记录提供演进线索：`858cbda` 修复 RTVTDF，`f5f92b5` 添加训练代码，`0a2973d` 添加神经网络决策，`74145ce` 修复神经网络问题，`e1d0bd6` 添加更多场景。提交标题不能替代测试和实验结果。
- 构建和测试的实际执行证据见 [CHANGELOG.md](CHANGELOG.md)；源码核对本身不能认证性能优势或论文结论。
