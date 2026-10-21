# 三场景重新训练与论文图执行记录

用户于2026-10-21（Asia/Shanghai）回复“确认并执行”，授权
[完整计划](RETRAIN_AND_FIGURES_PLAN_20261021.md)的P0–P6。
研究设计及20种子约束保持不变，阶段完成状态与最终科研效果分别记录。

## 当前状态

P0统一单元基线已通过；P1新增实现的统一14步骤已通过。
三场景NoForward采样开关六轮验收全部通过，其余策略的配对及临时模型闭环待执行。
P2已冻结预实验源码，正在串行运行独立种子10001的三个300秒基准轮。
已启动独立后台等待队列，当前等待该批次结束；本次队列目标为`pilot-report`，
尚未越过开发参数冻结或正式模型冻结。
尚未启动正式训练采样、正式模型训练或4080轮测试。
输出根目录：`data/experiments/retrain-20261021/`。当前有两个旧模型，只保存哈希，不覆盖。
用户已有计划与CHANGELOG受保护；执行期间用户提交为`3a785ec`，不撤销、不替用户提交。

## P0证据

- 起点HEAD：`f6347bb`。源码与两旧模型哈希：
  `data/experiments/retrain-20261021/plan/baseline-source.json`；
  起始差异：同目录`baseline.patch`。
- 命令：`export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`，
  `python3.8 tools/validate.py`，退出0。
- 报告：`build/validation/20261020T163654.266822Z-17bec152/report.json`；
  一次构建、七个C++套件、五组Python测试共13步骤全部通过，没有跳过。
  产物目录使用UTC时间，文档日期使用用户时区。

## P1开发证据（持续追加）

所有构建由根代理串行执行，使用`-j4`，未运行`waf configure`。

| 变更 | 修改前证据 | 当前结果 |
|---|---|---|
| 七站场景路线覆盖、路线族均衡与独立请求随机流 | `build/validation/retrain-20261021-tools/routes-red.log`：原路线缺道路，3个断言失败 | `routes-green.log`：8项通过；道路覆盖不代表真实RSU类别已覆盖 |
| runner封存训练输出、保留预实验身份、传递正式模型契约 | 同目录`runner-red.log`：4项目标行为失败 | 后续安全/动作封存回归见下文 |
| 17条件/4080正式轮数、918候选采样、42候选pilot设计 | 同目录`campaign-red.log`：7个目标断言失败 | 后续执行/恢复/中断共15项通过 |
| C++采样开关及记录 | `build/validation/retrain-20261021-cpp/config-red.xml`：非法类型未拒绝5项、开启状态未保存1项 | 4个相关C++套件共11例通过，真实三场景验收待执行 |
| 统一验证增加快照套件与共享正式训练测试 | `build/validation/retrain-20261021-tools/validate-red.log`：2项断言失败 | 验证工具自身22项通过；整体验证另记 |
| 数据集、模型训练/推理、统计/绘图 | 各代理红绿证据位于`build/validation/retrain-20261021-training/`和`retrain-20261021-figures/` | 相关单元/合成小训练通过，真实集成验收尚未完成 |

首次C++增量构建因新增FaceTable迭代缺完整类型头失败，记录在
`build/validation/retrain-20261021-cpp/implementation-build.log`。
该编译错误不算有效行为红灯；已补头文件后重编。

P1后续进展：

- 第2次编译暴露测试夹具非void函数使用ASSERT宏的类型错误，改为等价EXPECT与安全保护；
  不降低检查标准。第3、4次增量构建均退出0。
- `vndn-experiment-{config,recorder}`、`vndn-l3-experiment-tracer`、
  `vndn-training-snapshot`四套件最终分别1、4、2、4例全部PASS，XML为
  `build/validation/retrain-20261021-cpp/*-green.xml`。
  快照夹具包含真实RSU、无线/P2P Face、hello接收、空/短/完整10步历史及开关不改变L3字节。
