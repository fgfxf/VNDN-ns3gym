# ns-3 主项目工作入口

继承并遵守 [工作区 AGENTS.md](../AGENTS.md)。本目录是当前开发版本。

- 开始修改前阅读 [项目说明](docs/ai/PROJECT.md)、[验证指南](docs/ai/VALIDATION.md)
  和 [近期变更记录](docs/ai/CHANGELOG.md)。不要把通用 ns-3 README 当作本研究的完整说明。
- 研究旧论文图、比较指标或延续历史实验时，先读 [旧实验与出图记录](docs/ai/LEGACY_EXPERIMENTS.md)；
  旧图的筛选/流量口径与旧 KAN 实现不能直接当作当前重写版本的实验定义或验证结果。
- 新的三自变量、五指标对比按 [实验与出图方案](docs/ai/EXPERIMENT_COMPARISON_PLAN.md) 理解口径；
  二次转发包含预测复制等全部额外业务 Data 副本，控制负载按自定义协议功能分类。
  方案中的参数和采集接口尚待实施与预实验验证，不把文档建议当作已有实验结果。
- 测试先行：相关基线 → 新行为测试预期失败 → 最小实现 → 新测试和相关回归通过 → 更新文档。
- 所有 waf 操作及间接触发构建的脚本，先 `export JOBS=4`；显式构建使用 `-j 4`。
- 跑实验时尽可能避免 `./waf configure`，复用现有配置和增量构建，避免重新配置引发大批量重新编译。
  仅在首次初始化、配置缺失或确需变更构建选项/依赖时使用，并记录原因；不要每轮实验都重新配置。
- 默认相关单元回归入口：`python3.8 tools/validate.py`。
  它不替代三场景仿真验收，详细覆盖与前提见验证指南。
- 修改 `contrib/vndn-nn-rd/` 或 `src/ndnSIM/NFD/` 时跟踪 Interest、控制消息、PIT、Data 回程全链路。
- 修改 `scratch/vndn-map-simulator-common.h` 同时影响方阵和蜘蛛网；圆圈有独立主程序，也需检查语义一致性。
- 当前学习方案是离线监督训练与模型推理。`GetNeuralReward() == 0` 不意味着研究方案缺失。
- 每次逻辑修改追加 `docs/ai/CHANGELOG.md`；记录实际执行证据，不把 PASS 推广为未覆盖的实验结论。
