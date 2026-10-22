# 神经策略无损状态编码正式合入（2026-10-22）

## 用户决定与范围

用户明确选择：**三个场景均启用，接受spider本轮小幅退化**。
本次把[探索阶段](NEURAL_EXPLORATION_20261022.md)已验证的VNH1/CBOR发送、接收实现合入正式源码，
仅当策略为NeuralNetwork时发送新格式；NoForward、VTDF、RTVTDF继续旧JSON。
此前神经专用的空缓存增量省略保留。模型、阈值、统计及HTML/图不变，不启动完整论文批次。

用户接受spider退化是采用决定，**不改变它未通过性能门槛的实验事实**。
上一轮均值ISR60.7417→60.7167%、成功RTT301.3849→301.5705ms、固定交接成功547→545，原结果保留。
circle/grid的改善和两开发种子的局限也按探索记录保留；不能宣称模型分类准确率提高。

## 实现和安装范围

- `contrib/vndn-nn-rd/apps/vndn-obu.cc`：仅NN调用`hello_wire::Encode`，其他策略保持`dump(4)`。
- `contrib/vndn-nn-rd/apps/vndn-rsu.cc`：双格式解码，先校验再进入原状态/历史/缓存更新逻辑。
- `contrib/vndn-nn-rd/apps/vndn-hello-wire.h`：新编码辅助头，包含版本、形状、数值和缓存协议校验。
- `tools/experiments/tests/test_hello_strategy.py`：把NN协议预期升级为VNH1，保留其它策略、缓存语义和三场景接线断言。

核心源文件采用被冻结候选，NDN Data Content使用显式长度容纳二进制零字节。
六维原值与顺序、历史长度、发送频率保持；接收时序仍可能随网络变化，不能把在线历史称为逐条完全相同。
新RSU兼容旧JSON，旧RSU不识别VNH1，安装必须同时更新双端。

仅定向重编两个对象、链接一个模块库，复用已核验的其它八个对象；三场景程序及公共类布局不变。
不configure、不全量构建，所有命令`JOBS=4`。原库与原源备份在
`build/validation/neural-wire-install-20261022/before/`，索引`before.json`。
不能使用早期构建树中陈旧的OBU/RSU对象覆盖已修正的prepared-PIT处理。

## 测试与进度

修改前全回归已通过：9个C++套件45例、Python289例，均无失败/跳过。
命令：`export JOBS=4`后`python3.8 tools/validate.py --skip-build`。
原始报告：`build/validation/20261022T064408.850439Z-e0ce2a1a/report.json`。
入口日志和报告定位记录在本次build目录的`baseline/`。

实际按以下顺序执行：

1. 扩展正式hello测试，旧实现编译成功，441项细节检查中15项有效失败：
   14项要求NN采用新编码，1项要求RSU接受合法新格式。证据`tests/red-summary.json`。
   测试准备时一次证据目录不存在的错误单独留档，不计为有效RED。
2. 安装前三场景各跑一次冻结候选NN作为参考。冻结测试与源码，不在仿真期间修改。
3. 三份正式源文件与冻结候选逐字一致；同一份测试变绿，8项测试、441项细节检查全部通过。
   覆盖56个策略/缓存/数值状态和24种坏输入；没有删减断言，RED/GREEN测试SHA一致。
4. 封存3404个构建输入/保护文件身份，仅编译两个对象、链接一个库。
   阶段库实际加载到debug测试运行器，九套件45例全通过，随后备份并原子替换正式模块库。
   三场景程序、其它动态依赖、公有类头及原prepared-PIT修复保留；没有修改waf缓存签名。
5. 使用正式安装库、原运行器`--no-build`串行完成三场景×四策略12轮，全部complete并通过数据闭合。
   5车、250请求、seed63021，5秒预热＋10秒测量＋3.5秒排空，加载各场景原冻结模型。
   三个场景命令累计墙钟120.534秒；短测不作为正式性能比较。
6. `verify_smoke.py`核验12个安装后结果及12个实际参考：60份原始CSV逐字相同；
   NN另有6份决策JSONL一致，仅C++决策记录排除`run_id`，控制器记录保持原样比较。
   非NN对照原b73正式库，NN对照a930冻结候选，输入/模型/程序/其它依赖均匹配。
   校验工具自身六项行为测试先RED后GREEN；不忽略失败、未完成、重复或多余attempt。
7. 仿真全部结束后再串行执行统一回归，结果见下方最终验收记录。

这些短测验证安装和运行一致性，不重新宣称spider性能改善。

## 文件、模型与证据位置

