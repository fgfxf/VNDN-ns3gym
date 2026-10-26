# 2026-10-21 实验结果归档与重新出图、手动运行说明

记录日期：**2026-10-21，Asia/Shanghai（北京时间）**。本批次名称：`retrain-quick-20261021`。

**本批次已经全部完成：48轮采样、三个场景的模型训练与独立评估、192轮四策略对比，以及最终图集。**
15:00:12开始，22:29:04结束，程序记录总耗时26931.15秒，即**7小时28分51秒**。
最终`plan/pipeline-state.json`为`status=complete, stage=complete`，进程已正常结束，无错误。
用户此前看到的`formal-complete / figures`表示正在出图，不是还在跑仿真；该阶段现已完成。
`ready-for-formal / test`是连续执行入口保留了上阶段状态文字，实际对比进度以`stage=test`及轮数为准。

## 1. 现在直接看哪里

**用浏览器打开[全部图表预览 index.html](../../data/experiments/retrain-quick-20261021/workflow/figures/all/attempt-001/figures/index.html)。**

图表文件夹的完整路径：

```text
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/workflow/figures/all/attempt-001/figures/
```

其中PNG用于快速查看，PDF/SVG用于论文排版和后续编辑。共**25张计划图＋9张诊断图**，每张三种格式，合计102个图文件。
`figure-index.json`记录每图编号、中文/英文图注、来源表、文件名与SHA256；`index.html`提供图片预览。

全部实验资料的主目录：

```text
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/
```

**三个模型另外保存在`/home/fgfxf/ndnSIM/ns-3/data/models/`，具体目录见第5节。备份时不能遗漏。**

## 2. 本次到底跑了什么

| 内容 | 实际完成情况 |
|---|---|
| 场景 | circle圆圈、grid方阵、spidermap蜘蛛网 |
| 策略编号 | 0=NoForward/Naive NDN；1=VTDF；2=RTVTDF；3=NeuralNetwork/TKAN-LSTM |
| 单轮窗口 | 0–20秒预热；20–140秒测量；排空到143.5秒 |
| 采样 | NoForward，共48轮：train 24、validation 12、evaluation 12；每场景8/4/4轮 |
| 采样种子域 | train 23001–23024；validation 33001–33012；evaluation 43001–43012；精确分配见run-index.csv |
| 正式对比 | 3场景×8条件×4策略×2种子=192轮；种子52001、52002；同条件四策略配对 |
| 尝试次数 | 240轮全部首次尝试完整完成，没有失败重跑 |
| 训练 | 每场景一次初始化62021，最多30epoch，patience=5，实际早停结果见第5节 |
| 采样实际耗时之和 | 5348.97秒，约89.15分钟 |
| 正式单轮实际耗时 | 合计20686.67秒；平均107.74秒；范围53.02–206.13秒 |
| 完整任务耗时 | 448.85分钟，含整理数据、训练、评估、校验和出图 |

8个唯一条件如下，三条扫描共享`baseline`，无需重复跑基准：

| 条件目录名 | 车辆数 | 速度设置km/h | 测量窗口内首次业务Interest数 |
|---|---:|---:|---:|
| `baseline` | 10 | 30 | 6000 |
| `n10-v30-k1500` | 10 | 30 | 1500 |
| `n10-v30-k12000` | 10 | 30 | 12000 |
| `n10-v10-k6000` | 10 | 10 | 6000 |
| `n10-v50-k6000` | 10 | 50 | 6000 |
| `n5-v30-k3000` | 5 | 30 | 3000 |
| `n15-v30-k9000` | 15 | 30 | 9000 |
| `n20-v30-k12000` | 20 | 30 | 12000 |

这是一组**每条件n=2的探索初稿**。主图显示实际运行点与样本SD，不把包数当作独立实验次数，也不据此宣称统计显著。
模型训练为离线监督学习，标签是Data首次回到原请求RSU时车辆实际关联的服务RSU，不是强化学习奖励。

## 3. 全部路径索引与目录结构

为避免在长目录中逐个寻找，本次同时生成了四份归档索引：

