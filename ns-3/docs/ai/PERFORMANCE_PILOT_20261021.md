# 2026-10-21～22：实现优化小批量验证

用户在只读诊断之后授权：“尝试你给定的方案，小批量测试通过后再告诉我。如果不行，你再继续尝试其他的方案。”
本轮优先改善成功率及交接时延，沿用原统计定义；不重跑整批论文实验，不覆盖已完成的 quick 数据、模型或图。

## 范围与隔离

- 原诊断：[FIGURE_IMPLEMENTATION_DIAGNOSIS_20261021.md](FIGURE_IMPLEMENTATION_DIAGNOSIS_20261021.md)。其中“只诊断”是上一阶段范围，已被本次小批量实施授权更新。
- 新运行数据：`data/experiments/performance-pilot-20261021/`，全部标记 `validation_only`。
- 构建、测试及诊断证据：`build/validation/performance-pilot-20261021/`。
- 复用固定模型、SUMO 输入、请求计划和种子。最初使用旧测试种子 52001 定位问题，因此属于开发性实验，不能充当新的独立确认结果。
- 所有涉及环境的改动对比较算法一致；不增加或删改统计指标来改变优劣方向。
- 不执行 configure；`JOBS=4`，候选只编译必要对象到独立共享库，原对象及程序保持不变。

## 修改前证据

原版 `vndn-training-snapshot` 四项测试通过。随后复跑 circle 基准 Neural，开启 WifiMacQueue/Txop 日志。

运行：`baseline-mac/20261021T154242.850106Z-15405708/`，清单校验通过，实际耗时 172.77 秒。
6000 个请求、4846 个成功，ISR 80.7667%，成功 RTT 476.9939 ms，控制负载 125.670272 Mbit。

在测量窗口 `[20,140)` 秒，RSU0/1 的队列寿命过期移除共 3154 次，重发 21543 次，重试到上限失败 987 次。
过期时队列年龄均值约 514–515 ms，已直接确认存在 500 ms 队列过期问题。
过期日志没有请求名/UID，不能将全部移除计数认定为业务 Data。大帧 ACK 统计使用同节点最近出队帧尺寸代理，边界见原始 JSON。

原始 MAC 日志为该轮 `simulation.log`（约 500 MB），解析结果为 `baseline-mac-diagnosis.json`。
模型目标覆盖的逐请求核查另行记录；不能把目标站正确率当作业务交付成功率。

## 候选 A：Hello 紧凑 JSON

仅将 OBU 的 `j.dump(4)` 改成 `j.dump()`，四策略共享；字段、数值、频率和协议语义不变。

测试先行：提取真实 C++ 序列化表达式，使用项目 nlohmann 库测试 13 个夹具。
原实现解析语义 13 项通过，紧凑要求 13 项失败；随后才生成候选源码，候选 13 项通过。
测试涉及三场景状态、缓存分支、转义/Unicode/字符串空格与数值精度。
正常缓存增量样例每包减少 61 字节；这是夹具载荷证据，不冒充原始完整报文记录。

隔离库：`build/validation/performance-pilot-20261021/overlays/compact-hello/`。
只编译一个 OBU 对象，复用另外九个模块对象；完整构建哈希、命令及库加载验证在 `plan.json`、`report.json`。
运行器复用生产 `run_experiment.py` 的校验，仅直接启动现有二进制以确保加载隔离库；每轮保存 `overlay-provenance.json`。

首轮同输入 Neural：`compact-hello/20261021T154948.671105Z-5f9a0562/`。
6000 个请求、4984 个成功，ISR 83.0667%，RTT 467.1162 ms，控制负载 103.700696 Mbit。
相比原版成功率增加 2.30 个百分点、RTT 降低 9.88 ms、控制负载减少约 17.48%。
该结果只证明首个开发性对照有改善，尚不能认定达到 RTVTDF 或交接时延验收目标。

## 执行状态

