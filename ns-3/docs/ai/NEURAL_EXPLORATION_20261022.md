# 神经策略进一步改进探索（2026-10-22）

**后续采用决定（2026-10-22）：** 用户明确选择“三个场景均启用，接受spider本轮小幅退化”。
随后正式合入了相同的双端实现，见[正式合入记录](NEURAL_WIRE_INSTALL_20261022.md)。
下文“未合入/保持隔离”和旧生产库身份描述的是本次探索结束时的历史状态，
不能作为当前禁止安装的指令；spider未通过性能门槛及所有实验数值保持原样。

**最终结论：找到一个能改善circle交付、对grid有小幅收益的候选；spider未通过非退化检查。**
候选只在神经策略中使用无损CBOR状态报文，模型、概率阈值和统计定义未改。
保留隔离实现与全部原始结果，**正式默认代码及库没有替换**。不宣称模型分类准确率提高，
也不宣称三个场景均超过RTVTDF。共18轮，运行器记录的逐轮耗时合计31.06分钟。

| 场景 | 当前NN成功率 → 候选 (%) | 当前NN成功RTT → 候选 (ms) | 性能门槛 |
|---|---:|---:|---|
| circle | 85.4083 → 90.6250 | 430.8669 → 346.4444 | 通过 |
| grid | 90.1000 → 90.4667 | 315.3170 → 314.0629 | 通过 |
| spidermap | 60.7417 → 60.7167 | 301.3849 → 301.5705 | 未通过 |

这些是每场景两个开发种子的等权均值，只覆盖10车/6000请求条件，不代表完整参数扫描或独立显著性验证。

## 授权与边界

用户要求探索其他提高神经策略效果的方案，先在circle小批量验证，通过后才在grid和spidermap验证。
沿用已确认的成功率与交接时延优先级，区分模型分类、目标站覆盖和最终业务交付。
现有仅神经策略使用的hello优化继续保留；其他策略继续使用旧JSON编码。
额外机制仅在AI/实验Markdown文档解释，不改对比HTML、图表、原指标、旧结果或原模型。

本次起始Git版本`f623b37c5e3da8becc673e08c1361c186604c648`，工作树起始无改动。
当前生产主库SHA256为`b73e0752d551e466c8f8dcec3a7015eaf98503f3f3779e6b6fb312a854da9504`。
候选先保存到`build/validation/neural-explore-20261022/`隔离目录，未通过不能当作正式实现。
所有构建/运行设`JOBS=4`，不执行configure或大批量重编。测试与真实仿真串行，避免全局实验锁冲突。

## 先验诊断与候选顺序

只读重算此前保留A+B+E的circle运行（seed52001/63011）发现：
11824次实际回程有11808次覆盖当时服务站，其中仍有1511次交付失败。
这里取请求截止前“任一实际选中RSU从Router收到Data的最早时刻”，
查询该时刻记录的车辆服务站是否在选中集合中；不是原请求RSU的首次回程时刻。
这是选站集合覆盖，不能替代训练契约定义的分类准确率，
也不是本次新种子的性能结果；完整逐请求证据见`prediction-audit/README.md`及其JSON。

- 降低第二路阈值0.10→0.05：固定旧轨迹诊断多90条支路，仅多覆盖7个旧失败请求；
  不能据此预言仿真获救数，新增竞争可能使收益消失。
- 强制保留遗漏的源站：多14条支路，静态多覆盖4个旧失败请求，同样不是在线改进证明。
- 提高第二路阈值0.20虽少58条支路，但丢掉6次已有覆盖，其中5次原先成功，不优先采用。
- 真正增加history age/接收间隔输入需要新模型契约、重新训练及独立评估，超出本轮低成本候选首选范围。

第一候选为**仅神经策略使用无损、带版本的紧凑状态报文**：
四字节`VNH1`标识后是CBOR数组`[1, [六维原值], NextRsu, cacheObject]`。
保留原数值精度、字段含义、缓存更新、hello频率及模型输入顺序；RSU解码回原有JSON对象后走原逻辑。
三个非神经策略逐字保留原JSON输出，接收端继续接受旧JSON。
该候选瞄准无线报文/排队成本，不能将其收益写作模型权重的分类准确率提高。

## 固定小批量设计

固定计划保存在`build/validation/neural-explore-20261022/plan.json`及
`data/experiments/neural-explore-20261022/plan.json`，先于本轮结果生成。

- 每个场景10车、速度设置30km/h、6000个首次业务请求。
- 20秒预热、120秒测量、3.5秒排空；两个开发种子52001/52002。
- 输入沿用`retrain-quick-20261021/inputs/test/<scene>/baseline/<seed>/experiment-template.json`。
- 三模型继续使用各自`retrain-quick-20261021-*-session/checkpoint.pt`，计划内固定精确路径和SHA。
- 先跑当前circle的RTVTDF和NN各两个种子，再跑候选NN两个种子。
  当前RTVTDF已恢复旧hello编码，不能拿上次共享优化的RTVTDF结果冒充本次对照。