| 索引 | 内容 |
|---|---|
| [run-index.csv](records/quick-draft-20261021/run-index.csv) | **240行**；按阶段、场景、条件、种子、策略定位每轮实际run目录、raw目录、manifest、输入模板、模型、耗时和主要指标。可用表格软件筛选 |
| [file-index.csv](records/quick-draft-20261021/file-index.csv) | **5649个实际文件**；覆盖整个批次与三个模型目录，逐文件保存绝对路径、项目相对路径、字节数、修改时间和本次重新计算的SHA256 |
| [model-index.json](records/quick-draft-20261021/model-index.json) | 三模型准确路径、SHA256及对应数据集、训练历史、独立评估路径 |
| [archive-check.json](records/quick-draft-20261021/archive-check.json) | 2026-10-21 22:34核查结果；实际文件与历史manifest、输入、模型及来源封存的哈希引用匹配，无缺失或不一致 |

索引只是清单，**不是原始文件的备份**。主批次约4.245GB，模型目录合计约36.7MB，总计4281968749字节。

下列路径均相对主批次`/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/`：

```text
plan/                                      参数、状态、日志、来源快照
  design.json                              冻结条件、种子、三模型路径与SHA256
  training-config.json                     实际训练参数
  training-coverage.json                   三场景全类/跨站样本覆盖审计
  state-train.json                         24轮训练采样的准确run路径
  state-validation.json                    12轮验证采样的准确run路径
  state-evaluation.json                    12轮独立评估采样的准确run路径
  state-test.json                          192轮正式对比的准确run路径
  pipeline-state.json                      完成状态、阶段日志路径、总耗时
  console.log                             整体进度输出
  pipeline-logs/                           各阶段的启动命令输出/进程记录
  launch.json                             实际启动命令和当时PID身份
  source.tar.gz / source-seal.json          本次运行时源码归档及哈希
inputs/{split}/{scene}/{condition}/{seed}/  冻结的SUMO输入和请求计划
sampling/{job_id}/attempt-001/runs/{run_id}/ 48轮采样的原始数据
runs/{job_id}/attempt-001/runs/{run_id}/     192轮正式对比的原始数据
workflow/datasets/{scene}/attempt-001/      整理后的训练数据集
workflow/train/{scene}/attempt-001/         训练命令、日志和实际模型位置
workflow/evaluate/{scene}/attempt-001/      独立评估报告与逐样本预测
workflow/figures/all/attempt-001/
  campaign.json                            48个配对block、192轮及三模型的出图输入清单
  analysis/                                从原始数据汇总出的统计表
  figures/                                 最终图、预览页、图注和配套表
  commands.json                            实际汇总和绘图命令
  aggregate.log / plot.log                  汇总和绘图日志
  attempt.json                             本阶段完成状态、依赖与产物哈希
```

`{split}`取train/validation/evaluation/test，`{scene}`取circle/grid/spidermap。
例如`test-circle-baseline-s52001-a3`表示正式对比、圆圈、基准、种子52001、神经策略。
精确的`run_id`带UTC时间和随机后缀，不要手工猜目录；查`run-index.csv`或对应state文件的`jobs → attempts → manifest_path`。

## 4. 原始数据与汇总表：以后画错图从这里重做

一个真实完整轮的例子（圆圈、基准、52001、无策略）：

```text
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/runs/test-circle-baseline-s52001-a0/attempt-001/runs/20261021T083722.804023Z-6924fa2d/
```

| 单轮内文件 | 用途 |
|---|---|
| `manifest.json` | 成功状态、来源代码身份、模型、现有二进制/依赖身份及输入/产物哈希 |
| `experiment.json` | 本轮生效配置，包含该轮专属输出路径；不要直接拿它再跑并写回旧目录 |
| `run-metrics.json` / `run-metrics.csv` | 单轮满足率、成功RTT、L3负载、额外Data次数和诊断指标 |
| `simulation.log` | 本轮仿真进程输出 |
| `raw/request-events.csv` | 首次请求、成功/超时等请求事件，重算满足率与成功RTT的基础 |
| `raw/data-rx.csv` | Data接收事件，辅助回程与交付追溯 |
| `raw/data-attempts.csv` | 应用显式提交的额外Data，重算“二次转发”口径 |
| `raw/packet-l3.csv` | 网络Face的L3出站报文，重算网络负载、控制负载及协议分项 |
| `raw/mobility-events.csv` | 车辆状态、服务站变化和交接事件 |
| `raw/neural-decisions.jsonl` | C++接受的神经决策及实际选站；非神经策略可能为空 |
| `raw/controller-decisions.jsonl` / `controller.log` | 神经策略Python概率与控制器日志，仅相应轮次存在 |
| `raw/training-observations.jsonl` / `raw/face-roles.json` | 采样轮中的真实hello输入快照及Face角色 |
| `raw/effective-experiment-config.json` / `simulation-config.txt` | 仿真侧配置记录 |
| `raw/recorder-complete.json` / `simulation-result.json` | 采集完成和仿真成功标记 |