- 为记录C++实际采用的动作，先验证Recorder缺日志/缺计数的2处有效红灯，再新增
  `neural-decisions.jsonl`及完成计数；记录有效动作与既有无效action回退，不改选择阈值。
- 运行器进一步核对训练/动作行数、封存空日志；17项通过。
  另经17项基线→5个目标失败断言→20项全部通过，补齐SIGTERM清理与ldd实际库封存。
  `runner-safety-{baseline,red,green}.log`及实际149个库的只读解析证据均在tools证据目录。
  ldd解析证据不等于`/proc`运行时动态映射。
- 验证入口扩展为14步骤；旧测试中“只选一个推理测试文件”的限定已更新为
  共享`test_*.py`发现，增加正式训练失败必须阻止通过的断言。
  `validate-green-2.log`记录22项工具行为测试通过。
- 统计/出图新增25测试全部通过（`retrain-20261021-figures/final-green.log`）。
  `smoke-final/figures/figure-index.json`保存30张编号图加9张诊断图的实际渲染，
  来源是24个合成run，均为VALIDATION ONLY，不是正式实验成果。
- 正式数据集22项、共享训练与推理24项通过；三个旧训练入口分别2/16/16项通过，
  证据为`retrain-20261021-training/{dataset-final-v2,formal-inference-final-v2,
  circle-legacy-final,grid-legacy-final,spidermap-legacy-final}.log`。
  包含三场景合成小数据实际优化、保存、重载及独立评估；
  重复/晚到Data诊断不能增加请求终态、跨split复制run不能成为独立样本、
  缺类/非有限权重拒绝、空评估种子不丢弃，均有行为测试。
- 调度器已有17条件/独立种子域、完整轮数、设计身份冻结、模型契约及源码验证、
  失败attempt保留与恢复校验。中断测试已完成：
  `campaign-cancel-baseline.log`原13项通过，`campaign-cancel-red.log`
  实际子进程复现SIGTERM/SIGINT退出而未封存的问题，`campaign-cancel-green.log`
  最终15项通过，runner回归20项通过。
  取消时先通知runner、等待30秒清理；异常时按`/proc`启动身份限制清理范围，
  保留失败attempt和资源日志，无关进程保持存活。
  GNU time的`%x`在信号终止时可能为0，因此完成判定以实际进程退出码和manifest为准。
- 真实模型runner增加`--decision-log`连接：20项基线通过，4个有效目标断言失败，
  实现后23项通过、campaign回归15项通过（`runner-decisions-*.log`）。
  `controller-decisions.jsonl`必须存在，含空日志在内封存哈希，
  行数与C++动作计数一致；均匀测试控制器不冒充真实推理日志。
- 新`campaign_workflow.py`按datasets/train/evaluate/figures阶段串接已有工具。
  33项测试通过（`retrain-20261021-workflow/final-green.log`），包括三场景
  合成数据实际构建、三个初始化各1epoch、独立评估，以及信号/半写attempt恢复。
  对源码、输入、模型、阶段记录和产物检查哈希；不会自动决定配额或冻结模型。
- 新统一回归实际执行`export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
  OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1`后运行`python3.8 tools/validate.py`，
  退出0，14步骤全部通过。报告：
  `build/validation/20261020T172150.744626Z-2483a09e/report.json`。
  八个C++套件通过，Python各组为2/16/16/24/149项，无失败或跳过。
  未执行`waf configure`；这仍不等于真实三场景网络验收或正式模型完成。

为实际渲染图片，在现有Python3.8用户环境安装`matplotlib==3.7.5`及兼容依赖，
保留`numpy==1.24.4`；pip退出0。版本记录于
`tools/experiments/requirements-experiments.txt`，不是正式出图完成的证据。

## 真实路线预检

预检使用与生产TraCI相同的1ms SUMO步长，40辆车、速度10/50km/h，
预热20s、测量300s、排空3.5s；未运行ns-3或Gym。
证据保存在`data/experiments/retrain-20261021/pilot-route-check/`，
原始输入、命令、哈希、tripinfo和压缩summary均保留。