- circle通过后，grid/spidermap各重复上述配对。固定交接子集继续读取旧NoForward冻结cohort，
  只作为相同请求分组，不拿旧NoForward关联结果充当当前策略性能。

circle推进门槛：运行/数据完整性通过；候选NN在两个种子的ISR均不低于当前NN，
两种子平均成功RTT不升，固定交接请求成功总数不减。
所有失败候选、成本变化和混合结果保留，不因结果不利改种子、分母或分组。
这是开发探索，两个已使用种子不支持独立泛化或统计显著性声明。

## 当前进度

修改前六项hello行为测试及五个相关C++套件已执行通过，原始命令和退出码位于`baseline-tests/`。
18轮真实仿真全部完成并校验通过。circle/grid通过性能推进门槛，spidermap未通过，未将候选全局合入。
生产实现尚未改变，未启动训练或完整论文批次。

## 第一候选的行为与构建验证

`candidate-wire-v1/test_wire_codec.py`提取真实OBU/RSU相关分支验证协议及状态更新。
旧实现有效RED为435项检查中的15项失败，原因是NN未采用新编码且RSU不接受新编码。
新增版本边界检查还发现一次无符号整数下界校验问题，已修正；最终`frozen-green/`中
441项检查通过，覆盖56个策略/缓存/数值状态及24个坏输入。负零、极小和极大double位值保持，
另外三种策略的输出字节保持原样，旧JSON接收语义保留。

候选源在`candidate-wire-v1/source/`；`overlays/wire-v1/`仅编译两对象、链接一隔离主库，
三场景程序及其他共享库身份保持。库SHA为
`a930351bd444aaa3f1bf6a3291ce56d3ba247a1b3b5b50c1b01f93674998ba4f`。
未执行waf configure或全量构建，未覆盖生产库。隔离入口为`overlay.py`，
必须保留每轮`overlay-provenance.json`，因为普通source_snapshot仍表示生产源树。

隔离库实际加载到debug test-runner后，五套件共19个用例通过：
forwarding-policy、return-selection、neural-return-buffer、training-snapshot、router-neural-pit。
证据在`candidate-cpp-tests-debug/`，含ldd解析及XML。
此前误选optimized test-runner得到“no tests match”，保存在`candidate-cpp-tests/`；
这是测试入口错误，不算有效RED或候选行为失败。

## circle阶段结果（已通过）

原始数据位于`data/experiments/neural-explore-20261022/{current,wire-v1}/circle-{52001,52002}/`。
复算报告：`build/validation/neural-explore-20261022/analysis/circle/wire-v1/20261022T043257.486108Z/`。
以下为两个种子逐轮指标的等权均值，未按成功请求数重新混合RTT。

| 版本 | ISR (%) | 成功RTT (ms) | 网络 (Mbit) | 控制 (Mbit) | 应用额外Data次数 |
|---|---:|---:|---:|---:|---:|
| 当前RTVTDF | 83.2833 | 440.7434 | 2072.1530 | 118.5212 | 69.5 |
| 当前NN | 85.4083 | 430.8669 | 1577.7996 | 90.6129 | 98 |
| 候选NN | 90.6250 | 346.4444 | 1545.2829 | 52.8838 | 98 |

NN两个种子的ISR分别提升5.5333、4.9000个百分点。
固定交接子集成功数为390→425（669请求）、375→428（655请求），合计765→853。
交接成功RTT分别438.674→328.600ms、455.508→347.825ms。
同一子集仍有48/44个请求从成功变失败，净收益不能解释为逐请求都改善。

独立准确率诊断见`prediction-current-wire/circle-paired-results.json`。
严格使用原请求RSU实际首次收回Data的时刻作为标签时间，只评价源站有回程且关联可确定的子集：
当前两轮共有11821个可评价决策，其中top1正确11767，所选集合覆盖11815；
候选为11857个可评价决策，其中top1正确11822，集合覆盖11855。
源站未返回的14/20个决策不算错误或正确，不用别的站先到时刻代替。
无决策请求165→123，已覆盖却交付失败1574→992。此处样本子集随协议运行变化，
不能据此宣称固定测试集模型分类能力提升；模型权重未改变，实际交付改善才是本轮主要结论。

## grid阶段结果（已通过同样检查）

六轮原始数据在`data/experiments/neural-explore-20261022/{current,wire-v1}/grid-{52001,52002}/`。
报告为`analysis/grid/wire-v1/20261022T044410.021468Z/`（相对本次build证据目录）。