2026-10-22已完成五种候选的开发性筛选，保留 A（紧凑JSON）、B（缓存身份修正）、E（省略空增量），
拒绝 C（RTS/CTS）及 D（hello错峰）。最终候选已在两个circle种子及grid、spidermap基准完整运行，
并对两个circle种子用同配置RTVTDF作公平对照。共19轮候选/诊断仿真完成，另做安装后四策略短测。
生产实现已应用A+B+E并完成局部构建、九C++套件45用例暂存验收和安装；安装后验收详见文末。
circle神经方案相对原版改善明确，但同配置RTVTDF总体ISR和平均成功RTT仍更好，**尚未达到总体不劣于RTVTDF的目标**。
grid/spidermap总体ISR相同、平均RTT变化小，不能把circle收益推广到所有场景，亦不声称统计显著。

## 候选 B、C、D 的实际筛选

**B：修正回程缓存的身份。** Router的prepared-PIT格式使用`sender=目标RSU、senderMac=0、targetMac=OBU`。
正常PIT已负责向车辆发送，但RSU应用回调原来又将发送RSU误当作OBU缓存。
新增严格格式判断后退出这个回退分支；带非零targetMac的旧OBU格式仍保留原处理。
真实P2P/SimpleNetDevice、NFD和RSU测试：旧实现被后续身份探测hello诱发第二次发送（期望一次），有效RED；
修正后prepared及两种legacy回退三例全部通过。探测hello不是正常实验车辆，不能据此宣称实验中发生了相同重放。
circle A与A+B的45项非身份指标、7个原始文件完全一致；grid逐请求结果也一致。
因此保留的是身份正确性修复，不能把A的吞吐收益归因于B。

**C：RTS/CTS，不保留。** 临时命令行设阈值1000B，短/长重试上限都设7，避免阈值变化暗中改变重试预算。
真实WiFi管理器探针确认大帧才触发RTS，广播不触发，最大尝试预算未被不公平削减。
circle/52001总体ISR从原版80.77%降到57.02%，即便成功RTT从476.99降到225.03ms，也不能视作成功。
固定669个交接请求成功数324→414，但非交接4522→3007，总体损失严重；不修改生产无线默认值。

**D：hello回复错峰，不保留。** 在A+B上尝试0.1～5ms确定性分散，仍在真正发送时采集TraCI状态。
真实调度器五例通过、实际hello收发轨迹证实候选延迟0.547～4.289ms；此前夹具的编译/时钟问题单独保留，不充当有效RED。
完整circle/52001结果相对A+B：ISR83.07%→80.52%，RTT467.12→484.12ms；
相同交接子集成功数360→327、RTT470.36→498.87ms，故恢复立即回复，不合入调度帮助函数。
两种失败方案的原始数据与测试记录均保留，未挑选对己方有利的子集作为总体结论。

## 生产安装及最终验收（2026-10-22）

最终生产修改仅在`vndn-obu.cc`、`vndn-rsu.cc`及新增缓存回归测试、wscript注册、统一验收入口和入口测试。
不改底层转发/传输、模型、请求计划、hello频率、无线配置和统计/绘图代码。
实现源码与已完成三场景仿真的A+B+E候选逐字一致。

- 原HEAD为`757701f8ebf16b34a02e72d09314f84f26ff4dd3`；保留开始时已有AI文档差异及归档文件。
- `production-install/final-A-B-E-20261022/plan.json`记录仅3次对象编译、2次库链接，
  没有configure或waf构建，也没有重新链接场景程序。全程`JOBS=4`，编译串行。
- 安装前实际加载暂存库，9个C++套件45用例通过；随后备份并替换两个生产动态库。
  `install.json`状态为`installed`；其余202个保护文件（含旧对象、缓存、程序、头文件等）哈希未变。
  后续用户正常运行waf仍可能进行这些源文件对应的增量构建；没有伪造waf签名。
- 安装后`python3.8 tools/validate.py --skip-build`退出0：9个C++套件45用例、5组Python共283用例，
  无失败/跳过。使用已验证的新库，报告路径为`build/validation/20261021T163616.028884Z-5a3380bc/`。
