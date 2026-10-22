# 神经策略专用 hello 优化记录（2026-10-22）

**后续更新：** 神经专用的紧凑JSON已进一步换为无损VNH1/CBOR，
用户确认三场景均启用并接受spider小幅退化，见[正式合入记录](NEURAL_WIRE_INSTALL_20261022.md)。
本文保留此前版本的实际实现与验收；非NN使用原JSON、优化仅用于NN的约定继续有效。

## 用户要求与解释范围

用户明确要求：只有神经网络策略使用“hello 紧凑编码、省略空缓存增量”；
NoForward、VTDF、RTVTDF 恢复此前的报文格式。
随后明确要求仅在文档说明此额外优化，不在对比 HTML 报告或对比图添加说明。
本次不修改统计器、绘图器、HTML 生成器、模型、已有实验结果或图片。

这使后续比较成为“包含 hello 优化的神经方案”与其他方案原有编码实现的比较。
其负载和无线排队变化不能全部归因于预测模型；此前四策略共享优化的小批量结果仍按当时配置解释。
不能给旧结果重新贴上本次配置标签，也不能把旧结果与新运行混合后当作同版本实验。
旧报告中的“当前代码复跑”命令在本次修改后将采用新配置；复现此前共享优化配置时，
需要使用当时冻结的源码或二进制，不能只复用命令文字。

## 实现

| 策略编号 | 策略 | JSON 编码 | 已注册且缓存无变化 |
|---|---|---|---|
| 0 | NoForward | 四空格缩进 `dump(4)` | 发送 `CsAdded=[]`、`CsRemoved=[]`、`CsUpdate=true` |
| 1 | VTDF | 四空格缩进 `dump(4)` | 同上 |
| 2 | RTVTDF | 四空格缩进 `dump(4)` | 同上 |
| 3 | NeuralNetwork | 紧凑 `dump()`，等价 `dump(-1)` | 省略上述三个字段 |

所有策略继续保留首次全量缓存、非空增删、六维车辆状态和 `NextRsu`。
缓存不参与时不发送缓存字段。hello 频率、切换逻辑及 prepared-PIT 回程身份修正不变。

策略沿以下路径传递，默认使用 NoForward 的旧编码：

1. 圆圈主程序和方阵/蜘蛛网公共入口，将实际选中的 `rsuForwardStrategy` 设到 OBU App。
2. `VndnObuApp` 的 `RsuForwardStrategy` 枚举属性在启动时传给 `VndnObu`。
3. OBU 仅在枚举为 `NeuralNetwork` 时启用两项优化；与日志、模型文件是否存在、采样开关无关。

因此手动使用已有 `--rsu-forward-strategy=0/1/2/3` 即可切换，无须另设编码开关。
NoForward 训练采样同样恢复旧格式。模型输入字段未变，但无线时序可能变化，不能承诺训练分布完全一致。

修改文件：

- [OBU 编码](../../contrib/vndn-nn-rd/apps/vndn-obu.cc)、[OBU 配置](../../contrib/vndn-nn-rd/apps/vndn-obu.h)
- [OBU App](../../contrib/vndn-nn-rd/apps/vndn-obu-app.h)
- [圆圈入口](../../scratch/vndn-circle-simulator/vndn-circle-main.cc)、[公共地图入口](../../scratch/vndn-map-simulator-common.h)
- [策略与缓存回归测试](../../tools/experiments/tests/test_hello_strategy.py)

## 测试顺序与证据

证据目录：`build/validation/neural-only-hello-20261022/`。
本次短跑目录：`data/experiments/neural-only-hello-20261022/`。

1. 修改前 `JOBS=4 python3.8 tools/validate.py --skip-build` 通过，报告为
   `build/validation/20261022T031255.294818Z-dff2bd99/report.json`，九个 C++ 套件和五组 Python 回归均执行。
2. 新测试先提取真实 OBU 编码、RSU 解析/特征/缓存分支，覆盖四策略共44个状态。
   旧生产代码的探针编译和执行均退出0；行为要求出现33个非神经格式失败、9个空增量失败，
   加上3个配置接线失败。神经编码、所有策略缓存状态及模型特征检查通过。
   `red/` 保留有效失败；首次探针 include 路径准备错误另存，未计作行为失败。