同一条件的四策略共享`inputs/test/{scene}/{condition}/{seed}/`，内含
`experiment-template.json`、`input-summary.json`、`bundle-sha256.json`、`network.net.xml`、
`routes.rou.xml`、`simulation.sumocfg`、`request-plan.json`。

已经整理好的统计表位于：

```text
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/workflow/figures/all/attempt-001/analysis/
```

| 文件 | 实际记录数/用途 |
|---|---|
| `run-metrics.csv` | 192行，一轮一行；最直接的全条件结果表 |
| `plot-summary.csv` | 768行；各条件/策略/指标的汇总值、实际两次run_values及SD等字段 |
| `paired-effects.csv` | 576行，配对差值等结果；n=2不能据此强推显著性 |
| `baseline-requests.csv` | 144000行；基准条件的逐请求结果，供RTT分布/时序图 |
| `baseline-associations.csv` | 2000行；基准的车辆关联事件 |
| `run-details.json` | 各轮详细统计与原始来源引用 |
| `aggregate.json` | 统计参数、模型与数据来源、图编号和汇总结果；出图主要入口 |
| `status.json` | 汇总完整完成标志 |

以上CSV记录数均不含表头。基准逐请求表仅覆盖基准，其他条件的逐请求数据仍完整保存在各轮raw目录。

`figures/`另外保存`time-bin-rtt.csv`（288行）、`baseline-rtt-quantiles.csv`（24行）、
`baseline-decomposition.csv`（108行）、`mobility-coverage.csv`（42行）、`model-confusion-counts.csv`（102行）。

指标解释沿用本次采集契约：RTT只对成功请求计算，必须结合满足率阅读；网络/控制负载为网络Face的L3发送字节换算Mbit，
不含LP分片、MAC重传或空口成本；额外Data数为应用提交次数，不冒充实际空口全部副本。
控制负载按代码中的自定义控制分类统计，不能重画时无记录地删掉其中某类报文。

## 5. 三个模型、训练数据与独立评估在哪里

最终推理使用下列**`checkpoint.pt`**，不是任意一个epoch文件：

- 圆圈：[checkpoint.pt](../../data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt)
  完整目录：`/home/fgfxf/ndnSIM/ns-3/data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/`
- 方阵：[checkpoint.pt](../../data/models/grid/tkan-lstm/retrain-quick-20261021-f6a90796ad9a2a7f-session/checkpoint.pt)
  完整目录：`/home/fgfxf/ndnSIM/ns-3/data/models/grid/tkan-lstm/retrain-quick-20261021-f6a90796ad9a2a7f-session/`
- 蜘蛛网：[checkpoint.pt](../../data/models/spidermap/tkan-lstm/retrain-quick-20261021-e71f46c6af3100ad-session/checkpoint.pt)
  完整目录：`/home/fgfxf/ndnSIM/ns-3/data/models/spidermap/tkan-lstm/retrain-quick-20261021-e71f46c6af3100ad-session/`

| 场景 | 实际训练epoch | 选中epoch | 训练样本 | 验证样本 | 独立评估样本 | 独立评估top-1准确率 |
|---|---:|---:|---:|---:|---:|---:|
| circle | 21 | 16 | 52067 | 27733 | 27771 | 99.5931% |
| grid | 9 | 4 | 51501 | 28183 | 28090 | 97.6468% |
| spidermap | 11 | 6 | 28443 | 17311 | 13499 | 98.9629% |

上述准确率是**离线目标站预测准确率**，不等于在线兴趣满足率，也不能证明神经策略各指标都优于转发策略。
选模依据验证集，正式测试使用固定模型；早停后选中最佳epoch，因此不一定是最后一个epoch。

