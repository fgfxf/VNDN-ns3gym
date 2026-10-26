# 固定旧模型的 quick 扩展实验（2026-10-22）

## 授权、目标和当前状态

用户完成grill问答后明确“确认并执行”。本次授权实现并启动264轮对比与出图，
复用2026-10-21 quick的三个模型，跳过新采样、训练和离线评估；不输出训练图。
444分钟是目标，不是强制停止时间。历史耗时推算约471分钟（7小时51分），
实际受新种子、60km/h条件及机器负载影响，不承诺准确完成时刻。

当前状态：实现、测试和真实模型预检已通过；**2026-10-22北京时间16:19:56已后台启动真实实验**。
启动PID为8901，身份token/精确命令在新批次`plan/launch.json`，运行日志为`plan/console.log`。
初始化后已进入`running / test`，模型3/3复用、采样训练跳过，第一轮为circle/策略0/23001/基准。
这表示批次已启动，不表示264轮或真实论文图已完成；随时以`status`及实际manifest为准。

北京时间16:28:25状态快照：5/264轮完成，剩余259轮，正在执行第6轮grid/策略1/23009/基准，
累计约8.5分钟。首个circle基准四策略已全部完成并通过只读核验：每轮6000个请求均有终态记录
（终态包括成功或失败，不表示全部成功交付），四策略共享输入一致、没有开启训练采样。
NN实际加载上述旧circle模型，5935条Python/C++动作的车辆、概率和目标逐条一致且均被接受；
四轮墙钟分别约96.8、97.5、96.9、110.0秒。这仅验证入口与数据完整性，不作性能优越性结论。
证据为`build/validation/quick-fixed-model-20261022/first-block-audit.json`，小型副本亦已归档。

旧目录`data/experiments/retrain-quick-20261021`与模型保持只读，
新目录`data/experiments/quick-fixed-model-20261022`，profile为`quick-fixed-model-v1`。
此前停止的各批次不恢复。本次正式授权覆盖本批次264轮，不延伸到旧完整论文批次。

## 冻结矩阵与种子

| 扫描 | 取值 | 固定条件 |
|---|---|---|
| 首次业务Interest总数 | 1500、3000、6000、9000、12000 | 10车、30km/h |
| 速度设置 | 15、30、50、60km/h | 10车、6000请求 |
| 车辆数 | 5、10、15、20 | 30km/h、每车5Hz，对应3000/6000/9000/12000请求 |

基准10车/30km/h/6000请求为三扫描共用，5+4+4-2=11个唯一条件。
11条件×3场景×4策略×2种子=264轮，每场景88轮；无新增采样、训练。
单轮20秒预热、120秒测量、3.5秒排空。各比较策略共享同条件/种子的外生输入。

| 场景 | 固定训练采样种子 | RTT三维示例种子 |
|---|---|---|
| circle | 23001、23002 | 23001 |
| grid | 23009、23010 | 23009 |
| spidermap | 23017、23018 | 23017 |

用户确实选择训练采样种子，而非昨日在线对比的52001/52002。
这是**复用训练种子的探索性在线比较**，不能声称独立泛化测试。
模型初始化种子62021是另一概念。不同参数但相同种子不保证产生相同轨迹/请求。
60km/h超过旧训练参数上限50，模型固定，不根据结果再训练或调阈值。
保留所有结果及两个重复的差异，不按结果删除不利点或提前停止。

## 模型、代码与统计边界

三模型相对项目根路径：

```text
data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt
data/models/grid/tkan-lstm/retrain-quick-20261021-f6a90796ad9a2a7f-session/checkpoint.pt
data/models/spidermap/tkan-lstm/retrain-quick-20261021-e71f46c6af3100ad-session/checkpoint.pt
```

SHA256依次为：

```text
644c383c683562be6465f816f723a5b8ba178d270055e17ccedb222620d3c5ba
c71f23c2b9cc0c77411ff26fc9e447539db750596d7557a86bece651cbfde2c4
52a04c6038b0f6290d1003f1432a6d6aeb752df1ff4d88d7a7b4c9d600ff4f47
```

保留两个阈值0.10，观测10×6与标签契约不变。
新模式分别记录历史模型训练源码及当前运行源码，核对原模型manifest、dataset来源和checkpoint；
不伪改历史契约，也不解除旧profile的同源、训练/评估隔离校验。

使用当前已安装的三场景程序与最新NN专用VNH1/CBOR编码；非NN仍原JSON。
本次仅改Python编排/来源核验/汇总和图集选择以及测试，不改C++、模型权重或统计公式。
所有运行`JOBS=4`、现有二进制`--no-build`，不configure、不重新编译。
额外优化的解释继续仅写入Markdown文档，不在比较HTML/图里添加机制说明。

成功率、成功请求平均RTT、L3网络/控制累计发送字节、应用显式额外Data提交计数沿原口径。
后两者仍不等于完整MAC开销或所有隐式副本。新结果不混进旧批次，也不覆盖旧图。

## 输出、恢复和图集

新目录保存`plan/`、`inputs/`、`runs/`、`workflow/`及源码封存；三模型仍保留原路径，
新批次绑定准确来源和SHA。仿真原始CSV/JSONL、每轮manifest/日志和汇总表一并保留。
模型来源和代码冻结后才开长跑，运行期间不得修改封存源码/脚本。

首组基准三场景四策略12轮计入264轮，作为真实入口检查，不另外浪费重复轮次。
进度包含模型复用3/3、采样训练已跳过、当前条件/策略/种子/轮次、完成/剩余、
当前轮时间和本次/累计时间，不输出剩余时间估算。
只保留立即停止；同一命令恢复时核验并跳过已完成轮，保留中断attempt并重跑不完整轮。
保留现有最多两次attempt的失败保护，不无限重试或把失败算完成。