- 验收工具自身22项测试退出0；安装安全临时文件测试6项通过，独立审查也复核6项通过。
- 安装后的原生产运行器`--no-build`四策略短测全部`complete (validated)`：circle、5车、
  seed63001、5秒预热＋10秒测量＋3.5秒排空、每轮250请求；神经策略使用真实冻结模型及正式契约检查。
  此短测只检验安装后四策略可运行及数据闭合，不作为性能优势或交接改善证据。
  数据在`data/experiments/performance-pilot-20261021/production-smoke/`，4轮分别为
  `20261021T163820.779023Z-532cd147`（0）、`20261021T163832.492491Z-cbc15d71`（1）、
  `20261021T163843.500028Z-10adbc78`（2）、`20261021T163854.469965Z-eb8dd6d6`（3）。

精简持久证据在[归档目录](records/performance-pilot-20261021/README.md)，
安装后报告见[生产验证摘要](records/performance-pilot-20261021/production-validation/SUMMARY.json)。
大日志、原始CSV、二进制和旧库备份仍保留在上述data/build目录，不在精简文档包中。
从头复现旧基线必须恢复对应旧源码/二进制或使用记录的隔离库，不能用新生产库冒充原版。

### 当前代码手动重跑同配置circle对照

以下复用旧批次的只读输入与模型，输出到新的独立目录，每次运行会生成唯一run目录；不会覆盖旧结果。
它执行RTVTDF及神经策略各一轮开发性对照，不启动完整论文流水线。运行前不要并行占用SUMO/Gym端口。

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 tools/experiments/run_experiment.py \
  --config data/experiments/retrain-quick-20261021/inputs/test/circle/baseline/52001/experiment-template.json \
  --output-root data/experiments/performance-pilot-manual-20261022 \
  --block-id manual-circle-abe-s52001 --strategies 2,3 \
  --model-file data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt \
  --require-formal-contract --validation-only --no-build --timeout 900 --python /usr/bin/python3.8