每个模型目录内还包括：

| 文件 | 用途 |
|---|---|
| `model-manifest.json` | 最终模型SHA、数据集、初始化、阈值和训练来源 |
| `training-config.json` / `training-session.json` | 实际参数及稳定训练会话身份 |
| `training-history.csv` / `history-62021.jsonl` | 学习曲线与逐epoch历史 |
| `candidate-62021.pt` / `candidate-62021.complete.json` | 本次唯一初始化的最佳候选与完成标记 |
| `resume-62021.json` / `resume-62021/` | 可恢复完整epoch的当前权重、Adam、RNG、shuffle与早停状态；不是普通推理模型 |

训练数据目录（场景名分别替换）：

```text
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/workflow/datasets/circle/attempt-001/dataset/
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/workflow/datasets/grid/attempt-001/dataset/
/home/fgfxf/ndnSIM/ns-3/data/experiments/retrain-quick-20261021/workflow/datasets/spidermap/attempt-001/dataset/
```

每个目录含`dataset-manifest.json`、`audit.json`以及16组`shard-00000`至`shard-00015`的
`.features.npy`、`.targets.npy`和`.samples.jsonl`。split和原run映射见manifest；无效标签排除及数量见audit。
同级的`../sources.json`保留原始run来源，`../build.log`记录整理过程。

独立评估结果及逐样本预测：

```text
<主批次>/workflow/evaluate/circle/attempt-001/evaluation/{evaluation.json,predictions.jsonl}
<主批次>/workflow/evaluate/grid/attempt-001/evaluation/{evaluation.json,predictions.jsonl}
<主批次>/workflow/evaluate/spidermap/attempt-001/evaluation/{evaluation.json,predictions.jsonl}
```

## 6. 图编号与来源，避免把示意图当成多轮统计

| 编号 | 内容 | 主要来源 |
|---|---|---|
| F01–F05 | Interest数量：满足率、成功平均RTT、网络负载、控制负载、额外Data提交数 | 全部相应条件，两配对种子 |
| F06–F10 | 速度设置：同上五指标 | 全部相应条件，两配对种子 |
| F11–F15 | 车辆数：同上五指标 | 5/10/15/20车，两配对种子 |
| F21–F23 | 圆圈/方阵/蜘蛛网RTT三维图 | 事前指定基准seed52001，按请求发送时间5秒分箱；没有成功请求的箱留空 |
| F24–F26 | 三场景RTT箱线图 | 基准两种子的全部成功RTT；完整尾部＋P95附近放大，未删尾部样本 |
| F27 | 基准总流量对比 | 三场景四策略，两次运行点及SD |
| F28–F30 | 三模型混淆矩阵 | 独立评估数据 |
| D01–D03 | 三场景RTT ECDF诊断 | 基准成功RTT及共同交接集合 |
| D04–D06 | 额外Data、控制流量分解与移动覆盖 | 原始分项及实际移动记录 |
| D07–D09 | 三模型学习曲线 | 各模型训练历史 |

F16–F20对应旧大方案中暂缓的固定全网请求数扫描，本次没有这些图，属于计划内编号空缺。
三维图是指定一轮的示意；箱线图合并包分布只用于描述，不能把144000个请求当作144000次独立重复。

## 7. 只想重新画图：不用再跑实验

### 7.1 只改字体、配色、布局、坐标或图注

保留本次统计数据，用绘图脚本输出到一个新目录。以下命令可直接复制：

```bash
cd /home/fgfxf/ndnSIM/ns-3
QUICK_REPLOT_DIR="data/experiments/replots/quick-20261021-$(date +%Y%m%d-%H%M%S)"
python3.8 tools/experiments/plot_campaign.py \
  data/experiments/retrain-quick-20261021/workflow/figures/all/attempt-001/analysis \
  --output-dir "$QUICK_REPLOT_DIR"
echo "新图位置：$QUICK_REPLOT_DIR/index.html"
```

如需调整样式，修改的是`tools/experiments/plot_campaign.py`，之后运行上面命令；遵循测试先行约定并记录修改。
**修改样式后才会得到不同样式；原样运行只是按当前脚本重绘。** 原图不会被覆盖，输出目录存在时工具会拒绝覆盖。