| 版本 | ISR (%) | 成功RTT (ms) | 网络 (Mbit) | 控制 (Mbit) | 应用额外Data次数 |
|---|---:|---:|---:|---:|---:|
| 当前RTVTDF | 91.0417 | 343.3893 | 2033.5540 | 130.7887 | 347.0000 |
| 当前NN | 90.1000 | 315.3170 | 1539.6864 | 99.5586 | 283.0000 |
| 候选NN | 90.4667 | 314.0629 | 1500.5552 | 60.5921 | 282.0000 |

两个种子的ISR均提升0.3667个百分点，固定交接成功总数1716→1747。
候选RTT比当前NN低1.254ms，收益较小；相对当前RTVTDF，候选成功率仍低0.575个百分点，
尽管RTT和负载更低，不能说grid已经在所有指标胜过RTVTDF。

源站可评价子集的top1正确/总数：当前10957/11171，候选10926/11167，
这项运行条件下的诊断反而略降；选中集合覆盖11149→11145，覆盖但失败387→344。
样本不完全相同，不能解释为离线模型退化，但更不能宣称模型分类准确率提高。
明细及排除原因保存在`prediction-current-wire/circle-grid-paired-results.json`。

## spidermap阶段结果（性能门槛未通过）

六轮原始数据在`data/experiments/neural-explore-20261022/{current,wire-v1}/spidermap-{52001,52002}/`。
报告为`analysis/spidermap/wire-v1/20261022T045342.139753Z/`（相对本次build证据目录）。

| 版本 | ISR (%) | 成功RTT (ms) | 网络 (Mbit) | 控制 (Mbit) | 应用额外Data次数 |
|---|---:|---:|---:|---:|---:|
| 当前RTVTDF | 61.1583 | 317.7104 | 1334.8836 | 100.4563 | 100.0000 |
| 当前NN | 60.7417 | 301.3849 | 1003.0659 | 76.3884 | 69.0000 |
| 候选NN | 60.7167 | 301.5705 | 973.0537 | 45.8404 | 71.5000 |

seed52001：ISR66.8500→66.8667%，RTT301.4857→301.7595ms；
seed52002：ISR54.6333→54.5667%，RTT301.2841→301.3816ms。
均值ISR降低0.025个百分点，RTT增加0.1856ms，固定交接成功总数547→545。
这三个性能条件均未通过。差异很小，不据此声称显著恶化，但不能改门槛把它记为通过。
控制负载虽约下降40%，不能替代成功率与交接时延优先目标。

## 综合判断与证据边界

- circle候选相对当前NN：ISR提高5.2167个百分点，成功RTT降低84.4225ms，两个种子均同向。
  相对当前RTVTDF：ISR提高7.3417个百分点，RTT降低94.2991ms。
  但应用额外Data次数均值比RTVTDF多28.5次，不能称五指标同时最优。
- grid候选相对当前NN：ISR提高0.3667个百分点，RTT降低1.2541ms；相对RTVTDF，ISR仍低0.5750个百分点。
- spider候选相对当前NN基本持平但未通过预定门槛，相对RTVTDF的ISR仍低0.4417个百分点。
- 仅神经策略享有此前和本次编码优化，不能把全部相对RTVTDF的收益归因于神经模型。
  这些实现差异只在Markdown实验/AI文档解释；对比HTML及图未添加机制标注或改统计结果。
- 网络/控制负载继续采用既有NDN L3网络Face出站字节；额外Data继续为应用显式提交次数，
  不是MAC实际总流量或全部实际副本。没有改分母、补算缺失标签、挑种子或删除负向运行。
- 三场景的代码运行与数据闭合验证通过，不等于每个场景性能提升：spider有明确性能失败证据。
  本次完成的是候选探索和小批量验收，没有启动重训练或完整论文实验。

最终逐预测审计为`prediction-current-wire/all-complete-results.json`：12个完整神经运行均核验，
6个RTVTDF按定义跳过，并非剔除失败实验。RSU回程Face258已用grid/spider各16轮历史完整角色表核实，
32轮共224个RSU的Router接口一致，依据实际P2P设备与对端角色判定，不是假定协议固定编号。
多决策请求另列，不任挑首条；源站未返回、无决策等都保留原请求性能分母。

circle显示主要收益来自减少已覆盖路径但交付失败的请求。grid/spider仍需区分“有预测但失败”
和“请求没有产生决策”；不能仅凭no_decision推断无线丢失，也不能靠调模型修复一个尚未进入推理流程的请求。
改变模型特征、增加history age/接收间隔、重新采样训练应另建契约及独立评估，不与本轮固定模型结果混用。

### spider无决策请求的补充定位