```

本轮未重新训练或正式出图。旧quick图仍对应旧源码，不能将新控制负载估算值填回旧图。
下一步若继续追求RTVTDF非劣性，应基于已确认的MAC拥塞及实际交接失败逐请求定位；
不能把丢弃更多请求造成的较低平均成功RTT当作算法进步，也不能把本轮开发种子当作独立论文检验。

## 2026-10-22 补充：模型目标覆盖与固定交接请求诊断

本轮已跨日，以下核查发生在北京时间 **2026-10-22**；文件及产物目录沿用任务开始日 `20261021`。
这些核查只帮助定位实现与筛选候选，不增加论文主指标、不改冻结模型或历史实验结果。

模型目标覆盖证据见
[逐轮 JSON](../../build/validation/performance-pilot-20261021/neural-target-coverage.json)和
[方法及完整短报告](../../build/validation/performance-pilot-20261021/neural-target-diagnosis.md)。
20 轮涵盖 circle 全部 8 条件、两个种子，以及 grid/spidermap 基准各两个种子；每轮均带原始 run 绝对路径。
关联真实决策、首次 RSU 有线 Data 收到时刻及该时刻车辆服务站，得到：

| 场景/条件（两种子合计） | 生成请求 | 实际回程 | 回程时覆盖服务站 | 已覆盖但仍失败 | 没有 NN 决策 |
|---|---:|---:|---:|---:|---:|
| circle 基准 | 12000 | 11750 | 11737 | 2112 | 250 |
| circle 10 车/12000 请求 | 24000 | 23294 | 23263 | 14946 | 706 |
| circle 20 车/12000 请求 | 24000 | 23132 | 23100 | 19413 | 868 |
| grid 基准 | 12000 | 11206 | 11179 | 417 | 794 |
| spidermap 基准 | 12000 | 7357 | 7348 | 63 | 4643 |

circle 基准只漏选 13 次，却有 2112 次选中了实际服务站仍交付失败，优先处理选站后的交付有依据。
在旧轨迹上把第二站概率阈值从 0.1 改为 0.01，基准将额外增加 363 条回程支路，
仅新覆盖 11 个旧结果失败请求；这只是静态覆盖诊断，不能假定新增副本真的能挽回这 11 个请求。
因此本阶段没有修改模型阈值。

这里采用**实际收到副本的首个 RSU 的返回时刻**，并非训练标签契约中的源站反事实返回时刻。
目标站覆盖不是分类准确率，也不是 ISR；车辆可能在之后等待无线发送时继续移动。
spidermap 大量请求未进入 NN 决策阶段，不能将这些失败算成模型预测错误。

### 固定交接请求子集及复核工具

交接子集严格沿用 `aggregate_campaign.py`：使用原 NoForward 的关联事件；A→B 或 A→失联→B
的跨站恢复发生在请求 `[send_ns,deadline_ns]` 内则入选，边界相等保留并标记 tie。
初次入网、失联后回原站不算交接。候选自身的服务站变化或成功结果不能改变这个子集。

[冻结请求文件](../../build/validation/performance-pilot-20261021/fixed-cohorts/)含三场景、52001/52002 两种子，
circle 为 669/655 个，grid 为 1267/1178 个，spidermap 为 406/288 个。
每份已逐 ID 核对原 `baseline-requests.csv` 完全一致，保留来源、日志哈希和请求/物理轨迹签名。

[只读对照工具](../../build/validation/performance-pilot-20261021/compare_fixed_handover.py)提供 `freeze` 与 `compare`，
检查完整运行、仿真及控制器成功退出、所读日志原始哈希，以及相同请求、SAMPLE 轨迹、种子和测量窗口；
输出到新文件，拒绝覆盖。对全请求及冻结交接子集仍计算原有 ISR、成功请求平均 RTT。
同时保留双方共同成功请求的同 ID RTT 配对差，以及成功/失败转换计数，作为诊断；
不能用只剩少数较快成功请求的均值下降来替代交付改善。

七项行为测试先失败后通过，证据为
[RED](../../build/validation/performance-pilot-20261021/fixed-handover-red.log)与
[GREEN](../../build/validation/performance-pilot-20261021/fixed-handover-green.log)。
真实 CLI 对照也通过：原版 MAC 诊断重跑与原历史 NN 的全请求、固定交接、共同成功配对结果均为零差异。

### 缓存身份修正没有改变这轮正常业务结果

将 `compact-hello-buffer-circle/20261021T160300.736096Z-81f72703/` 与
`compact-hello/20261021T154948.671105Z-5f9a0562/` 按同一输入、同一冻结子集比较：

- `run-metrics.json` 除 `run_id`、`block_id` 外的 **45 个字段逐值完全一致**，包含所有业务计数、RTT、网络/控制负载和额外 Data。
- 7 份 raw 文件逐字节一致，包括 request、packet-l3、data-rx、data-attempts、mobility 和 controller-decisions。
  其余 3 份仅运行身份元数据不同：5907 条 neural-decisions 的差异全部为 `run_id`；
  effective config 仅 `run_id/output_dir` 不同，simulation-result 仅 `run_id` 不同。
- 两轮均为 6000 请求/4984 成功，ISR 83.0667%，平均成功 RTT 467.1162 ms；
  network 1587.129128 Mbit、control 103.700696 Mbit、额外 Data 91 次。
  固定 669 个交接请求中均成功 360 个，成功 RTT 470.3574 ms，逐请求结果及 RTT 完全一致。

该结果支持“修正错误暂存身份，没有扰动此轮正常交付”，不能代替异常回调单元测试或全部场景验收。
完整证据见[不变性核查](../../build/validation/performance-pilot-20261021/buffer-vs-hello-invariance.json)和
[固定子集对照](../../build/validation/performance-pilot-20261021/fixed-comparisons/circle-compact-hello-buffer-vs-hello-NN.json)。

完成轮次的精确指标、耗时和路径集中于
[汇总表](../../build/validation/performance-pilot-20261021/pilot-runs-summary.md)、
[JSON](../../build/validation/performance-pilot-20261021/pilot-runs-summary.json)及
[CSV](../../build/validation/performance-pilot-20261021/pilot-runs-summary.csv)。
独立调度诊断种子 63001 没有套用 52001 的交接子集，表内明确标为“未冻结”；
初次表格渲染因此缺字段而停止，修正为明确展示未冻结后通过，保留在 `pilot-summary-verification.json`。
后续仅在完整运行通知后更新，不将正在执行的临时数据提前用于性能结论。

## 2026-10-22 候选 E：省略无变化的缓存增量

E 以 A 的紧凑 JSON、即时 hello 响应为基础，不叠加已退化的相位调度 D。
已经注册且 `added`、`removed` 同时为空时，省略 `CsAdded`、`CsRemoved` 和 `CsUpdate` 三个字段；
首次 `CsUpdate=false/CsList` 即使为空也完整保留，非空增删完整保留，`m_lastCsNames` 仍更新。
六维模型状态、NextRsu、hello 频率、模型和选站阈值都不变。运行使用含 B 身份修正的隔离库，
共享 OBU 编码调整同样用于 RTVTDF，原有统计定义不变。

### 真实编码与接收端语义测试

测试提取实际 OBU 缓存报告与序列化代码，以及实际 RSU 缓存处理代码；执行序列化、解析和 RSU 双向缓存映射更新。
9 个夹具、16 个 hello 步骤覆盖首次空全量清旧映射、首次非空全量、增删、Unicode/转义名称、
其他车辆共享映射、连续变化/不变状态。只忽略 debug 日志可能建立的空映射容器，所有名称—车辆关系严格比较。

修改前语义测试 16 步通过；新增省略要求只有 6 个空增量步骤失败，其他语义断言仍通过，构成有效 RED。
最小候选后 16 步全部通过，这 6 个步骤各精确减少 **44 字节 JSON 载荷**。
这不是 NDN/MAC 总报文节省的估算替代，真实负载以新运行采集为准。
证据及冻结源码在[候选目录](../../build/validation/performance-pilot-20261021/empty-cache-candidate/)，
源片段哈希见 `baseline/extraction.json`、`candidate/extraction.json`，红绿输出为
`baseline/semantics.json`、`baseline/omit-empty.json`、`candidate/green.json`。

最小 A+E OBU 补丁及 B 的测试/实现/验收入口材料见
[集成说明](../../build/validation/performance-pilot-20261021/retain-abe-integration.md)与
[哈希清单](../../build/validation/performance-pilot-20261021/retain-abe-integration.json)。
组合 `git apply --check` 退出 0；这是可应用性检查，不代表已经提升为生产实现。

### circle 同输入、同配置的完整对照

以下都是 52001 种子、6000 请求；交接子集固定为原 NoForward 的同一组 669 请求。

| 实现/策略 | 全请求成功数 | 全请求 ISR | 全请求成功 RTT | 交接成功数 | 交接 ISR | 交接成功 RTT |
|---|---:|---:|---:|---:|---:|---:|
| 原版 NN | 4846/6000 | 80.7667% | 476.994 ms | 324/669 | 48.4305% | 514.355 ms |
| A+B NN | 4984/6000 | 83.0667% | 467.116 ms | 360/669 | 53.8117% | 470.357 ms |
| A+B+E NN | 5118/6000 | 85.3000% | 435.681 ms | 390/669 | 58.2960% | 438.674 ms |
| 同 A+B+E 配置 RTVTDF | 5314/6000 | 88.5667% | 397.386 ms | 384/669 | 57.3991% | 400.687 ms |

E 对 NN 自身有改善：相比 A+B，成功数增加 134，全请求 RTT 降低 31.435 ms；
固定交接成功数增加 30、RTT 降低 31.683 ms，共同成功交接请求配对 RTT 也降低 38.589 ms。
NN 控制负载从 103.700696 降至 90.562960 Mbit。
RTVTDF 同样受益：相比其 A 配置，成功数增加 91，成功 RTT 降低 15.110 ms，不能只给 NN 使用共享优化。

**当前不能声称已达到“不劣于 RTVTDF”**。同配置下 NN 全请求 ISR 仍低 3.2667 个百分点，
平均成功 RTT 高 38.295 ms。固定交接子集中 NN 多成功 6 个，但成功 RTT 高 37.988 ms，
双方共同成功交接请求的配对 RTT 也高 47.757 ms。这个单种子的小幅交接成功数差异不构成总体优越性或统计显著性。

原始运行分别为 `empty-cache-circle/20261021T162239.593894Z-fa07d48f/` 与
`empty-cache-rtvtdf/20261021T162454.907260Z-b68d35d1/`；
[公平固定子集对照](../../build/validation/performance-pilot-20261021/fixed-comparisons/circle-ABE-NN-vs-RTVTDF-fair.json)
以 RTVTDF 为 baseline、NN 为 candidate，差值方向已在文件内注明。

### 最后四轮隔离确认已完成：范围与结论

E/63011/circle NN、E/63011/circle RTVTDF、E/grid NN、E/spidermap NN 四轮均已完整结束并核验，
输入签名、逐请求终态和所读原始日志哈希通过。最后一轮为
`empty-cache-spidermap/20261021T163310.548725Z-70c450ed/`。
以下是同输入的原 NN 到 A+B+E NN 的变化，不把它当作与其他策略的胜负：

| 场景/种子 | 原 NN ISR → 新 NN ISR | 原 NN 成功 RTT → 新 NN 成功 RTT |
|---|---:|---:|
| circle/52001 | 80.7667% → 85.3000% | 476.994 → 435.681 ms |
| circle/63011 | 79.1667% → 86.3500% | 498.013 → 420.527 ms |
| grid/52001 | 89.5333% → 89.5333% | 317.383 → 316.846 ms |
| spidermap/52001 | 66.8500% → 66.8500% | 301.858 → 301.486 ms |

circle 两个开发性配对种子都显示自身改善；grid/spidermap 的全请求满足率没有变化，RTT 变化很小。
固定交接子集中，grid 原版 877/1267 成功变为 881/1267，RTT 328.320→328.077 ms；
spidermap 原版 312/406 变为 313/406，但 RTT **307.940→308.606 ms，略变慢**。
相对中间 A+B，grid 在加入 E 后交接成功数 892→881、RTT 325.740→328.077 ms，也完整保留这项退化。
不能声称三个场景的交接时延一致改善。

新种子 63011 下，同 A+B+E 配置 RTVTDF 为 **89.0000% / 375.137 ms**，
NN 为 **86.3500% / 420.527 ms**；NN 全请求 ISR 低 2.6500 个百分点、RTT 高 45.390 ms。
双方共同成功请求的同 ID RTT 配对差为 NN 高 48.954 ms。
63011 暂无同种子 NoForward 参考，未套用其他种子交接子集。
结合 52001 的公平对照，**本次不能证明 NN 总体超越或不劣于 RTVTDF**；
grid/spidermap 本轮也没有运行同新配置的 RTVTDF，因此没有这两个场景的新策略胜负结论。
这些是小批量实现验证，不是新的完整论文参数扫描或统计显著性证明。

最后四轮驱动日志 `final-overlay-checks.json` 的 `elapsed_seconds` 是**批次累计时间**，不是每轮时长。
相邻相减得到 123.851、107.125、118.957、106.107 秒，总计 456.040 秒；
各 run manifest 的单轮执行时间另为 122.176、105.518、117.234、104.475 秒，差额包括启动及记录开销。
精确分解见归档 `results/final-overlay-timing.json`。

小型结果归档已准备于
[records/performance-pilot-20261021](records/performance-pilot-20261021/README.md)：
包含 19 轮（含两轮短调度诊断）汇总、22 份配对结果、6 份固定交接请求 ID、20 轮目标覆盖诊断、
原样统计/复算代码和必要测试；不复制大 MAC 日志、对象或实验原数据。
RTS C、相位 D 及所有轻微退化的结果均保留。归档复算不运行仿真、训练或编译。
隔离确认与生产集成验收分别记录；后者已完成，详见本文“生产安装及最终验收”章节。