- 圆圈10km/h：40辆全部在预热结束前入场，最晚5.819s，之后全程在场；
  SUMO墙钟11.24s，无碰撞/teleport警告。
- 圆圈50km/h：SUMO退出0、墙钟12.20s，但只有39辆入场，另1辆一直等待。
  此条件判为失败，未将退出0当作实验有效。
- 原圆圈路径是同一个16边环重复6次。按96个索引分配起点使短边`e4`
  聚集7辆车；后续以有效失败证据和新测试验证最短循环归约修正。
  方阵和蜘蛛网首轮尚未执行，不能宣称六组预检通过。

上述SUMO耗时不包括ns-3网络事件和模型推理，不能用于外推4080轮完整实验总耗时。

后续定位与修正：

- 圆圈最短循环修正：生成器8项基线通过，2个新目标测试先失败，
  实现后10项通过，跨速度请求/路线前缀契约扩大到全部三场景。
  `pilot-route-check-v2`圆圈10/50km/h均40车0s入场、全窗留场，无告警；
  每条实际起始边2或3辆车。原网络与请求计划哈希不变。
- v2方阵10km/h额外启用`collision.check-junctions=true`后在31.228s出现
  掉头内道几何重叠。短对照中，生产默认设置没有告警或移除/传送；
  严格检查的两辆车逐毫秒轨迹与默认设置相同。此结果不能把几何重叠写成不存在。
- 不改变原路网，改为在方阵/蜘蛛网的覆盖路线选取中排除`dir=t`掉头转向，
  两场景仍能覆盖全部20/48条道路。方阵原型全323.5s严格检查零碰撞/传送，
  40辆全部入场留场。生成器新测试先有效失败、实现后11项通过，
  证据`retrain-20261021-training/route-uturn-{red,green}.log`。
  路线策略版本为圆圈`source-cycle-v2`、方阵/蜘蛛网`road-coverage-v2`。
- 最终六组正在`pilot-route-check-v3`重测，保留生产默认碰撞动作`teleport`，
  并额外开启严格路口检查；任一碰撞/传送或车辆缺失都不能通过。
  旧失败输入和诊断证据不覆盖，最终结果另行追加。

v3严格检查的实际结果并未全部通过：圆圈两端和方阵两端入场/留场及碰撞检查通过，
方阵另有6/13条紧急刹车告警；蜘蛛网10km/h在149.857s的左转几何重叠触发了
严格检查下的teleport，保留FAIL。不能进一步按已见种子逐个排除转向来得到绿灯。
该路口检查不是原生产启用项；生成器保持冻结，不修改原交通模型或拓扑。

蜘蛛网生产默认对照中，10/50km/h均40辆在预热前入场并全窗留场，
未发生collision/teleport，紧急刹车分别1/5条。严格warn与默认设置下两车前155秒
逐毫秒轨迹相同，说明附加检查揭示几何重叠，但生产未对此事件移除/传送车辆。
证据为`pilot-route-check-v3/production-spider-check/comparison-report.json`。
后续在独立`production-route-check/`按生产实际默认碰撞设置复验六组，
检查入场/留场、实际传送和记录闭合；严格几何FAIL作为交通模型边界保留，
不合并成“所有严格检查通过”，也不将紧急刹车等同于车辆丢失。

生产默认六组最终全部通过，脚本退出0。每轮40辆均在0秒入场，
323500个1ms步中测量/排空窗至少40辆，结束时仍有40辆未到终点；
collision/teleport/error均为0。墙钟分别为圆圈11.044/10.943s、
方阵13.350/12.954s、蜘蛛网9.791/8.789s；紧急刹车分别0/0、6/13、1/5。
详细命令、哈希与交通模型边界见
`data/experiments/retrain-20261021/production-route-check/FINDINGS.md`及
`precheck-report.json`。它们是单独SUMO预检，不替代ns-3端采样、网络或Gym验收。

## 三场景真实网络验收

