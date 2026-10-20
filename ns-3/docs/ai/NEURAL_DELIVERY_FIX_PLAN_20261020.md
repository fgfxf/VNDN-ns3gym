# 神经回程出站后未交付：定位与经过小规模验证的修复计划

后续状态：用户已明确要求“执行修改”，四文件正式修复及验收另记于
[正式修复记录](NEURAL_DELIVERY_FIX_20261020.md)。下文保留提出计划时的证据和授权状态，
其中“未合入、需确认”不再代表当前实施状态。

日期：2026-10-20。起始提交 `86ef39c`。本轮任务是进一步排查并验证修复方案，
不是将原型合入正式源码。原型、独立构建、原始日志和抓包全部放在
`build/validation/neural-delivery-diagnosis-20261020/`（下称 `R/`）。
正式源码、原模型、历史数据及 `ns-3_old` 保持不变。

## 结论与证据边界

已确认一个失败请求存在两个连续问题：

1. Router 的迟到重复 Interest 重新建立网络 PIT in-record，导致服务器 Data
   先自动沿普通路径返回。它没有目标车辆 MAC 标签，抢先消耗了 RSU 准备好的 PIT；
   随后的正确神经回程副本成为 unsolicited Data 被丢弃。
2. 消除上述抢跑后，首片虽然正确单播，后续 LP 分片仍广播，目标车辆缺片而无法重组。
   联合原型让同一报文的所有分片保留目标 MAC 后，原失败请求成功交付。

**“补 outface”不能解释或修复本例。** RSU 的无线 Face 257 存在，PIT 已预备，
有 L3 出站、真实无线帧和车辆接收到部分分片的证据。需要区分 Face、PIT in-record
和上游 Interest 的 out-record：Data 返回车辆依赖下游 in-record；
`OnNeuralPitPrepareData()` 已调用 `insertOrUpdateInRecord()` 与协议 PIT 定时器接口。
`NextHopFaceIdTag` 也已有使用，不能因看到超时就再强制发送一份 Data。

这次证明的是具体协议与分片缺陷以及原型效果。此前436个“有无线出口无目标入口”
事件是否都具有相同根因尚未逐一证明，模型预测准确率也需另外评价。

## 固定请求的端到端证据

圆圈、种子1、OBU2、请求 `exp-00000:8`：
`/com/baidu/www/userid/2/%FE%08`，生成于 5.788859800s，当时服务 RSU1。

| 时间 | 未修复版本的行为 |
|---|---|
| 5.809083521s | Router 收到首 Interest，应用代理请求并移除原网络 PIT |
| 5.809090880s | 神经回程指令生效，选定 RSU1 |
| 5.809097919s | 重复 Interest 建立网络 in-record，随后被策略抑制，没有再交给应用 |
| 5.829100400s | RSU1 已准备无线 Face 257 的 PIT |
| 5.929928001s | Router 先自动向 RSU1 返回未加目标标签的 Data，再由应用发送正确副本 |
| 5.950767921s | 首副本在 RSU1 满足 PIT，并分成5片广播 |
| 5.951610641s | 正确副本到达 RSU1，`onDataUnsolicited ... decision=drop` |
| 8.788859800s | OBU2 超时 |

Router 在场景中使用默认 BestRouteStrategy2，其初始重复转发抑制间隔为10ms；
本例两次网络 Interest 相隔14.398μs。NFD 在决定抑制前已经写入 in-record，
所以仅在 Router 应用的 pending 合并分支里清理记录，覆盖不到这次竞态。

| 同一请求的版本 | 逻辑分片数 | 无线发射次数，含MAC重试 | 单播/广播发射 | 目标收到的片号 | 应用结果 |
|---|---:|---:|---:|---|---|
| 未修复 | 5 | 5 | 0 / 5 | 4 | TIMEOUT |
| 仅修 Router | 5 | 9 | 5 / 4 | 0–3 | TIMEOUT |
| Router＋所有分片保持目的地址 | 5 | 10 | 10 / 0 | 0–4 | DATA |

仅修 Router 时，首片经4次 MAC 重试后被车辆收到并 ACK；末片仍为广播且未被目标收到。
联合版末片发生一次 MAC 重试，车辆于5.984009079s收到完整 Data，
L3 IN 和应用 DATA 终态均存在，RTT为195.149279ms。
按目标抓包重组得到的 Data 字节与源端一致。
这不是绕过无线模型直接投递，也没有增设应用层超时重发。

证据：
`R/lp-endpoint/target08-version-comparison.json`、
`target-{baseline,router,both}-seed1.json`、
`target-router-seed1-ack-evidence.json`、`target-both-seed1-tail-ack.json`。
抓包没有所有 PHY 丢包原因，缺少成功 RX 不能进一步断言具体 SINR 或碰撞原因；
ACK 归属按临近时序、接收地址及交换关系判断，ACK 字节本身不保证唯一。