图集：15主图、3 RTT三维图、3箱线图、1总流量图，共22编号图；另6非训练诊断图，合计28。
取消3混淆矩阵和3学习曲线。图形仍使用两个重复的点及标准差，不当作独立显著性结论。
缺轮禁止形成宣称完整的最终图集；所有数据齐全并校验后生成HTML预览和配套索引。

## 测试先行与实施证据

起始Git工作区干净。修改前实验工具全基线：

```bash
export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 -m unittest discover -s tools/experiments/tests -p 'test_*.py' -v
```

退出0，228测试通过，耗时65.864秒。证据根为`build/validation/quick-fixed-model-20261022/`，
入口日志`baseline.log`。pipeline新7项行为测试在旧实现因不支持profile/CLI而有效失败，
新分支后7项通过，分别为`pipeline-red.log`、`pipeline-green.log`。
后续完整回归、图集集成、绑定及启动实际结果追加在本文件。

新增campaign 10项、pipeline 7项、workflow 9项、aggregate/plot 7项。
campaign补测显式浮点duration仍须生成整数请求量，真实RED后修正；
图集补测代表seed被改后不得静默出空图，真实RED后拒绝。
完整264个合成运行的原始CSV实际经过汇总和绘图，生成28张图的84个PDF/SVG/PNG文件；
这是工具集成验证，不是真实仿真性能数据。缺轮、错误场景seed、模型篡改均拒绝。
真实三模型经当前控制器加载通过，13项历史模型/元数据依赖核验通过，
receipt为`real-model-preflight.json`；真实计划与workflow/aggregate接口核对为
`workflow-real-plan-preflight.json`，不把预检中的占位run引用当成已跑数据。

最终统一入口`python3.8 tools/validate.py --skip-build`退出0：9个C++套件45例、Python324例全部通过，
无失败/跳过。报告为`build/validation/20261022T081555.483901Z-cb6a7d7a/report.json`，
本次目录另存`final-regression.log`及`final-regression-summary.json`。
`runtime-before-launch.json`核对三个程序、正式模块库与waf配置缓存SHA均未改变，C++源差异为空。
修改前HEAD为`c64023a4af55b0f47fa01898a1a86352aae28889`。

启动时三个模型SHA与上文一致；当前源代码快照与旧模型训练快照分别封存在
新`plan/design.json`的`source_sha256`和`external_models.training_source_sha256`，
来源依赖共13项。运行源码归档为`plan/source.tar.gz`和`plan/source-seal.json`。
恢复不得伪改旧模型训练契约或本次源快照。新helper仅读取模型及必要元数据，不反复扫描旧全部训练原始数组。

测试日志、实现源码和最终回归的小型本机副本在`docs/ai/records/quick-fixed-model-20261022/`，
逐文件索引`archive-index.json`。沿用Git忽略规则，没有自动提交，也不是异机备份。
文档89个相对链接及本文件6个Bash示例语法检查通过；`git diff --check`通过。
已完成真实轮次会保留在新批次的`runs/`，未完成时不生成伪完整结果或用合成测试图替代。

## 操作命令

以下命令均在`/home/fgfxf/ndnSIM/ns-3`执行。当前批次正在运行时，只查看进度，
不要再启动第二个实例。启动/中断后的继续使用同一命令，模型与代码需与封存状态一致：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 tools/experiments/run_campaign_pipeline.py all \
  --root data/experiments/quick-fixed-model-20261022 \
  --profile quick-fixed-model-v1 \
  --model-source data/experiments/retrain-quick-20261021 \
  --run-timeout 900 --stage-timeout 7200 --python /usr/bin/python3.8
```

每个仿真运行超时900秒，异常attempt保留，不无限重试。正常约8小时的整批运行不会因
`--stage-timeout 7200`被中断：该值用于workflow的汇总/绘图子命令，不是整批仿真的总时限。

查看持续更新的进度；这个查看窗口按Ctrl+C只关闭查看：

```bash
cd /home/fgfxf/ndnSIM/ns-3
python3.8 tools/experiments/run_campaign_pipeline.py status \
  --root data/experiments/quick-fixed-model-20261022 --watch
```

立即停止本批次，保留已完成数据：

```bash
python3.8 tools/experiments/run_campaign_pipeline.py stop \
  --root data/experiments/quick-fixed-model-20261022
```

电脑重启后不会自行开跑，重新执行上方`all`命令即可核验并继续。
同一轮已累计两次失败/中断时会停止并报错，已完成轮不受影响；需查看保留的失败原因，
不要删除manifest或改状态来绕过校验。

正常完成后浏览器打开：

```text
data/experiments/quick-fixed-model-20261022/workflow/figures/all/attempt-001/figures/index.html
```

若出图出现失败后重试，以`workflow/figures/all/`内完成attempt为准，前一失败目录保留。
只续跑未完成的出图阶段，不重新仿真：

```bash
export JOBS=4
python3.8 tools/experiments/run_campaign_pipeline.py figures \
  --root data/experiments/quick-fixed-model-20261022 \
  --run-timeout 900 --stage-timeout 7200 --python /usr/bin/python3.8
```

如需用同一汇总数据另画一套图，选择未使用的新输出目录；无需重新仿真：

```bash
python3.8 tools/experiments/plot_campaign.py \
  data/experiments/quick-fixed-model-20261022/workflow/figures/all/attempt-001/analysis \
  --output-dir data/experiments/quick-fixed-model-20261022/replot-001
```

源码、模型或原始产物变化会影响恢复校验，运行时保持冻结。
若之后要改图形代码，先等当前批次完成；直接绘图入口读取并校验保存的analysis和数据，
不会改写旧campaign/manifest来伪装同一版本。