NoForward采样开/关配对已完成，使用独立种子9001、每场景10车、
30km/h、预热20s、测量45s、排空3.5s、450个首次业务请求。共六轮串行，
入口为`build/validation/retrain-20261021-cpp/collector_on_off_acceptance.py`，
输出在同目录`collector-pairs/p1-prepared/`，`acceptance-report.json`为全部通过。
该验收比较原始请求、移动、L3、额外提交和接收记录及派生指标，
并检查真实快照和Router回程Face元数据。NoForward通过不自动代表其余三策略通过。
对应脚本的行为测试先有效失败，再5项通过；Neural双日志验收另3项通过。

已完成的圆圈配对：off/on两轮均450请求闭合，DATA171、TIMEOUT279；
六份原始CSV/JSONL的SHA逐项一致，去除`run_id`后全部指标一致。
实际runner耗时分别210.69/198.72s，第一轮包含约11.77s增量链接。
on轮450快照均可生成有效Router回程标签，支持数为`[216,234]`、排除0，
完整10步历史449条、1步历史1条。
请求寿命内有交接的48条，与回程目标不等于源RSU的2条是不同集合，不能混称预测交接样本。
真实标签证据位于`build/validation/retrain-20261021-training/real-snapshot-audit/circle/`。
其中171条DATA的源站均等于回程标签；279条TIMEOUT中277条也为同站、仅2条为跨站目标。
本短轮的高超时率不能主要解释为预测了错误的未来站，也不能把离线准确率直接当交付率。
保留该交叉表，不因此修改已确认标签、协议或按结果筛掉失败请求。
方阵off/on均450请求闭合、DATA300/TIMEOUT150；蜘蛛网均DATA227/TIMEOUT223。
每场景六份原始协议日志逐字节一致，同进程重算的全部指标相等。
方阵/蜘蛛网单独进程缓存的平均速度分别有约2.3e-14/8.9e-15 m/s的浮点求和尾差，
不声称缓存JSON也逐字节相同。六轮外层墙钟合计819.340s；详细资源见
`build/validation/retrain-20261021-cpp/P1_NOFORWARD_COLLECTOR_ACCEPTANCE_20261021.md`。
这些是独立工程验证，不用于正式性能曲线或选模。

实际标签及请求覆盖审计位于
`build/validation/retrain-20261021-training/real-snapshot-audit/`：

| 场景 | 首次请求 | 唯一观测请求及有效标签 | 未观测请求 | 各类别有效标签支持数 |
|---|---:|---:|---:|---|
| 圆圈 | 450 | 450 | 0 | 216,234 |
| 方阵 | 450 | 410 | 40 | 69,56,11,74,81,84,35 |
| 蜘蛛网 | 450 | 243 | 207 | 39,46,39,38,13,3,65 |

全部eligible样本均得到有效标签，标签排除计数为0；无身份歧义或重复增权。
未观测请求均为TIMEOUT，保留在协议指标分母；单凭没有快照不能定位丢包层次。
蜘蛛网类5只有3条，只表示观察到了该类，不表示训练样本充足。
三场景源站与回程目标不同的有效样本分别2/3/1条，
请求寿命内发生过交接的分别48/68/24条，两个定义分别报告。
P1种子9001不进入训练数据集。

二进制证据的准确范围：runner在成功结束后保存二进制、构建cache及ldd解析库哈希；
配对harness比较两轮该证据一致。它不是每轮前后全部实际动态库映射的证明。
只读实测发现运行期另加载`libnss_files`，不在ldd的149项依赖中；
研究模块ndnSIM/vndn/opengym/traci均在解析及实际映射中。

## P2独立预实验（进行中）

生产源码冻结为
`ba577ef0090a7715387dca6dec8fd763930fa090746426116de6a96556d378b6`。
1566个源码/配置文件封存于
`data/experiments/retrain-20261021/plan/pilot-source-ba577ef0090a7715.tar.gz`，
归档SHA256为`7240b24cd08003c99521023d87475c767a7b9e801d602940ed04674dc9083f25`。
同目录`pilot-source-archive.json`保存清单；`environment-baseline.json`保存选定运行环境版本，
它不是所有运行时动态映射的完整封存。