## 小规模测试与结果

本轮共16轮圆圈小规模仿真，均完成并通过请求闭合校验；每轮2车、600请求，
发包窗口 `[5,35)`、排空至38.5s，设定100km/h，实测时间加权约99.88964km/h。
固定ns-3 Seed/Run、SUMO seed、C rand seed与上一轮三组输入一致。
真实模型仍为 `data/models/circle/tkan-lstm/20260813-202805/`
`tkan-lstm-circle-noforward-20260813-202805.pt`，未训练或修改权重。
同种子路网、路线、请求计划及实际GENERATED的Name/车辆/节点/纳秒时刻逐项一致。

种子1的两因素对照如下，保留了两个单项不足的结果：

| 版本 | 成功/600 | Router自动网络回程份数 | 固定请求08 | 机制＋目标断言 |
|---|---:|---:|---|---|
| 未修复 | 570 | 598 | TIMEOUT | 失败 |
| 仅Router | 570 | 0 | TIMEOUT | 失败：交付未达标 |
| 仅分片目的地址 | 580 | 597 | TIMEOUT | 失败 |
| 两者联合 | 593 | 0 | DATA | 通过 |

仅Router版本虽与原版本成功总数相同，但7个请求变好、7个变坏，不能写成逐请求行为不变。
联合版明确选站的615份Data与实际Router网络回程615份一致，没有自动额外分支；
600次清理被观测到。实际600个请求全部有终态，失败请求未被剔除。

以下三种算法均使用**相同修正后的底层和Router原型**：

| 种子 | VTDF | RTVTDF | Neural | 修复前Neural，仅作同策略前后参考 |
|---|---:|---:|---:|---:|
| 1 | 597/600 | 599/600 | 593/600 | 570/600 |
| 2 | 583/600 | 596/600 | 594/600 | 382/600 |
| 3 | 597/600 | 598/600 | 594/600 | 407/600 |
| 合计满足率 | 1777/1800，98.7222% | 1793/1800，99.6111% | 1781/1800，98.9444% | 1359/1800，75.5000% |
| 合并成功请求平均RTT | 191.232ms | 181.098ms | 184.392ms | 178.904ms |

Neural交付率提高，但仍低于RTVTDF；也不是每个种子都高于VTDF。
**“神经策略不差于两种转发策略”的效果目标尚未达到，统计非劣性也未建立。**
成功RTT的样本集合随交付率改变，不能只比较平均RTT而忽略成功/失败变化。

另外，在同一修正底层下，种子1分别运行“有/无Router修复”的NoForward、VTDF、RTVTDF，
三对成功数分别为554/554、597/597、599/599；每对的`request-events.csv`、
`mobility-events.csv`、`packet-l3.csv`、`data-attempts.csv`、`data-rx.csv`均逐字节相同。
这支持Router改动在本轮非神经对照中保持无作用，不能扩展为任意场景都已回归通过。

严格汇总为 `R/followup-matrix-summary.json`：16/16本轮运行、9/9历史参考均有效，
`verification_passed=true`；单独的逐种子Neural不低于两转发策略字段为`false`。
汇总器11项行为测试通过，包括拒绝未完成输入、计划/实际请求错配和同底层对照不一致。
历史9轮不是本轮新跑，完整来源见[上一轮策略核查](STRATEGY_REGRESSION_20261020.md)。

真实 GLS 行为测试使用10KB Data、MTU1500，运行生产 GenericLinkService 分片、
逆序接收及重组，共9例。原库因分片尾部丢失目的地址而退出1，
候选库同一测试程序退出0；全部分片未超MTU、重组内容一致。
覆盖无标签、零目标、已有非零 endpoint、显式目标优先、小包及P2P的GLS接口行为。
P2P RecordingTransport 用例不能代替真实 P2P 网络验证。
见 `R/gls-fragment-destination/{build-results,test-results}.json`。

隔离运行器3项、Router日志分析7项、抓包分析8项行为测试均先失败后通过；
这些只验证验收工具，不能替代真实 C++/无线实验。
`accept_router_log.py` 同时检查机制和目标终态：
未修复和仅Router版本的整体断言均失败，联合版才满足两部分断言。

## 推荐正式修复范围

推荐按两个独立提交实施，分别保留原始失败测试，再联合验收。
正式实现共4个源码文件，其中2个为底层文件；测试、注册、验证入口和文档另列。
**第二部分需要改两个此前排除的底层文件；当前只在隔离副本中测试，
若仍坚持完全不改底层，则只能采用第一部分，不能宣称本例交付缺陷已经解决。**