`spider-no-decision/`保留四轮逐请求证据、哈希和连续失败段。当前NN两种子共有4644个无决策请求，
全部TIMEOUT，占其4711个失败请求的约98.58%；候选无决策总数为4643。
生成时无关联站的数量为255/1539，有记录服务站但无决策为1695/1155；候选仅第一组后者少1。
全部有原OBU同名Interest的L3出站，未发现同名RSU/Router出站或Data到达，缓存成功样本为0。
现有采集不记录InInterest，不能据此把每个请求确诊为无线丢失。

有站却无决策存在连续78.6/82.8秒失败段，新旧相同。OBU邻居2秒过期清理当前只在收到hello时触发，
生成记录中rsu_id有值并不保证hello新鲜；陈旧站只是待验证假设，未实施修复。
下一步定位应记录hello年龄、发送目标MAC、RSU Interest接收，并核实物理覆盖，保持原请求统计分母。
seed52002的2694个无决策ID新旧完全相同；实际净少4个成功发生在已决策请求中（7失3得），
7个新增失败均有RSU有线Data到达及业务Data出站、没有目标OBU接收。

独立复核未调用现有汇总/门槛实现，直接重计18轮原CSV，核验258个产物、108个输入引用、
201个保护文件，结论一致。见`final-review.md`和`final-independent-audit.json`；
全目录恰18个manifest，全部complete，没有漏报失败或异常attempt。

## 保留与复跑方式

正式OBU/RSU源文件、默认主库和模型均未替换。候选源码、私有协议头、测试、构建计划、
冻结SHA和运行命令完整留在`build/validation/neural-explore-20261022/`。
每轮原始证据在`data/experiments/neural-explore-20261022/`，与旧quick批次隔离。
不改统计工具、HTML报告或论文图，旧结果仍对应旧版本。

本次候选是一个带版本的双端协议变更，后续正式合入时必须同步修改OBU发送端和RSU接收端，
并更新现有hello测试中“NN内容一定为JSON”的假设，保留无损和非NN字节兼容断言。
不允许只安装发送端；旧RSU不能解析VNH1。当前兼容方向是新RSU能读旧JSON。

在项目根目录重算本次完整场景结果（只读原始数据，输出新报告目录）：

```bash
python3.8 build/validation/neural-explore-20261022/analyze.py --scene circle --candidate wire-v1
python3.8 build/validation/neural-explore-20261022/analyze.py --scene grid --candidate wire-v1
python3.8 build/validation/neural-explore-20261022/analyze.py --scene spidermap --candidate wire-v1
```

每场景生成`results.json`、`seed-level.csv`、`REPORT.md`，未完成轮次明确为pending，
不计零或失败。程序重算原五指标并验证完整性、计划输入、模型、动态库、轨迹和请求配对。
真实命令在`circle-current-state.json`、`circle-wire-state.json`、`cross-scene-state.json`。
若需要重跑，必须选新输出目录并保留此前结果，不改现有manifest来伪装相同版本。

隔离候选单轮命令示例（新目录，当前已验证的同一模型与输入）：

```bash
export JOBS=4
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 build/validation/neural-explore-20261022/overlay.py run \
  --overlay build/validation/neural-explore-20261022/overlays/wire-v1 -- \
  --config data/experiments/retrain-quick-20261021/inputs/test/circle/baseline/52001/experiment-template.json \
  --output-root data/experiments/neural-explore-20261022/manual-circle-wire-recheck \
  --block-id manual-circle-wire-recheck --strategies 3 \
  --model-file data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt \
  --require-formal-contract --validation-only --no-build --timeout 900 --python /usr/bin/python3.8
```

该入口检查冻结源码/依赖SHA；正式代码或构建依赖以后改变时会拒绝运行，需要为新基线重新准备候选，
不能删除哈希检查强行复用。这些小批量运行均为开发验证，未修改或重新启动完整论文实验。


## 证据索引与备份

- 固定设计、模型路径/SHA：`build/validation/neural-explore-20261022/plan.json`。
- 全部18轮的路径、种子、策略、耗时及manifest SHA：同目录`runs-index.csv`。
- 最终三个场景报告路径、原五指标、逐项门槛和生产库SHA：同目录`final-summary.json`。
- 实现、行为测试、隔离构建/运行工具及分析证据的本地文档副本：
  [records/neural-explore-20261022](records/neural-explore-20261022/)。
  该records目录沿用工作区现有Git忽略规则；没有自动加入版本控制，不等于异机备份。
- 原始18轮数据留在`data/experiments/neural-explore-20261022/`，每轮含manifest、experiment、
  run-metrics、simulation/controller日志和raw目录；候选额外含overlay-provenance。
  不覆盖此前quick数据、模型、图和迁移出图包。