**最终验收：正式源码、定向构建安装、12轮短测和相关统一回归均通过。**
安装后统一命令`export JOBS=4`再运行`python3.8 tools/validate.py --skip-build`，退出0；
九个C++套件45例、Python291例（2＋16＋16＋29＋228）全部通过，无失败/跳过。
报告为`build/validation/20261022T065928.532065Z-913c9547/report.json`，
定位与完整入口日志在本次证据目录的`final-regression/`。
`--skip-build`之前已完成本次双端定向编译和实际库加载核验，不是直接拿旧库验证新源码。

相对路径均以`/home/fgfxf/ndnSIM/ns-3`为根。

| 内容 | 路径 |
|---|---|
| 正式安装后的12轮原始数据 | `data/experiments/neural-wire-install-20261022/installed/{circle,grid,spidermap}/<run-id>/` |
| 新跑的三个候选NN短参考 | `data/experiments/neural-wire-install-20261022/candidate-reference/{circle,grid,spidermap}/<run-id>/` |
| 复用的九个非NN短参考 | `data/experiments/neural-only-hello-20261022/after/{circle,grid,spidermap}/<run-id>/` |
| 输入模板及请求/SUMO输入 | `data/experiments/neural-only-hello-20261022/inputs/{circle,grid,spidermap}/` |
| 本次计划、构建、安装与核验凭据 | `build/validation/neural-wire-install-20261022/` |
| 精确24轮路径、manifest及逐文件SHA | 上述目录的`smoke-verification.json` |
| 三模型精确路径和SHA | 上述目录的`plan.json`中`installed_smoke_commands`，及`source-review.json` |
| 本次小型证据与源码副本 | `docs/ai/records/neural-wire-install-20261022/` |

每轮`raw/`保留`request-events.csv`、`mobility-events.csv`、`packet-l3.csv`、
`data-attempts.csv`、`data-rx.csv`；NN另有两类决策JSONL。不能只备份图或summary。
新旧manifest未改写；复用历史参考不计作新独立重复。18轮性能结果仍在
`data/experiments/neural-explore-20261022/`，本次不覆盖旧quick数据、模型、图或出图交接包。

正式库：`build/lib/libns3-dev-vndn-nn-rd-debug.so`。

- 安装前SHA256：`b73e0752d551e466c8f8dcec3a7015eaf98503f3f3779e6b6fb312a854da9504`。
- 安装后SHA256：`f51b177817af6b4b2c83f5e9d4d3ab4f02bef02a7c192705db760b962dbb2665`。
- `install.json`保留安装当时的`installed-pending-runtime-verification`状态；
  后续运行验收由`smoke-verification.json`和最终记录承接，不能改写先前凭据。
- `installation-draft.json`及`PLAN.md`保留草案身份；实际冻结计划为`plan.json`，编译记录为`build.json`。

证据副本沿用Git忽略规则，仅是本机留档，不是异机备份或已经提交；库和对象备份仍在build目录。

## 后续手动使用

正常选用`--rsu-forward-strategy=3`即可让三个场景的NN使用新编码，无需额外编码开关。
这里的“三个场景均启用”没有改变场景默认策略：circle默认NN，grid/spidermap默认NoForward。
非NN保持编号0/1/2。手动双终端启动时，继续使用对应场景的Python控制器和匹配的模型。

以下命令自动启动圆圈仿真及原模型控制器，复跑一轮10车/6000请求的开发验证；
使用独立输出根、自动生成新run目录，不训练、不构建、不覆盖历史结果：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3.8 tools/experiments/run_experiment.py \
  --config data/experiments/retrain-quick-20261021/inputs/test/circle/baseline/52001/experiment-template.json \
  --output-root data/experiments/neural-wire-manual-circle \
  --block-id manual-circle-vnh1 --strategies 3 \
  --model-file data/models/circle/tkan-lstm/retrain-quick-20261021-22109572fde7474a-session/checkpoint.pt \
  --require-formal-contract --validation-only --no-build --timeout 900 --python /usr/bin/python3.8
```

grid/spidermap的精确模型及四策略短测命令都保存在上述`plan.json`。
同一机器串行运行，避免SUMO/Gym端口与实验锁冲突。不要再次调用旧探索overlay入口，
它封存的是合入前的源码身份，正式合入后拒绝该旧身份是正确行为。
本次已定向编译并验证源码与正式库对应；以后继续修改C++，不能只凭`--no-build`跳过必要构建。

## 结论边界

这是无损编码的工程合入，收益来自降低报文和网络竞争成本，不是重新训练模型。
原18轮中circle、grid改善，spider小幅退化；两个开发种子不足以证明泛化或统计显著性。
仅NN享有额外编码优化，不能把相对其它策略的全部收益归因于神经网络预测能力。
用户已接受该采用范围；机制继续只记入Markdown文档，没有改对比HTML、论文图或统计口径。