| 文件/范围 | 修改内容 | 影响 |
|---|---|---|
| `contrib/vndn-nn-rd/apps/vndn-router.cc/.h` | 订阅网络 Face 收 Interest 后事件；仅对有效 Neural pending 的匹配业务请求删除网络 in-record；保留本地 app in-record、服务器 out-record和等待状态；晚到指令/应用合并同样清理；Stop/析构解除订阅 | 三场景共用 Router，增加成员需重编所有使用该类的模块/入口 |
| `src/ndnSIM/NFD/daemon/face/generic-link-service.cpp` | 分片前取完整包的非零 `VndnTag.targetMac`，经发送 endpoint 传递给本报文全部分片 | 使用该自定义目标标签的所有策略和场景 |
| `src/ndnSIM/model/ndn-net-device-transport.cpp` | 非P2P发送分支优先采用非零目的endpoint，即使本片无标签；endpoint为零才沿用原标签/广播处理 | 作用于所有非P2P NetDevice，当前场景为WiFi；尾片得到与首片一致的寻址、ACK和MAC重试行为 |
| `contrib/vndn-nn-rd/test/`、`wscript` | 新增 Router PIT竞态和分片目的地址行为套件，注册执行 | 保留回归保护 |
| `tools/validate.py`、相关工具测试 | 将新套件纳入强制验收，拒绝零测试/跳过 | 更新验证步骤 |
| `docs/ai/PROJECT.md`、`VALIDATION.md`、`CHANGELOG.md` | 记录回程所有权、目的地址约定、验证与限制 | 后续AI维护依据 |

不需要改 `forwarder.cpp`、`strategy.cpp`、本地传输、fragmenter或reassembler。
不修改模型权重、概率阈值、训练标签、SUMO路线或统计分母。
原型补丁分别是 `R/router-prototype/router-neural-pit-owner.patch` 和
`R/fragment-destination-prototype/fragment-destination.patch`。

### 实施步骤与验收门槛

1. **先补正式 C++ 回归，确认未修复时真实行为失败。**
   用4个P2P节点建立实际 Router、两个RSU侧peer和Server；
   Router保留场景默认BestRoute抑制行为。
   注入同名不同nonce、间隔小于10ms的重复Interest，确认它未再次送应用，
   但重建了网络in-record。断言修复后仅移除网络记录、保留本地与服务器记录，
   服务器Data只经选定的一条/两条神经分支返回，内容和目标MAC正确。
2. **实现应用部分并检查作用域。**
   覆盖晚到neural-route、重复清理、无pending、非神经请求、控制前缀、
   不匹配selectors、Nack/超时、Stop/析构，防止影响普通NDN请求或出现悬空回调。
3. **实现两文件分片目的地址修复。**
   将本轮9例GLS测试转为项目测试套件；增加真实NetDevice无线发送检查，
   覆盖无有效目标且endpoint为零的广播、零tag且既有非零endpoint的寻址保留、
   带目标的多片/单片、P2P和本地路径。
   使用现有8字节ns-3 Address编码，不能误当作裸48位MAC。
4. **增量编译与回归。**
   `export JOBS=4`，使用现有waf配置、`-j 4`，不例行configure。
   重编两个底层对象并重链接`libns3-dev-ndnSIM-debug.so`、
   完整研究模块及三个入口，执行新套件和已有相关套件；
   运行 `python3.8 tools/validate.py`。编译或测试失败即保留为未通过。
5. **三场景、四策略端到端验收。**
   固定输入与种子，覆盖切换、单/双目标、原RSU/其他RSU、失联和排空；
   同时核对请求闭合、Router实际分支、RSU/OBU L3、无线分片、最终DATA。
   方阵/蜘蛛网没有匹配的真实七类模型时，只能用明确标记的控制器验协议，
   不能写成真实模型质量已通过。
6. **重新做同底层的模型效果对照。**
   所有算法使用相同底层修正、工作负载和随机块，再评估ISR、RTT和负载。
   正式非劣性结论需预先约定差值容限、足够独立重复和置信区间；
   本次小样本和单个请求修复不能代替这一结论。

### 保留的限制

- Router观察者处理的是已复现的CS-miss竞态。CS直接命中会在观察者执行前响应，
  动态新建Face、共享Name的多个消费者、CanBePrefix/多PIT等需独立测试和明确支持范围。
  当前实验使用包含OBU与序号的请求名，P2P Face在启动前建立。
- 当前StackHelper未开启LP可靠重传。若未来开启，
  `LpReliability`的重传分支仍传endpoint0，必须另补目的地址保持；
  不把本方案写成所有可靠重传配置均已支持。
- 尾片单播可能增加MAC重试、ACK和信道竞争；成功RTT不保证下降。
  现有network overhead是L3字节，不含MAC重试，不能由L3总量推断空口开销。
