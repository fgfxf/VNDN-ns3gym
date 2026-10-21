# ns-3 主项目工作入口

继承并遵守 [工作区 AGENTS.md](../AGENTS.md)。本目录是当前开发版本。

- 开始修改前阅读 [项目说明](docs/ai/PROJECT.md)、[验证指南](docs/ai/VALIDATION.md)
  和 [近期变更记录](docs/ai/CHANGELOG.md)。不要把通用 ns-3 README 当作本研究的完整说明。
- 研究旧论文图、比较指标或延续历史实验时，先读 [旧实验与出图记录](docs/ai/LEGACY_EXPERIMENTS.md)；
  旧图的筛选/流量口径与旧 KAN 实现不能直接当作当前重写版本的实验定义或验证结果。
- 新的三自变量、五指标对比按 [实验与出图方案](docs/ai/EXPERIMENT_COMPARISON_PLAN.md) 理解口径；
  采集口径以 [实验采集使用说明](docs/ai/EXPERIMENT_COLLECTION.md) 为准：
  采集实现当时未改底层，仅记录网络 Face 的 L3 出站 Interest/Data 字节，以及应用显式提交的额外 Data 次数。
  后者不能标成全部实际发送副本；负载不包含 LP/分片/MAC 开销。控制负载按自定义协议功能分类。
  正式参数、模型和重复次数仍需预实验冻结，不把小规模流程验证当作性能结论。
- 测试先行：相关基线 → 新行为测试预期失败 → 最小实现 → 新测试和相关回归通过 → 更新文档。
- 所有 waf 操作及间接触发构建的脚本，先 `export JOBS=4`；显式构建使用 `-j 4`。
- 跑实验时尽可能避免 `./waf configure`，复用现有配置和增量构建，避免重新配置引发大批量重新编译。
  仅在首次初始化、配置缺失或确需变更构建选项/依赖时使用，并记录原因；不要每轮实验都重新配置。
- 默认相关单元回归入口：`python3.8 tools/validate.py`。
  它不替代三场景仿真验收，详细覆盖与前提见验证指南。
- 核查采集修改是否影响四策略、或判断真实神经模型效果时，先读
  [策略回归与模型核查记录](docs/ai/STRATEGY_REGRESSION_20261020.md)。
  区分同策略修改前后回归、模型目标覆盖率和业务满足率；旧离线100%准确率不能替代在线交付验收。
- 排查神经回程“RSU有出站、车辆未交付”时，先读
  [正式交付修复与验收记录](docs/ai/NEURAL_DELIVERY_FIX_20261020.md)；
  [原型定位与计划](docs/ai/NEURAL_DELIVERY_FIX_PLAN_20261020.md) 保留修改前证据。
  用户已授权正式修复，Router cc/h 与 `generic-link-service.cpp`、
  `ndn-net-device-transport.cpp` 已落实网络 PIT 下游清理及所有分片的目的地址传递。
  这次获准的两个底层文件修改不扩大采集统计口径；L3 负载仍不包含 LP/分片/MAC 开销。
  统一单元回归现含八个 C++ 套件及五组 Python 测试（共享目录包含正式训练契约测试）；
  新增`vndn-training-snapshot`验证旁路观测与实际动作记录。
  Router 与分片测试分别覆盖十例、十九例。
  单元通过和交付改善不等于神经策略已不劣于转发策略，三场景结果及未覆盖边界以验收记录为准。
- 修改 `contrib/vndn-nn-rd/` 或 `src/ndnSIM/NFD/` 时跟踪 Interest、控制消息、PIT、Data 回程全链路。
- 修改 `scratch/vndn-map-simulator-common.h` 同时影响方阵和蜘蛛网；圆圈有独立主程序，也需检查语义一致性。
- 当前学习方案是离线监督训练与模型推理。`GetNeuralReward() == 0` 不意味着研究方案缺失。
- 每次逻辑修改追加 `docs/ai/CHANGELOG.md`；记录实际执行证据，不把 PASS 推广为未覆盖的实验结论。
- 三场景重新采样/训练/论文图按[已授权计划](docs/ai/RETRAIN_AND_FIGURES_PLAN_20261021.md)
  和[执行记录](docs/ai/RETRAIN_EXECUTION_20261021.md)推进。
  新正式数据为RSU实际hello的10×6快照，标签按源RSU从Router首次回程的时间关联服务站；
  旧请求结果CSV仅保留兼容入口，不能混入新正式训练。
  P0–P6已获用户最终授权，不再逐阶段重复询问执行许可。
  2026-10-21首轮预实验7200秒超时，旧等待队列已失败；12轮转发策略采集开关验收已通过，
  用户随后明确要求让已有剩余编译结束后直接跑实验，不再configure或另起批量编译，接受少量非致命瑕疵。
  已用现有程序开始真实三场景baseline，使用`--run-no-build`避免运行入口再次触发编译。
  11:01已启动接续到出图的后台队列，入口为
  `build/validation/runtime-diagnosis-20261021/no-build-entry/continue_experiments.py`；
  查`plan/direct-pipeline-state.json`与`plan/direct-pipeline.log`。
  它等待当前三场景基准完成后直接采集918轮训练/验证/独立评估数据，训练三个固定模型，
  再运行既有模型工程核查、4080轮正式测试与出图；不再执行其余重复pilot或临时模型预演。
  这是按用户最新指令调整工程准备顺序，未执行的预演不得标为通过，正式20种子不减少。
  不要重启旧的`queued-driver`或优化构建脚本，也不要与新队列并行启动仿真。
  最新状态见[运行恢复记录](docs/ai/RETRAIN_RUNTIME_RECOVERY_20261021.md)。开始新的运行前检查
  `data/experiments/retrain-20261021/plan/queued-driver-state.json`、`state-pilot.json`
  及`long-driver-state.json`、`plan/resumed-real-experiments-launch.json`、
  执行记录，避免另起并发构建或仿真。阶段完成不等于正式图集完成；
  已封存的生产源码和执行辅助脚本在运行期间不得混改。

- **2026-10-21 11:44 用户已要求关闭当前仿真。** 当前仿真及自动接续队列已停止，
  原始数据保留。停止记录为`data/experiments/retrain-20261021/plan/user-stop-20261021.json`。
  上述自动执行授权已被本次停止指令中止，不得自行重启队列或后续实验，等待用户新的执行指令。