`design.json`当前为`pilot-frozen`，不是开发配额或模型已冻结。
先执行：

```bash
export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 tools/experiments/campaign.py run \
  --root data/experiments/retrain-20261021 \
  --split pilot --condition baseline --seed 10001
```

三场景依次运行，N10、设置速度30km/h、K15000、预热20s、测量300s、排空3.5s，
开启训练快照、标记`validation_only`。初始每轮7200秒仅为诊断上限，
不冒充经过实测冻结的正式timeout。运行未完成时的进度和文件大小不作为完整耗时结果。
仅有NoForward预实验成本时，不能将其乘4080声称已估出四策略总耗时；
神经控制器成本在真实模型工程预检后单列更新。

长任务阶段驱动及额外验收只放在独立验证/计划产物目录，另外封存哈希，
避免运行期间修改生产源码而混合不同版本。任何失败保留attempt并停止依赖阶段。

已完成的额外执行工具测试（尚未通过这些插件启动真实批次）：

- `build/validation/retrain-20261021-cpp/collector_gate.py`封装其余两转发策略12轮
  和真实临时Neural模型6轮的采样开关验收；`engineering_preflight.py`封装
  P4三个负载条件×三场景×四策略36轮。20项轻量测试全部通过，
  包含真实轻量进程的SIGTERM及独立session清理，未运行SUMO或Gym。
  命令、有效红灯、绿灯与哈希见同目录`ARTIFACT_HELPERS_20261021.md`、
  `artifact-helpers-freeze.json`。P4只按实测三条件估算对应720个正式轮次，
  其他14条件3360轮保持未测，不把子集总和写成全4080轮实测成本。
- `build/validation/retrain-20261021-training/pilot_plugins.py`提供独立seed10003
  三场景基准采样，以及10001/10002/10003完整运行划分的临时训练。
  固定三初始化61021/61022/61023、1epoch、hidden32、CPU单线程；
  缺类时保留审计并停止，不按准确率补换数据。新增资源记录后15项轻量测试通过，
  包含非零退出、超时、SIGTERM清理及GNU time退出字段不能代替真实退出判定。
  新版封存为同目录`pilot-plugins-freeze-v2.json`，没有实际优化训练。
  每场景分别保存数据构建/训练墙钟与峰值RSS，附有效样本及源run数。
  训练耗时包含三初始化、验证、checkpoint I/O和启动，不声称是纯优化吞吐；
  baseline单run/split的成本不能无条件外推到每场景170个正式train run，
  特别是随机mmap读取、八run缓存及较大工作集的成本差异。

### 持久队列已启动

2026-10-21（Asia/Shanghai）实际启动，bootstrap退出0，启动后状态为`waiting`。
后台进程PID为15438、`/proc` starttime为18787450；等待已有基准调度进程
PID7969/starttime18623144。该进程身份仅描述本次启动，后续查询应核对状态文件，
不能仅凭同一个数字PID认定还是原任务。

先独立测试驱动16项、等待器2项、资源报告4项，全部通过。
交叉复核补齐了大日志流式哈希、嵌套模型/数据哈希、阶段末身份检查、
已退出父进程的遗留子会话检查，以及实测后确定训练/P4超时的入口。
有效红灯与绿灯位于`build/validation/retrain-20261021-workflow/`；
详细接口为同目录`LONG_DRIVER_INTERFACE.md`。

执行配置原样封存为`data/experiments/retrain-20261021/plan/long-driver.json`，
SHA256为`c58bd14afdc677b153b81a38c4899ad61e00bd3e0dfa3955b06908463289bd91`。
31个执行文件、测试和证据的归档为
`plan/execution-tools-c58bd14afdc677b1.tar.gz`，
SHA256为`d6374d9054c3de74df69a0dd59b64c12173acb1828fad4b64645730e6d0d1c23`；
完整清单为`plan/execution-tools-archive.json`。脚本仍从已封存的build绝对路径执行，
归档副本用于保留证据，不能直接移位后运行依赖目录层级定位的辅助脚本。