- 另发现接收端未区分源endpoint的潜在重组缺陷：真实LP夹具中两个发送者同序号交错，
  endpoint均0时产生混合报文，分离endpoint后正确恢复两份；控制用例均通过。
  见 `R/lp-endpoint/test-results.json`。本例抓包尚未证明由它导致丢失，
  因此不混入本次推荐主修复；以后处理时需联合核对收发endpoint编码。
- `OnNeuralReturnData()`把Router回程tag的sender字段当作OBU，
  本例日志出现暂存“OBU=1”，而目标实际为2。它不是本例无线首发失败的必要条件，
  联合版仍凭预备PIT交付；该旧旁路另列后续核查，不在本次四文件修复范围内，
  不应在此次顺便改成额外转发。

### 联合原型剩余的19个超时

| 种子 | RSU无线出站包含当时记录服务站，但目标无L3接收 | 仅向不同站出站 | 无RSU业务Data阶段 |
|---|---:|---:|---:|
| 1 | 6 | 1 | 0 |
| 2 | 5 | 0 | 1 |
| 3 | 4 | 0 | 2 |

唯一不同站请求在出站4.96ms后切换到该站，不能直接认定模型选错。
另3个请求只见OBU Interest OUT，完整日志未见对应Interest进入RSU/Router，
并在发包后约13.77、9.95、82.68ms换站。19个请求在目标OBU均没有L3 Data接收，
也没有“L3已收、应用仍超时”的案例。
这些是后续排查的阶段分类，不是物理丢失原因或模型错误标签。
见 `R/lp-endpoint/remaining-timeouts-three-seeds.json`；
保留19个请求及逐事件行号，未从ISR分母移除。

## 复现与产物

所有隔离构建均设置`JOBS=4`，编译并行最多4；未运行waf configure，未替换主build库。
Router增加成员，故用一致的16个公开头完整重编10个研究模块源文件和3个场景入口，
共13次编译、4次链接，均退出0。底层候选只替换两个对象、复用285个未变对象，
两次编译及共享库链接均退出0。两个候选分别构建后，用`combined/lib`组合加载。
三场景入口编译成功不代表三个场景都已完成运行验收；本轮仿真范围只有圆圈。

主要文件：

- `R/router-build/{build-plan,build-report}.json`、`R/overlay/fragment-destination/{plan,report}.json`：完整构建命令、候选源/依赖/产物哈希。
- `R/run_diagnostic.py`：复用现有实验运行器的配置、串行互斥和闭合校验，直接调用已构建程序；开启抓包，不触发waf。
- `R/followup-matrix-plan.json`、`followup-matrix-execution.json`：后续13轮的预定矩阵、命令、退出码和耗时；之前3轮分别为未修复、仅Router及联合首轮。
- `R/runs/<variant>/<run-id>/`：manifest、独立原始CSV、pcap、完整NS_LOG、模型控制器日志及汇总。
- `R/{baseline,candidate}-router-acceptance.json`、`fragment-seed1-router-acceptance.json`、`both-seed1-router-acceptance.json`：两因素对照的严格日志验收。
- `R/provenance-check.json`：事后只读56项核对全部通过；包含1547个主项目源码快照文件、126个原始库、291个受保护原始文件以及隔离产物。
  原始库的运行前/后哈希均有保存；事后补做的ldd明确标记为事后复核，不假称采集了运行时/proc映射。
- `R/source-model-freeze-check.json`：全矩阵完成后重算生产源码、模型与候选哈希，均匹配；
  明确记录之后新增/修改的三个文档文件，不把完成后的整个工作区描述为干净状态。
- 模型SHA256：`ab0015243af833550a3486be858aeb07d57c1b86b65d390c897e0cf9316918ca`。

重现联合候选的运行命令如下，前提是上述隔离构建与`combined/lib`中的两个库链接已准备好：

```bash
export JOBS=4
python3.8 build/validation/neural-delivery-diagnosis-20261020/run_diagnostic.py \
  --variant reproduce-both-seed1 --seed 1 --strategy 3 \
  --overlay /home/fgfxf/ndnSIM/ns-3/build/validation/neural-delivery-diagnosis-20261020/combined/lib \
  --binary-directory /home/fgfxf/ndnSIM/ns-3/build/validation/neural-delivery-diagnosis-20261020/router-build/bin
```

详细协议日志需沿用`diagnostic-environment.json`中记录的NS_LOG；该设置与抓包均未改变基线的600请求结果。
原始验证产物位于未纳入Git的build目录，本记录和变更记录保留核心数字、范围与复现入口。

本轮交付的是经过上述小规模测试的修复计划。正式实现与三场景完整验收尚待按本计划执行。