3. 最小修改后六项新测试通过，44个状态满足要求；证据 `green/` 和 `green-tests.log`。
   这是源代码分支行为测试和静态接线保护，不冒充实际 SUMO/网络运行。
4. 修改前三场景神经短跑各有一轮通过，固定5车、30 km/h、250请求、seed63021，
   5秒预热＋10秒测量＋3.5秒排空，加载原冻结模型。
   首次 grid 短跑因同时新增测试文件触发源码一致性保护而拒收，失败记录保留；
   测试文件冻结后另起新目录重跑通过，没有改写失败 manifest。

5. 定向编译4个对象（OBU、三个场景main），链接1个主库和3个场景程序。
   阶段库的九个C++套件45例通过后，安装主库、三个程序与两份OBU导出头；
   不调用configure/waf构建、不重链测试库、不修改原waf对象或签名。
   独立复核229个冻结输入和179个受保护共享库；保留此前RSU回程修正的正确对象，
   不误用原build目录的旧RSU对象。安装备份、命令和加载来源见`plan.json`、`build.json`、`install.json`。
6. 安装后四策略×三场景共12轮短跑全部完成并通过原运行器闭合校验，耗时128.540秒。
   三场景NN前后五份CSV逐字一致：请求事件、移动事件、L3报文、额外Data提交、Data接收。
   Python决策逐项一致；C++决策仅排除运行身份`run_id`后逐项一致，包含概率及选站。
   `smoke-verification.json`保存目录、哈希及断言结果。
7. 安装后的首次统一回归与仿真并行，四项实验编排测试因仿真持有全局实验锁而失败，
   原报告`build/validation/20261022T032233.537834Z-216ca750/report.json`保留。
   没有改断言或业务源码；仿真全部结束后串行运行同一入口，45个C++及289个Python用例全部通过：
   `build/validation/20261022T032517.668025Z-315a8fff/report.json`。
   后续统一回归应与真实实验串行运行，避免全局实验锁冲突。

**当前状态：实现、安装、单元回归及三场景四策略短跑验收完成。**
这不是新一轮论文性能比较；本次没有重训模型或生成对比图/HTML报告。
神经策略前后轨迹相同的结论仅限上述固定短跑，不推广到所有运行条件。

实际L3 hello Data出站单包平均字节如下，仅用于确认编码分支实际生效：

| 场景 | NoForward | VTDF | RTVTDF | NeuralNetwork |
|---|---:|---:|---:|---:|
| circle | 303.679 | 307.597 | 307.919 | 200.464 |
| grid | 296.877 | 297.938 | 298.200 | 192.686 |
| spidermap | 314.461 | 314.774 | 314.836 | 208.219 |

不同策略的包数和缓存状态可能不同，该表不替代精确payload测试，也不作为性能优越性证据。
真实L3 CSV不保存完整payload；四策略字段内容与缓存语义由44状态源码探针验证。

## 文件与复现入口

- 原始短跑：`data/experiments/neural-only-hello-20261022/before/`、`after/`，各按场景分目录。
  前者另保留一轮被源码一致性保护拒收的grid记录；分析只使用状态为complete的轮次。
- 输入：`data/experiments/neural-only-hello-20261022/inputs/<scene>/experiment-template.json`。
- 具体执行命令：证据目录的`before-runs.json`、`before-retry-runs.json`、`after-runs.json`。
- 原冻结模型：`data/models/<scene>/tkan-lstm/retrain-quick-20261021-*-session/checkpoint.pt`，
  精确路径和SHA在`unchanged-contract.json`及各轮manifest；未修改或重新训练。
- 当前主库SHA256：`b73e0752d551e466c8f8dcec3a7015eaf98503f3f3779e6b6fb312a854da9504`。
- 小型证据及源码副本：[归档索引](records/neural-only-hello-20261022/README.md)。
  现有上层Git规则忽略records目录，它是本机文件；迁移时需显式复制，归档不含模型或完整原始数据。

单独重跑新增行为测试：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
python3.8 -m unittest discover -s tools/experiments/tests -p test_hello_strategy.py -v
```

无真实仿真运行时重跑统一回归：

```bash
export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 tools/validate.py --skip-build
```

`--skip-build`在本次安装已核验的二进制上有效；后续再次改源码时须重新编译受影响目标，
不能据此无条件跳过构建。手动仿真的策略参数和Python模型控制器用法保持原样。