后台队列的实际命令、PID/启动身份和环境见`plan/queued-driver-launch.json`，
日志为`plan/queued-driver.log`，状态为`plan/queued-driver-state.json`。
接续阶段启动后还会产生`plan/long-driver-state.json`及
`driver/<stage>/attempt-NNN/command.log`。

当前三个seed10001基准轮全部完成并通过哈希/退出码核验后，队列顺序执行：
其余转发策略12轮采样开关验收 → 补齐42轮NoForward预实验 →
独立seed10003三轮 → 三场景临时模型各三初始化1epoch →
真实Neural六轮开关及动作验收 → 完整预实验资源/覆盖报告。
全部串行、`JOBS=4`，BLAS及训练线程限制为1；任一阶段失败立即保留证据并停止依赖阶段。
队列标记`complete`只表示请求的`through=pilot-report`前缀完成，不表示完整研究任务完成。

随后依据实际报告记录开发冻结决策，再推进正式采样和训练；P4实际工程预检后
另记正式冻结决策，才进入独立评估、4080轮和图集。两个决策沿用现有用户授权，
是AI对实际证据与资源的审核，不是新增的用户许可要求。当前不伪造这两个决策文件。
训练与P4的超时分别从开发决策中的`training_timeout_seconds`、
`preflight_timeout_seconds`读取，避免在实测前把诊断默认值固定为正式资源结论。

## 资源与科研约束

继续串行执行真实SUMO/Gym与模型训练；预实验后才能填入可信总耗时和采样配额。
网络/控制仍为L3 OUT，额外Data仍为应用提交口径，不修改底层统计。
不根据正式结果好坏删条件、减少20次重复或调整模型；失败运行与无效样本需保留原因。

## 已实现的阶段入口

以下是操作约定，不表示这些阶段已经执行。所有命令从`ns-3/`根目录运行，
先设置`export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1`。
调度器和阶段工具串行工作，重复执行同阶段会校验已有产物后恢复，失败attempt保留。

| 阶段 | 入口及先决条件 |
|---|---|
| 初始化候选 | `python3.8 tools/experiments/campaign.py init --root data/experiments/retrain-20261021`，拒绝覆盖已有design |
| 冻结pilot源码 | `campaign.py freeze --root ... --phase pilot --timeout ...`，只冻结当前候选用于预检，不代表P2开发配额已定 |
| 采样 | `campaign.py run --root ... --split pilot`；P2冻结后分别使用`train`、`validation`、`evaluation` |
| 构建三个数据集 | `campaign_workflow.py datasets --root ...`，要求开发设计冻结、三个采样split全部完成 |
| 三场景训练 | `campaign_workflow.py train --root ... --training-config ...`，配置固定至少3个初始化种子，仅train/validation参与优化和选择 |
| 冻结模型 | `campaign.py freeze --root ... --phase formal --model circle=... --model grid=... --model spidermap=... --timeout ...`，严格核对三模型契约、来源源码和临时标记 |
| 独立模型评估 | `campaign_workflow.py evaluate --root ...`，仅在三模型冻结后执行 |
| 正式四策略矩阵 | `campaign.py run --root ... --split test`，完整17条件×3场景×4算法×20种子 |
| 完整统计与图集 | `campaign_workflow.py figures --root ...`，拒绝缺轮、缺策略、哈希变化或临时结果混入 |

`campaign.py`和`campaign_workflow.py`均位于`tools/experiments/`。
阶段工具不自动决定P2采样配额，不自动冻结模型，也不自行启动仿真。
正式训练配置中的`initialization_seeds`为独立初始化种子数组，其余字段沿用训练CLI
的下划线名称（如`hidden_size`、`batch_size`、`selection_tolerance`）。
具体冻结值、资源限额与实际命令在P2/P4验收后追加，不把候选默认值当作实测结论。