### 7.2 怀疑汇总计算或统计口径需要修正

从本次`campaign.json`索引的原始数据重新计算，并另存结果：

```bash
cd /home/fgfxf/ndnSIM/ns-3
QUICK_REANALYSIS_DIR="data/experiments/reanalysis/quick-20261021-$(date +%Y%m%d-%H%M%S)"
python3.8 tools/experiments/aggregate_campaign.py \
  data/experiments/retrain-quick-20261021/workflow/figures/all/attempt-001/campaign.json \
  --output-dir "$QUICK_REANALYSIS_DIR/analysis" && \
python3.8 tools/experiments/plot_campaign.py \
  "$QUICK_REANALYSIS_DIR/analysis" \
  --output-dir "$QUICK_REANALYSIS_DIR/figures"
echo "成功出图后查看：$QUICK_REANALYSIS_DIR/figures/index.html"
```

这仍然**不重新仿真、不重新训练**。若改变统计代码或指标定义，应同时保存变更原因、新旧结果与版本，不能静默修改旧结果。
`aggregate_campaign.py`负责汇总，`summarize.py`负责单轮指标逻辑，`plot_campaign.py`负责图形。
重新汇总会重新校验原始证据；缺失或哈希不一致应先查原因，不能删掉核验强行作图。

本批次已经完成，执行旧批次的`workflow figures`或`pipeline all`通常只会核验并复用既有阶段，
**不会强制重画**；需要重新生成图片时使用本节的独立命令。

## 8. 手动重新跑实验：对应“无策略→VTDF→RTVTDF→神经网络”

### 8.1 一次手动运行圆圈四策略各一轮

以下命令使用本次基准输入和已训练模型，顺序跑0/1/2/3四种策略。
脚本会在策略3时自动启动Python推理进程，所以不用再手工开第二个窗口，也不用修改cc策略默认值或py模型默认路径。

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python3.8 tools/experiments/run_experiment.py \
  --config data/experiments/retrain-quick-20261021/inputs/test/circle/baseline/52001/experiment-template.json \
  --output-root data/experiments/manual-quick-circle \
  --block-id manual-circle-baseline-52001 \
  --strategies 0,1,2,3 \
  --model-file data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt \
  --require-formal-contract \
  --no-build \
  --timeout 900 \
  --python /usr/bin/python3.8
```

每轮新结果位于`/home/fgfxf/ndnSIM/ns-3/data/experiments/manual-quick-circle/<UTC时间-随机ID>/`，
含`manifest.json`、`run-metrics.json/csv`、`raw/`及日志，原批次不被修改。
重复执行会创建新run目录；**重复同一个52001种子属于复现，不增加独立种子数**。

只跑某一种时，把`--strategies 0,1,2,3`替换为下列任一项；不要同时保留两个选项：

| 想跑的策略 | 命令选项 |
|---|---|
| 无策略 | `--strategy 0` |
| VTDF | `--strategy 1` |
| RTVTDF | `--strategy 2` |
| 神经网络 | `--strategy 3`，保留`--model-file`及正式模型检查 |

### 8.2 换成方阵、蜘蛛网、另一条件或另一个已冻结种子

换场景需要同时替换`--config`和`--model-file`；为便于辨认，也替换输出目录与block-id中的场景名：

| 场景 | `--config`（相对ns-3） | `--model-file`（相对ns-3） |
|---|---|---|
| circle | `data/experiments/retrain-quick-20261021/inputs/test/circle/baseline/52001/experiment-template.json` | `data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt` |
| grid | `data/experiments/retrain-quick-20261021/inputs/test/grid/baseline/52001/experiment-template.json` | `data/models/grid/tkan-lstm/retrain-quick-20261021-f6a90796ad9a2a7f-session/checkpoint.pt` |
| spidermap | `data/experiments/retrain-quick-20261021/inputs/test/spidermap/baseline/52001/experiment-template.json` | `data/models/spidermap/tkan-lstm/retrain-quick-20261021-e71f46c6af3100ad-session/checkpoint.pt` |

换实验条件：把config中的`baseline`替换为第2节条件目录名；换第二个种子：把`52001`替换为`52002`。
例如蜘蛛网20辆车、12000请求、第二个种子的模板是：

```text
data/experiments/retrain-quick-20261021/inputs/test/spidermap/n20-v30-k12000/52002/experiment-template.json
```

要新增第三个种子或全新参数，需要生成新的独立输入；不能只改block-id假装换种子，也不要修改本次已冻结的inputs。
本节新跑的数据是独立复现实验输出，不会自动加入原192轮的`campaign.json`；需另建可审计的比较清单才能汇总为新图集。

底层仍是`waf --run-no-build ... -j 4`及真实场景控制器。保留`--no-build`，不要先执行`./waf configure`。
直接把原run的`experiment.json`交给waf可能写回旧输出目录；手动复跑优先使用上述模板＋runner入口。
同一项目串行执行，避免多个仿真抢用SUMO/Gym端口。

### 8.3 从零重新跑整套初稿

只有确实需要重新采样和训练时才使用本节；改图片外观使用第7节即可。
下面创建全新批次，原结果保留：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
QUICK_RERUN_ROOT="data/experiments/retrain-quick-rerun-$(date +%Y%m%d-%H%M%S)"
echo "记下这个目录，用于查进度和中断后继续：$QUICK_RERUN_ROOT"
python3.8 tools/experiments/run_campaign_pipeline.py all \
  --root "$QUICK_RERUN_ROOT" \
  --profile quick-draft-v1 \
  --training-config data/experiments/retrain-quick-20261021/plan/training-config.json \
  --run-timeout 900 \
  --stage-timeout 7200 \
  --python /usr/bin/python3.8
```

这会重新执行48采样、三模型、192对比和出图；仍使用同一组预定义种子，是同设计复现。
命令前台运行时保留终端。若中断，记录实际新目录，下次把`--root`写成**同一目录**继续，
不要再次用时间戳创建另一批，也不要将root写回原来的已完成目录。
源码/输入/训练配置保持一致时，程序核验后复用已完成轮次和训练保存点。

原批次查询命令如下；查看新批次时将root替换为其实际目录：

```bash
cd /home/fgfxf/ndnSIM/ns-3
python3.8 tools/experiments/run_campaign_pipeline.py status \
  --root data/experiments/retrain-quick-20261021 --watch
```

Ctrl+C只退出这个进度查看命令。对正在运行的新批次立即停止时使用
`python3.8 tools/experiments/run_campaign_pipeline.py stop --root <实际新目录>`；
停止保留已完成数据，当前未完成仿真下次重跑；既有每job两次attempt上限仍适用。

## 9. 今后保留与核查

完整保留以下四个目录：主批次目录，以及第5节三个模型目录；再保留本文和`records/quick-draft-20261021/`索引。
不能只保存PNG、`analysis/`或单独`.pt`：重画时工具会读取并校验原始manifest、输入、评估报告和训练历史。
路径引用中有绝对路径，迁移机器时需有记录地处理路径，不能直接改旧哈希或旧manifest绕过验证。

2026-10-21随后按用户要求建立[可迁移出图交接包](../../data/experiments/retrain-quick-2026102-others/README.md)：
包含本次三个绘图/统计模块的原样副本、测试、三个完整模型会话及详细AI文档。
与完整主数据归档一起保存；使用包内`code/replot.py check|plot|rebuild`在读取时映射历史绝对路径，
无需重写原JSON或重跑仿真。精确目录名为用户指定的`retrain-quick-2026102-others`。

本次冻结代码SHA256为：

```text
142365d8cc9af24f8028f6cc5bf11dd30af9baa0ac7c9ecb538ac3e9487c90a4
```

`plan/source.tar.gz`保存当时源码，`plan/source-seal.json`保存归档SHA256；各run的manifest还记录当时二进制和依赖身份。
源码包不等于完整二进制/系统环境备份；新机器重跑需要对应ns-3、SUMO、Python及依赖。

本次记录工作只读取实验结果并新建文档/索引：重新计算5649个文件SHA256，核对240个run manifest、3312个run产物引用、
1440个输入引用、48个神经运行模型引用、395个workflow产物引用、255个阶段依赖、源码归档及三模型，全部匹配。
另核查102个图文件与图索引一致。没有重新启动仿真、训练、configure或编译，也没有覆盖原图、原始数据或模型。
文中手动命令经现有CLI和参数/路径核查；本次没有为了文档再跑一遍七小时实验。
