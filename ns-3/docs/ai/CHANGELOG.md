# AI 变更记录

供后续 AI 接续工作。每个逻辑任务追加一条，记录实际执行结果；不要求逐次编辑都写一条。
历史记录保留。若后续修正之前的结论，新条目指出被修正的条目及原因。
完整日志可保存在忽略的 `build/validation/`，但关键结论、命令和失败原因必须在本文留存。

## 记录模板

```text
日期 / 任务：
背景与目的：
起始版本 / 已有工作区差异：
涉及文件与行为变化：
修改前基线（命令、退出码、实际结果）：
测试先行证据（测试文件、运行命令、预期失败、实际失败原因）：
修改后验证（命令、退出码、断言与覆盖）：
实验配置 / 种子 / 模型 / 数据来源（适用时）：
日志或报告路径：
未覆盖范围 / 已知失败 / 后续事项：
结论：通过（注明范围） / 未通过 / 阻塞
```

## 2026-10-18：初始化 AI 开发规范与单元回归入口

### 背景与决定

- 用户确认采用测试先行、修改后相关测试通过、每次修改更新 AI 文档的流程。
- 用户澄清当前研究方案已完成：离线训练深度神经网络，加载模型推理，经 ns3-gym 将结果交给 C++。
  它不是强化学习；reward 恒为 0 不作为缺陷处理。
- 开始时 Git HEAD 为 `e1d0bd6`（添加更多场景），工作区干净。
- 背景来自本次可见聊天、当前代码和 Git 近期历史；未访问其他历史聊天。

### 涉及文件与行为

- 新增根 `AGENTS.md`、`ns-3/AGENTS.md`：项目定位、目录边界、测试先行、完成条件、变更记录和 `JOBS=4` 约束。
- 新增 `docs/ai/PROJECT.md`：主/旧版本职责、三个场景、回程路由与模型训练推理、关键代码导航。
- 新增 `docs/ai/VALIDATION.md`：本机配置、验收入口、手动诊断、三场景验证要求及证据边界。
- 新增本记录文件，建立持续维护的格式。
- 新增 `tools/validate.py`：构建测试运行器、运行两个研究 C++ 套件和 circle Python 测试，生成日志与 JSON 报告。
  明确拒绝未启用测试、失败、跳过、零测试、证据缺失及超时；子进程固定 `JOBS=4`，构建显式 `-j 4`。
- 新增 `tools/tests/test_validate.py`：临时环境下验证入口的成功、失败、跳过、空测试、缺解释器、超时及进程收敛行为。
- 本地重新 configure 将 `ENABLE_TESTS=False` 改为 `True`；保留 debug、MPI、examples、sudo、Python 3.8、Boost Python 38。
  缓存与构建产物受现有 Git 忽略规则管理；新检出环境仍需配置。不修改研究算法、场景源码或 `ns-3_old`。

### 修改前基线

1. `python3.8 -m unittest discover -s contrib/vndn-nn-rd/ai-training/circle/tests -p 'test_*.py' -v`
   → exit 0，2 项通过（时序窗口/运行隔离，模型输出/反向传播）。
2. C++ 测试初始被本地构建配置禁用，先记录不可运行，不记为通过。
   按 `VALIDATION.md` 的本机 configure 命令启用测试 → exit 0。
3. `export JOBS=4` 后 `./waf build -j 4 --targets=test-runner`
   → exit 0，首次启用测试后的构建完成（约 49.6 秒）。
4. `python3.8 test.py --nowaf --suite=vndn-rsu-forwarding-policy`
   和 `python3.8 test.py --nowaf --suite=vndn-neural-return-selection`
   → 各 exit 0，各 1 个套件 PASS，0 skipped / failed / crashed；实际命令附 `--xml` 保存证据。

### 测试先行与修改后验证

- 验收工具先写 `tools/tests/test_validate.py`，运行
  `python3.8 -m unittest discover -s tools/tests -p 'test_validate.py' -v`
  → exit 1，原因是新入口 `validate.py` 尚未实现。这是新增工具缺失的预期红灯。
- 实现入口后同命令 → exit 0，11 项行为测试通过；其中还断言了忽略 SIGTERM 的子孙在超时后被终止。
- 真实运行 `export JOBS=4` 后 `python3.8 tools/validate.py`
  → exit 0；定向构建通过，两个 C++ 套件均实际执行并 PASS，Python 2 项通过，无跳过。
- 文档事实与相对路径检查、全部新增文件空白错误检查：通过。纯文档变更没有编写无意义的行为测试。

### 证据位置

- 本机配置/首次构建/两个套件基线日志：`build/validation/bootstrap-20261018/`。
  初次手动使用了带 `.xml` 的 `--xml` 参数，test.py 再附扩展名，文件名为 `rsu.xml.xml` / `neural.xml.xml`。
- 统一入口真实验收：
  `build/validation/20261018T152022.818154Z-fb930a43/report.json`。
  该目录名采用 UTC；本文日期按用户 Asia/Shanghai 时区记录。
- 机器报告不随 Git 提交；本文保留可共享的执行命令与结果摘要。

### 结论与覆盖边界

初始化所涉及的文档与验收工具验证通过，现有相关单元回归通过。
本任务未修改实验协议，因此未运行三场景仿真、重新训练模型或重做科研对照实验。
当前工具不是三场景端到端自动验收；现有单元测试未证明实际切换时的 PIT 时序、Data 交付和性能优势。
今后修改这些行为，须按验证指南补充相应场景断言与记录，不能凭本次绿灯省略。

## 2026-10-18：记录实验期间避免重复 configure 的约束

- 用户要求：跑实验时尽可能不要运行 `./waf configure`，避免重新配置引发大批量重新编译。
- 修改文件：根 `AGENTS.md`、`ns-3/AGENTS.md`、`docs/ai/VALIDATION.md` 及本记录。
- 规则：日常实验、重复仿真和回归测试复用已有配置，按需增量构建；只有首次初始化、配置缺失或确需调整构建选项/依赖时才重新配置，并记录原因。
- 验证指南将现有 configure 命令明确标为首次启用测试的参考，不作为每次实验步骤。
- 修改前工作区干净；核对现有文档后补充规则。修改后检查文档差异、相对链接及 `git diff --check`，通过。
- 本次仅修改文档，未运行 configure、编译、测试或仿真；无需新增行为测试。

## 2026-10-19：补齐方阵与蜘蛛网的训练和推理验证

### 背景与范围

- 用户批准前一轮实施计划：`grid/`、`spidermap/` 各自包含完整训练脚本、tests、README 和 Python 3.8 依赖，仅共享 `efficient_kan`；沿用现有 TKAN-LSTM 网络。
- 用户选择允许排除无效数据，但必须报告丢弃量，并阻止窗口跨过无效断点。训练窗口目标仍须覆盖实际基站 0–6，避免缺类模型和无穷类别权重。
- 本次验收到临时数据上的小规模训练、保存 `.pt`、实际推理加载函数重载与概率检查；不采集正式实验数据、不训练正式模型、不重做无线仿真。
- 执行期间已有“避免重复 configure”的文档修改进入提交 `167017a`；保留这些约束。没有修改 C++、旧项目或历史模型数据。

### 测试先行证据

- 圆圈基线：`OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 -m unittest discover -s contrib/vndn-nn-rd/ai-training/circle/tests -p 'test_*.py' -v` → exit 0，2 项通过。
- 新训练行为测试先临时对既有 circle 实现执行 `-k test_invalid_label_is_removed_without_joining_segments`：两个场景各 exit 1，断言 `7 != 6`。旧实现保留无效 -1 行，与要求的排除/切断行为不符；不是模块导入失败。
- 推理基线：既有 circle 临时 checkpoint 可保存、重载并输出有限、非负、和为 1 的概率。随后先写无效归一化参数与特征顺序测试，旧实现未抛出预期 ValueError，exit 1。
- 验收工具基线 11 项通过；先扩展新场景失败传播测试，旧入口出现 14 个预期失败断言：缺失/零项/跳过/失败的新套件仍返回成功，且没有执行全部独立步骤。

### 实现与验证记录

- 新增 `ai-training/grid/` 和 `ai-training/spidermap/` 下各自的 `train_tkan_lstm.py`、`requirements-python38.txt`、`README.md` 和训练测试。数据路径分别是 `data/grid-vanet-test/<日期>`、`data/fgfxf-spider-map/<日期>`；模型分别输出到 `data/models/grid/tkan-lstm/` 和 `data/models/spidermap/tkan-lstm/`。
- 新训练器在原始数值精度下判断非法标签，将无效行作为断点保留片段边界；检查训练窗口七类覆盖，记录逐文件筛选、丢弃原因、run 清单、分组窗口和类计数。输入来源不能仅由同为七类标签证明，摘要与 README 明确这一限制。
- 修改三个 `scratch/vndn-*-simulator/*-tkan-gym.py`：连接 Gym 前检查场景、完整标签、10×6 输入契约和归一化参数；新场景 wrapper 可离线导入调用。模型权重结构不变，circle 旧二参数加载接口与既有模型保留兼容性。
- 新增 `ai-training/tests/test_tkan_inference.py`。测试最初在 `scratch/tests` 建立红灯，后发现 waf 会把 scratch 所有子目录注册为 C++ 程序，遂迁移并移除本次临时目录，避免修改 wscript 或引入空程序目标。
- 扩展 `tools/validate.py` 与 `tools/tests/test_validate.py`：四个 Python 测试组各自独立进程、日志与证据；新增场景缺失、零项、跳过或失败均让总验收失败。更新 `PROJECT.md` 和 `VALIDATION.md`。
- 交叉审查发现从 circle 沿用的损失汇总问题：带类别权重的交叉熵均值不能再简单按 batch 样本数平均。固定 4 个样本，batch=1/2/4 得到的旧 val_loss 分别为 1.2896319/2.1229651/3.1646318；整集正确值为 3.1646318。两个新训练器增加批大小无关的回归测试，训练/验证历史损失改按目标类别权重总和汇总；不改变每批优化目标和按准确率选最佳模型的规则。本次没有修改原 circle 训练器。

### 修改后结果

1. 两个新训练目录各执行 `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 -m unittest discover -s contrib/vndn-nn-rd/ai-training/<grid或spidermap>/tests -p 'test_*.py' -v` → 各 exit 0，15 项通过。
   每个场景使用两次合成 run、各 45 行，每 run 排除一个 -1 行；每个 split 恰有 26 个窗口。训练 1 epoch，seed=20261018、CPU、hidden=4、KAN grid=3、spline order=2、batch=8、stride=1；生成 `.pt`/历史/摘要，并经对应场景真实 loader 重载，验证候选重排后的概率与模型输出一致、有限、非负且和为 1。临时产物自动清理。
2. `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 -m unittest discover -s contrib/vndn-nn-rd/ai-training/tests -p 'test_tkan_inference.py' -v` → exit 0，10 项通过。
   额外重载既有 circle 模型 `data/models/circle/tkan-lstm/20260813-202805/tkan-lstm-circle-noforward-20260813-202805.pt` 成功，候选 `[1,0]` 下概率有限、非负且和为 1。
3. `python3.8 -m unittest discover -s tools/tests -p 'test_validate.py' -v` → exit 0，16 项行为测试通过，包括新套件四种失败状态和进程隔离。
4. `export JOBS=4 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1` 后运行 `python3.8 tools/validate.py` → exit 0。
   定向构建、两个 C++ 套件、circle 2 项、grid 15 项、spidermap 15 项、inference 10 项全部通过，无跳过。
   完整报告：`build/validation/20261018T160510.889894Z-833471aa/report.json`（目录采用 UTC，用户本地日期为 2026-10-19）。
5. 指标审查后，两场景先执行新测试 `-k test_weighted_validation_loss` → 各 exit 1，复现固定验证集因 batch 划分不同而得到不同损失。修正按权重汇总后，两目录各 16 项通过。
   再运行同一统一验收命令 → exit 0；两个 C++ 套件、circle 2 项、grid 16 项、spidermap 16 项、inference 10 项全部通过（44 项 Python 回归，无跳过）。最终报告：`build/validation/20261018T160850.504870Z-2d6a6e2b/report.json`。
- 另行通过的验收工具行为测试为 16 项，合计本次最终验证包含 60 项 Python 测试及 2 个 C++ 套件。
- 全部 17 个修改/新增文件的空白检查、33 个文档相对链接和 21 个 bash 示例语法检查通过；`git diff --check` 通过。
- 本次没有运行 configure；统一验收前后 `build/c4che/_cache.py` 修改时间一致，waf 使用 `JOBS=4` 和 `-j 4`。

### 结论与后续使用

训练代码、推理兼容检查及相关回归通过。新增 README 提供采样、训练和双终端推理命令；控制器一次服务一轮仿真，现有批量脚本默认 NoForward，不会自动重启控制器。
真实 grid / spidermap 采样数据尚未生成，本次没有产出用于论文实验的正式模型，也没有验证真实数据泛化或无线切换收益。下一步由用户完成各场景的 NoForward 采样后，通过显式 `--data-root` 开始正式训练。

## 2026-10-19：记录旧论文实验与八张参考图的处理流程

### 范围与修改前证据

- 用户要求参考 `ns-3_old/旧的实验效果图/` 及其 `论文出图旧数据和代码-2026-10-18/` 归档，为后续 AI 接续工作建立记录。
- 按用户明确选择，以顶层八张 SVG 为参考：三张四算法 RTT 3D 图、三张三算法箱线图、总流量柱状图、KAN 混淆矩阵；归档其他版本用于溯源。
- 开始时 `git status --short` 无已有未提交修改。旧目录只读；本次是文档任务，依据 AGENTS 的纯文档规则检查事实、链接与差异，不编写行为测试或触发构建。
- 分别审查 RTT、流量和采样/训练来源，并交叉检查初稿。确认脚本中存在改名、保存语句注释、显示范围差异，不能将现存中间代码称为原图生成时的冻结版本。

### 文档变化

- 新增 [LEGACY_EXPERIMENTS.md](LEGACY_EXPERIMENTS.md)：记录八图入口、三场景四算法固定运行清单、原始字段、RTT 的超时记录语义、按行数平均、箱线图阈值/显示范围、流量筛选及单位、旧 KAN 训练和全样本混淆矩阵、旧/新协议差异及后续证据缺口。
- 在 `ns-3/AGENTS.md` 和 `docs/ai/PROJECT.md` 加入入口，提示后续 AI 不把旧筛选规则、旧 KAN/offload 流程或旧实验数值直接套用为当前重写版验收。
- 保留用户研究意图，分别标明本地代码可证事实、此次补充复算指标与未闭合的事件/模型对应关系；没有改写论文结论或修改历史数据。

### 核对与结果

- 标准库 `csv/ast/hashlib` 内联只读核对，exit 0：60 个 RTT CSV 与 12 个 trace 均存在；九组箱线图的原始数/保留数/中位数/P99 断言全部通过；12 个总流量值按旧公式复算与顶层 SVG 两位小数标注全部一致。
- 独立核对 39 个矩阵输入文件：10385 行，过滤异常标签 58 行，剩 10327 行，各类别计数吻合，标签 4 无样本；没有加载 checkpoint 重算图中 97.15%。
- SHA256 核对：六张 RTT SVG 和混淆矩阵与归档同名副本逐字节一致；总流量图无同名归档副本，以输入和数值对应验证。归档切换时段流量版本的另外 12 个标值也已按其独立公式复算吻合。
- 对五条不完整 trace 末行显式计数；记录各文件时间范围，不将截断终点当作仿真实际结束时间。SVG 标签/坐标与脚本核对还发现蜘蛛网 box 的参考图约 1500 ms 上界与当前脚本 1390 ms 上界不同，已记录版本差异。
- 三个方向的初稿复核完成；修正旧圆圈“输出目录不同”与“SUMO资源不同”的混淆，并将分布结论限定到本次复算的 P99。
- 最终文档相对链接、引用定义、空白与 `git diff --check` 检查通过。未执行旧出图脚本、旧模型反序列化、正式训练、仿真、waf 或 configure。

本次交付是可追溯的历史工作记录；不认证当前项目性能，不声称已完整复现八张图或恢复历史每轮命令、种子及 checkpoint 对应关系。

## 2026-10-20：制定导师新增三自变量、五指标的实验与出图方案

### 用户确认及范围

- 任务仅输出学术实验设计文档。沿用当前三场景、四算法，规划 Interest 数量、速度、车辆数三个扫描，以及额外 Data 副本、ISR、平均 RTT、网络负载和控制负载五指标。
- 用户确认 Interest 数量为固定时窗内全网首次业务请求数；车辆数主实验固定每车发包频率，补充固定全网请求量对照；网络/控制主图使用累计发送 Mbit，附每请求字节成本。
- 用户修正最初建议：二次转发合并所有额外业务 Data 副本，包括预测双路径；控制负载按代码中的新增控制协议理解，不再限于导师原话 search/find/update 三个名称。
- 修改前 `git status --short` 干净。读取项目约定和旧实验记录，分工只读检查指标、场景参数/几何及统计方法；本次没有修改实现或运行仿真。

### 文档内容

- 新增 [EXPERIMENT_COMPARISON_PLAN.md](EXPERIMENT_COMPARISON_PLAN.md)，规划15张三场景组合图、45个面板，给出候选参数、统一请求集合/测量与排空时段、五指标公式、分类规则、配对重复和置信区间、产物契约及后续测试先行步骤。
- 主控制指标纳入 hello 双向、P2P握手、查询/响应、neural-route/neural-pit；承载完整业务 Data 的 forward 单列混合封装，网络总量完整计入，附拆封装字节及宽口径审计列。没有遗漏 Proposed 更新成本，也没有人工将 Naive 控制负载设为零。
- 记录当前日志和参数能力缺口：两列 RTT 混含超时、生成分母/终态不全、缺副本身份及按名称的网络发送日志、无精确请求预算/速度/车辆数 CLI、Stop并非排空、SUMO端口3400固定。
- 根据实际代码区分名义频率与实发数，指出 `--i` 实际为TraCI同步间隔；以道路尺度说明必须延长路线并预实验冻结时长。没有将候选参数或拟议接口写成现成功能。
- 明确模拟RTT未显式包含Python推理/IPC墙钟耗时，Gym宿主机通信和离线训练不属于模拟网络负载；可另做部署时延敏感性实验。
- 更新 `ns-3/AGENTS.md`、`docs/ai/PROJECT.md` 的导航和指标约束，保留旧实验记录。

### 核查与边界

- 查询 ns-3、SUMO、ndnSIM 官方文档、NIST置信区间说明及Efron bootstrap原论文，文内就近链接方法依据；本地代码决定当前能力与统计分类，外部资料不代替本仓库验证。
- 三个方向交叉复核初稿：修正种子块内/块间作用域、pooled成功RTT的配对差及t区间适用范围；补充非线上测量标记、OBU网络层重复到达记录、发送设备接受不等于目标收到、SUMO端口隔离等细节。
- 标准库内联检查 exit 0：文档本地链接/空白通过；候选请求预算及图表数量核算通过；3600直接扫描、3120复用基准、960补充、4080总规模及252预实验轮数均符合公式。这些是规划轮数，不是已执行轮数。
- 最终四份文档的链接/空白和 `git diff --check` 检查通过。纯文档修改按AGENTS不编写行为测试，未执行waf、configure、正式采样、训练或结果出图。

后续实施须先补采集与计数验收，再独立预实验并冻结配置，最后正式配对比较；本次不声称五指标已可由现有输出严格计算。

## 2026-10-20：实现不改底层的实验采集与逐轮汇总

### 批准范围与实现

- 用户在影响范围审查后批准开始修改，采用不改底层的范围。起始 HEAD 为 `b6bff22`，工作区干净。
  没有修改 `src/`、旧项目、既有训练器、历史数据或模型；全程复用配置，所有 waf/间接构建均 `JOBS=4`、显式 `-j 4`，没有运行 configure。
- 新增 `helper/vndn-experiment-config.{h,cc}` 与三场景 `--experiment-config`：
  校验实际 SUMO 路线、稳定车辆 ID、唯一请求序号、纳秒计划、种子、测量/排空窗口；
  拒绝复用非空输出目录，保存有效配置及仿真完成凭证。
- 新增 `helper/vndn-experiment-recorder.{h,cc}`，OBU 在 `[t0,t1)` 按计划生成，
  到 t1 停发但保留接收至 t2；记录 GENERATED、唯一 DATA/TIMEOUT/NACK/STOPPED 及诊断事件。
  迟到 Data 若尚无终态，先在 deadline 补记 TIMEOUT，再记录 LATE_DATA；失败终态后的 Data 不伪装成重复成功。
  TraCI 提供实际速度/位置、关联变化和 t0/t2 样本。应用 t2 关闭，Simulator t2+1ns 结束。
- RSU/Router 增加应用额外 Data 提交观察：预测增加的返回分支、补救转送、同一无线方向重复提交。
  未知父关系记 `-`，无法可靠映射的目标 node 记 -1；不改路由决策、报文内容或底层发送行为。
- 新增 `helper/vndn-l3-experiment-tracer.{h,cc}`：订阅现有 L3 出站回调并筛选 NetDeviceTransport face，
  在 `[t0,t2)` 按语义累计 Interest/Data 编码长度，另记 Nack 次数及网络入 Data 诊断。
  hello、P2P握手、search/find、neural-route/neural-pit 为控制子集；
  携带完整 Data 的 relay 封装计网络总量，内外层长度只作分解，不重复加总。
- 新增 `tools/experiments/`：独立显式车辆/长路线及精确 K 生成器、串行策略运行器、测试控制器、严格逐轮汇总。
  保留失败证据，管理本轮 Gym/SUMO 进程，冻结输入/模型/源码和 traces 配置（含 RSU settings.xml）；
  保存运行后二进制及相关库/构建缓存、日志与产物哈希。完整性检查失败时不标 complete。
  生成器考虑 `departPos=free` 可能跳过首条道路，按最坏剩余路线长度补足余量。
- 模块 wscript 注册三个新测试套件，并使模块构建依赖新头文件导出，支持不 configure 的定向增量构建。
  `tools/validate.py` 纳入新 C++/Python 套件；验收工具的 `/proc` 测试夹具容忍读取时进程恰好退出的竞态。
- 新增 [EXPERIMENT_COLLECTION.md](EXPERIMENT_COLLECTION.md)，同步项目入口、PROJECT、VALIDATION 与原出图方案。
  明确当前支持 12 张主要图与 3 张应用提交机制图，工具本身不运行正式扫描或绘图。

### 测试先行证据

统一日志目录为 `build/validation/experiment-implementation/`（下文简写 `E/`）。

1. 修改前 `export JOBS=4; python3.8 tools/validate.py` → exit 0：
   原两个 C++ 套件、44 项 Python 测试通过；
   `build/validation/20261020T132627.645857Z-4b46025e/report.json` 保存基线。
   验收工具原 16 项测试通过，见 `E/validator-baseline.log`。
2. 新 C++ 测试先编译可运行的接口桩，再执行
   `python3.8 test.py --nowaf --suite=<套件> --xml=<证据前缀>` → exit 1：
   recorder 没有生成/终态记录，config 未加载车辆/窗口/种子，L3 分类和编码长度缺失。
   证据为 `E/vndn-experiment-{recorder,config}-red.xml`、`E/vndn-l3-experiment-tracer-red.xml`。
   早期头文件导出和旧 ns-3 Schedule 接口的编译问题不计作行为红灯。
3. 后续边界先红后绿：
   `E/config-seed-red.xml` 记录非空输出目录未拒绝、超出 MRG32k3a 合法 seed；
   `E/recorder-additional-red.xml` 记录迟到 Data 无终态；
   `E/recorder-csv-red.xml` 记录失败后 Data 错误分类及缺失父标记。
   修复后对应 `config-green.xml`、`recorder-green.xml` 通过。
4. L3 测试在两个真实节点的网络 face 上发送 10 KB Data，检验半开窗口、最后不足周期的落盘、
   逻辑 L3 计量不按分片倍增及原编码字节不变；`E/l3-green-1.xml` 通过。
5. Python 生成、运行和汇总最初以行为桩验证预期失败后实现，早期细节保留于工具调用记录。
   后续 `E/generator-depart-position-red.log` 明确捕获临界路线扣除首路段后过短；
   `generator-depart-position-green.log` 的 5 项生成器测试通过。
   `E/tool-integrity-red.log` 明确捕获 trace 配置变化漏检、完成计数/额外行截断漏检、
   deadline 同时刻 TIMEOUT 后 Data 诊断不兼容；修复后 `tool-integrity-green.log` 的 36 项测试通过。
6. 验收入口的新覆盖断言先失败，见 `E/validator-red.log`；修复后 17 项通过。
   一次并行 test.py 调用发生临时目录碰撞，随后改为串行重跑；碰撞不计入功能红灯或成功证据。

### 修改后统一回归

- `export JOBS=4; ./waf build -j 4 --targets=test-runner,vndn-circle-simulator,vndn-grid-simulator,vndn-spidermap-simulator`
  → exit 0，`E/integration-build.log`。
- `export JOBS=4; python3.8 tools/validate.py` → exit 0，
  **5 个 C++ 套件（9 个 case）、80 项 Python 测试全部通过，无跳过**。
  最终报告：`build/validation/20261020T135934.047802Z-a1c7fbef/report.json`。
  Python 为圆圈2、方阵16、蜘蛛网16、推理10、实验工具36。
- `python3.8 -m unittest discover -s tools/tests -p test_validate.py -v`
  → exit 0，17 项通过，`E/validator-final.log`。
- 最终 `git diff --check`、6份文档的63个本地链接及空白检查通过；
  `src/`、旧项目、训练器和数据目录的已跟踪文件无差异，未遗留本次仿真/SUMO进程。

### 三场景真实采集验收

输入保存在 `E/inputs/{circle,grid,spidermap}/`。每场景两车、36 请求、
测量 `[5,23)` 秒、排空至 26.5 秒；圆圈设置100 km/h、另两场景50 km/h。
种子元组为 rng_seed=1、rng_run=1、sumo_seed=1、srand_seed=1。
由生成器创建输入后，验收专用请求计划将序号改为 `17,23,…,119`，
检验真实 OBU 是否原样执行非连续序号；此修改发生在 runner 冻结/哈希之前，未修改原 traces。

每场景执行以下命令（`SCENE` 分别取三个场景）：

```bash
export JOBS=4
python3.8 tools/experiments/run_experiment.py \
  --config build/validation/experiment-implementation/inputs/SCENE/experiment-template.json \
  --strategies 0,1,2,3 --test-controller --block-id integration-SCENE \
  --output-root build/validation/experiment-implementation/runs --timeout 120
```

- 三组均 exit 0，共 **12 轮 complete**；另有圆圈 NoForward 先导1轮 complete。
  每轮恰好36 GENERATED、36互斥终态；请求 ID/时刻与冻结计划一致，t0/t2真实样本、t2退出及t2+1ns完成均核对。
  同一场景四算法的输入哈希、来源哈希一致；网络类别和控制子集闭合、原始文件哈希复核通过。
- 每轮测量窗实际交接次数：圆圈5、方阵2、蜘蛛网3（均为两车合计）。
  圆圈 VTDF/RTVTDF 捕获2/3次 REACTIVE_RELAY，方阵6/5次，蜘蛛网 RTVTDF 3次；
  三场景测试控制器分别捕获35、28、33次 PREDICTIVE_EXTRA。这些是日志机制验收，不是算法优劣结论。
- `python3.8 E/audit_integration.py`（将 E 展开为上述目录）→ exit 0，
  `E/integration-report.json` 保存12轮具体目录、断言范围和计数；
  `circle-block.log`、`grid-block.log`、`spidermap-block.log` 保存 runner 结果。
  每轮 `manifest.json`、`run-metrics.json/csv`、`raw/` 均保留。
  圆圈块运行后补强了工具的 XML 来源/完成计数校验，最终审计使用补强后的汇总器重新验证全部12轮。
- 另用现有圆圈 checkpoint
  `data/models/circle/tkan-lstm/20260813-202805/tkan-lstm-circle-noforward-20260813-202805.pt`
  执行策略3，使用同一输入、`--model-file`、block `integration-circle-real-model`，
  去掉 `--test-controller` → exit 0。run 为 `20261020T135812.073022Z-0fded453`；
  C++ 与真实 Python 控制器均 exit 0，35次决策后 done，36请求闭合，捕获2次预测额外提交。
  模型 SHA256 为 `ab0015243af833550a3486be858aeb07d57c1b86b65d390c897e0cf9316918ca`；没有训练或改写权重。
- 无实验配置的三个旧入口分别运行 `--s=6 --rsu-forward-strategy=0 --sumo-gui=0 --save-data=0 --pcap=0 --log=0`
  和同一组显式种子 → 均 exit 0；`E/legacy-report.json` 及 `legacy-*/simulation.log` 保存命令与结果。
  这是旧入口短时兼容性检查，不代替长期默认实验或原训练采样验收。

### 覆盖边界与结论

上述单元及集成采集验收通过。网络/控制指标是 **NDN L3 出站 Interest/Data 字节**，
额外 Data 是 **应用提交尝试数**；未实现设备接受、LP分片/MAC开销或全部隐式 NFD 副本身份。
普通 Nack 单列次数；hello 等共同移动控制不因算法名称 Naive 而人工清零。

三场景四算法矩阵使用均匀概率测试控制器且全部标记 `validation_only=true`，
不能当作 TKAN-LSTM 效果。圆圈真实模型单轮也只是接口/采集验证；方阵和蜘蛛网没有正式模型效果验收。
实际 smoke 覆盖了预测额外与补救分支；`REPEATED_SUBMIT` 规则有单元测试，但本次真实场景没有触发该分支。
没有开展正式参数扫描、独立重复、置信区间、论文绘图、模型泛化或部署推理时延实验。
后续按采集指南和原设计开展独立预实验，再冻结正式比较条件。

## 2026-10-20：四策略采集回归与真实神经模型效果核查

### 目的与范围

用户要求检查新增采集是否破坏原四策略，尤其神经策略，并检验神经效果是否不差于转发策略。
起始 HEAD 为 `cc31e88`，工作区干净；修改前基线为 `b6bff22`。
新增 [完整核查记录](STRATEGY_REGRESSION_20261020.md)，在主项目 `AGENTS.md` 加入入口。
本轮没有修改生产源码、策略、模型、原始 traces、底层文件或 `ns-3_old`。
隔离构建、运行脚本、行为测试、原始数据与分析报告位于
`build/validation/strategy-regression-20261020/`（下称 `R/`），未混入源码。

### 测试先行与执行证据

- 静态差异确认底层、回程选择规则、训练和控制器未被采集提交改写。
  从旧提交导出完整研究模块/入口，以旧公开头覆盖层独立重编7个模块源和3个入口，
  复用未改动依赖；全部编译/链接 exit 0，`ldd` 确认载入隔离旧模块。
  见 `baseline/build-plan.json`、`build-report.json`。编译并行上限4，未 configure。
- `export JOBS=4` 后分别运行
  `python3.8 test.py --nowaf --suite=vndn-rsu-forwarding-policy`、
  `python3.8 test.py --nowaf --suite=vndn-neural-return-selection`
  → 均 exit 0，两个套件通过。日志为 `current-policy-unit.log`、`current-neural-unit.log`。
- 验收分析/输入裁剪脚本11项行为测试、固定输入质量汇总4项、交付阶段诊断10项，
  先确认目标行为缺失的断言失败，再实现、全部通过。
  红/绿日志分别位于 `R/`、`R/quality-analysis/`、`R/model-audit/`。
  范围包括正确请求分母/成功RTT、尾部终止、配对差异/未完成拒绝、
  原输入保护、实际目标OBU匹配、截止时间与出站Face边界。
- 原模式 `run_legacy_pair.py`：两版本分别覆盖圆圈原1车80s、方阵原2车40s、
  蜘蛛网固定XML前2车20s；名义40Hz，四种种子均1。
  圆圈神经用现有真实模型；方阵/蜘蛛网用均匀控制器，仅验接口与协议。
- 原20车蜘蛛网40s基线策略0在300s墙钟限制内未完成，exit 1；
  保留 `runs/incomplete-20cars-40s-baseline-spidermap-s0-seed1/`，
  未当成通过。两车裁剪只在独立副本，选择与算法结果无关。
- `python3.8 R/analyze_pairs.py` → exit 0，`analysis.json` 为12/12对完整且一致：
  实际输入、逐事件协议、控制器、72份训练/RTT/统计/L3产物均一致。
  圆圈真实模型1711次推理输出完全一致；两个版本神经满足率均1585/1719（92.20%），
  VTDF/RTVTDF均为1606/1719、1608/1719，原差距不是新增采集造成。
- `export JOBS=4` 后执行 `python3.8 R/quality-analysis/run_quality.py --execute`
  → exit 0；3种子×3策略共9轮全部完成。
  每轮2车、设定100km/h、600请求、测量 `[5,35)`、排空38.5s。
  同种子实际生成Name/节点/纳秒时间逐项相同，9轮生产源码快照一致，
  见 `quality-analysis/provenance-verification.json`。
  `quality-summary.json/csv`、`aggregate.json` 保存所有结果，不挑选种子。
- 真实模型使用原圆圈 checkpoint `20260813-202805`，
  SHA256 `ab0015243af833550a3486be858aeb07d57c1b86b65d390c897e0cf9316918ca`。
  未训练、调参或改写权重。三轮累计每策略1800请求：
  VTDF成功1494（83.00%）、RTVTDF成功1489（82.72%）、Neural成功1359（75.50%）。
  合并成功请求平均RTT分别192.051、179.764、178.904ms。
- 质量首轮 waf 只重编生成版本信息并重链接，发生在24轮A/B全部结束之后；
  不是重新 configure。`dependency-build-transition.json` 记录时间/哈希边界。
  实验中采集的126库快照与结束后复核一致，不回填成A/B事前哈希。

### 发现、限制与结论

真实模型原历史验证窗口top-1为100%，但旧CSV按结果回调写入，而在线输入按hello时间排列；
这项历史语义差异早于采集修改，100%离线数值不能证明在线交付质量。
原模式119个神经超时中107个已回到当时服务RSU的应用回调，不能全归因预测错误。
新固定计划441个神经超时中436个有RSU无线L3 OUT而目标OBU无截止前L3 IN；
其中422个出站站点覆盖当时记录的服务站。见 `model-audit/raw-delivery-quality*.json`。
这只定位观测阶段，尚未证明具体无线/LP/重组原因或完整模型准确率。

**行为回归验收通过；“神经交付效果不差于转发策略”未达到，本轮测试不等于修复旧性能问题。**
三个种子神经满足率均低于两种转发策略。方阵/蜘蛛网没有真实模型效果验收；
蜘蛛网均匀控制器前后均0 DATA，只能说明协议一致，不是交付合格。
未完成原20车蜘蛛网负载验收或论文级参数扫描/统计非劣性检验。
下一步先定位少数失败请求的RSU无线出口至OBU入口，再评估训练/在线输入一致性；
未经必要失败复现与授权，不擅自改底层、增加兜底或以改统计口径提高结果。

## 2026-10-20：神经回程未交付定位与经过小规模测试的修复计划

用户要求继续排查“已有出站记录但目标车辆未收到”，优先检查outface，
并在提供修复计划前完成小规模测试。起始HEAD为`86ef39c`，工作区干净。
新增[完整定位与修复计划](NEURAL_DELIVERY_FIX_PLAN_20261020.md)，更新`AGENTS.md`入口。
本轮正式树只修改文档；未改生产源码、模型、历史数据或`ns-3_old`。
候选源、补丁、测试、隔离构建和运行证据位于
`build/validation/neural-delivery-diagnosis-20261020/`（下称`R/`）。

### 失败证据与候选边界

- 固定圆圈seed1请求`/com/baidu/www/userid/2/%FE%08`，OBU2、当时RSU1，
  已存在无线Face257和预备PIT。抓包确认真实发送，不能归因于缺outface。
- Router迟到重复Interest相隔14.398μs，默认BestRoute在10ms内抑制应用投递，
  但网络in-record已经重建。服务器Data先自动无目标标签返回，
  消耗RSU PIT；正确神经副本随后以unsolicited丢弃。
- 首副本5片广播，目标只收到index4。隔离Router候选清理网络in-record后，
  首片单播、尾片仍广播，目标收到0–3而缺4；所以单改Router不能作为完整修复。
- 第二候选只在隔离副本修改`generic-link-service.cpp`和
  `ndn-net-device-transport.cpp`，让完整包目的地址随所有分片传入发送endpoint。
  未改forwarder、strategy、本地传输、fragmenter/reassembler或接收endpoint。
- 联合候选中5片均单播，末片MAC重试后收到；目标于5.984009079s完成L3/应用交付，
  抓包重组内容与源Data一致。没有应用层额外兜底或绕过无线模型。
  正式采用将涉及Router cc/h及两个底层cpp，需确认扩展原“不改底层”的范围。

### 实际执行与验收

- 所有构建设置`JOBS=4`，最多4个编译进程，未configure。
  Router按一致公开头重编10模块源＋3入口，13次编译、4次链接均exit0。
  底层隔离库替换2对象、复用285对象，编译/链接均exit0。
  `ldd`与哈希核对见`router-build/`、`overlay/fragment-destination/`和
  `provenance-check.json`；56项事后复核通过，主源、原库、模型不变。
  区分运行前后哈希与事后ldd，不冒称保存了运行时/proc映射。
- 在同一固定请求实际失败后准备候选；隔离运行器3项、日志分析器7项、
  抓包分析8项、矩阵汇总11项行为测试均红→绿。
  真正的GLS分片/逆序重组测试9例：原库因尾片目的地址断言失败exit1，
  候选同测试程序exit0，MTU及内容重组断言通过。
- LP重组独立夹具：同源有序、乱序重复、不同报文交错控制通过；
  两源同序号交错且endpoint均0时产生混合报文、exit1；
  分离endpoint后正确恢复两份、exit0。未把此潜在问题当成已证实的本例根因，
  未纳入推荐主修复。
- `run_diagnostic.py`复用原实验运行器与闭合校验，直接运行已构建程序、开启pcap，
  不触发waf。共16轮圆圈2车、每轮600请求、100km/h、窗口`[5,35)`、
  排空38.5s；全部完成且终态闭合。后续13轮执行见
  `followup-matrix-{plan,execution}.json`，所有退出码0。
- seed1两因素对照：原版570/600，仅Router570，仅分片目的地址580，联合593。
  Router自动网络回程分别598、0、597、0份；固定请求08仅联合版成功。
  严格机制＋交付验收原版/单项均exit1，联合exit0；未降低断言。
- 同一修正底层下三种子：VTDF为597/583/597，RTVTDF为599/596/598，
  Neural为593/594/594；每项分母600。累计满足率分别98.7222%、99.6111%、
  98.9444%。旧Neural同输入为570/382/407，共75.5000%。
  同种子冻结输入和实际GENERATED身份/纳秒时刻逐项一致，模型SHA256仍为
  `ab0015243af833550a3486be858aeb07d57c1b86b65d390c897e0cf9316918ca`。
- 相同修正底层下，seed1非神经三策略有/无Router改动的5份原始CSV均逐字节相同；
  成功数分别554/554、597/597、599/599。
  `followup-matrix-summary.json`确认16/16新运行、9/9历史参考完整有效，
  `verification_passed=true`；逐种子Neural不低于两种转发策略字段为`false`。
- 最终`source-model-freeze-check.json`确认全部16轮及9轮历史参考的生产源码内容哈希、
  Neural模型与隔离候选一致；另行记录运行后新增/修改的三个文档文件。
  文档链接、汇总数字及`git diff --check`通过，生产源码差异为空。

### 未解决项与正式计划

原型提高了交付率，但Neural仍低于同底层RTVTDF，未达到“效果不差于转发策略”的目标，
也未证明统计非劣性。联合版剩余19个超时全部保留：16个有RSU无线OUT但目标无L3 IN，
其中15个输出站覆盖当时记录服务站；另1个出站4.96ms后才换到该站，不能直接判模型错。
另外3个只观察到OBU Interest OUT，未见其进入RSU/Router。见
`lp-endpoint/remaining-timeouts-three-seeds.json`。未证明全部剩余丢失的物理原因。

正式落地需先把Router真实Face/PIT竞态及GLS目的地址测试纳入项目，
再实施4源码文件修改，更新测试注册/统一验证入口，增量重编底层库、模块和三入口，
执行三场景四策略验收。当前只运行了圆圈；另外两场景编译成功不能替代运行验证。
保留CS-hit/动态Face、不同selectors、多PIT、Nack/生命周期，以及未来LP可靠重传
仍使用endpoint0的适用边界。MAC重试可能增多，现有L3负载不包含该开销。
本轮交付是已做小规模验证的计划，正式修复尚未合入。

## 2026-10-21（始于10-20）：按用户确认正式修复神经回程与分片目的地址

用户明确要求“执行修改”，据此前已验证计划正式修改四个源码文件：
`contrib/vndn-nn-rd/apps/vndn-router.cc/.h`、
`src/ndnSIM/NFD/daemon/face/generic-link-service.cpp`、
`src/ndnSIM/model/ndn-net-device-transport.cpp`。
此授权包含两个底层文件；不再沿用上一轮“待确认”的状态阻止实施。
起始 HEAD 仍为 `86ef39c`，保留前一轮未提交的定位文档及入口记录。
详见 [正式修复与验收记录](NEURAL_DELIVERY_FIX_20261020.md)。
证据目录 `build/validation/neural-delivery-fix-20261020/` 下称 `F/`。

### 行为与文件范围

Router 在 Forwarder 同步收包之后清理已被神经应用接管的业务 PIT 网络 in-record，
覆盖未进入应用的受抑制重复 Interest，以及迟到指令激活；保留本地 in-record、
服务器 out-record 与定时器，Stop 断开连接。GLS 将完整包目标地址带到所有分片，
NetDeviceTransport 非 P2P 发送优先采用该 endpoint，零值保留原有标签/广播回退。
四源文件与前一轮联合原型逐字节一致，见 `F/formal-source-prototype-equivalence.json`。
未改模型、阈值、forwarder、strategy、本地传输、重组或接收 endpoint。

新增两个正式测试源 `vndn-router-neural-pit-test.cc`、`vndn-fragment-destination-test.cc`，
更新模块 `wscript`、`tools/validate.py` 与 `tools/tests/test_validate.py`。
另更新 `AGENTS.md`、`PROJECT.md`、`VALIDATION.md`，新建正式记录，并在旧计划顶部标记后续状态。
F 中的运行器、分析器与冻结矩阵只用于本次验收，复用原生产采集及完整性检查；
实验产物不写入历史数据或模型目录。

### 测试先行与构建证据

- 所有可能调用 waf 的操作均先 `export JOBS=4`，显式构建 `-j4`；未 configure。
- 实现前原五个 C++、五组 Python 基线全部通过：
  `python3.8 tools/validate.py --skip-build`，exit 0，报告
  `build/validation/20261020T153823.780501Z-b25ae4e5/report.json`。
- 新测试首次编译存在夹具完整类型头文件/命名空间错误，修正后编译通过。
  这些编译错误不算有效行为红灯。随后旧实现两个新套件均 exit 1：
  Router 实际网络 in-record 1、预期 0，实际 Data 2、预期 1；
  分片 endpoint 实际为 0、预期保留目标地址。
  见 `F/red-results.json`、`F/red-vndn-*.xml.xml`。
- 应用修复后构建 test-runner 和三个 simulator，exit 0；
  `python3.8 tools/validate.py` 的构建＋七套 C++＋五组 Python 共13步全部通过，
  C++ 38个子用例（新增10＋19），Python 80个测试，无跳过。
  报告 `build/validation/20261020T154751.173146Z-c470c777/report.json`。
- 验证入口自身先17测基线通过，新20测出现11个预期失败断言，
  注册两套新测试后20测通过。F 中保存 baseline/red/green 日志和统计。
- 正式运行器11测红→绿；验收分析器先11测红→绿，
  补 OUT 与 IN 分属两个 CSV 的真实读取边界测试后12测通过。
  总体验收时发现平均速度求和顺序产生末位浮点差异，保留首次失败报告，
  再新增4测，确认14个断言失败后修正，最终16测通过。
  只允许两个派生平均速度字段在8倍机器epsilon的相对界内舍入误差，
  NaN/Inf/超界仍拒绝；计数、字节、RTT、ISR及终态精确比较。未改原始数据。
  复用分析工具原18测通过；夹具/解析错误保留日志，不计成协议缺陷。

### 正式仿真与结论

14轮矩阵及三个目标请求在新仿真开始前冻结于 `F/e2e-expected-matrix.json`。
使用主构建程序与 `build/lib`，不再使用隔离 overlay；每轮启用 PCAP，
以 ldd 解析并保存二进制和依赖库前后哈希，拒绝输入、模型或源码中途变化。
这属于解析与哈希证据，没有声称保存了运行时 `/proc` 动态加载映射。
运行器14轮均 exit 0；`python3.8 F/analyze_e2e.py` 最终 exit 0，
`F/e2e-summary.json/.csv` 为14/14有效、无未完成与错误；
九组同种子跨策略输入、实际首次请求身份及纳秒时间一致。
圆圈seed1四策略成功数为554/597/599/593（各600请求），
Neural seed2/3各594/600；方阵22/27/28/24，蜘蛛网34/30/33/10（各36请求）。
后两场景 Neural 为均匀测试控制器，只验协议，不能声称真实模型质量。
每轮均发生切换；五轮 Neural 自动/未分类 Router 网络回程均0，
实际出站与显式选择一致，总计覆盖1756个单目标、103个双目标回传请求。
三场景事前冻结的目标请求及其 PIT/L3/应用链全部通过。

原失败请求08在正式构建中于5.984009079s收到DATA；PCAP中5片均完整到达，
10次源发射含MAC重试均发往目标车辆，重组内容与源Data一致。
`F/formal-target-pcap-acceptance.json` 的7项检查通过。
圆圈seed1四策略共20份原CSV与前轮联合原型相同，Neural seed2/3另各5份也相同。
`F/final-source-model-binary-check.json` 确认14轮源码快照、二进制及解析依赖稳定，
原两个圆圈模型均未改动。最终文档链接与差异检查通过。

本次正式 Neural 累计1781/1800（98.9444%），保留19个超时；
圆圈seed1仍低于同次RTVTDF的599/600，三种子也低于此前同底层RTVTDF原型1793/1800。
本次修复验收通过，但“神经策略不差于转发策略”未达到，不能标成科学非劣性成立。

当前修复的边界保留：CS-hit、动态 Face、同名多 selector 的完整应用语义、
未来 LP 可靠重传及多源接收重组问题。L3 采集口径未扩大到 LP/MAC。
通过修复验收不等于已经达到神经模型预测准确率或业务满足率的统计非劣性。

## 2026-10-21：三场景重采样、训练与论文出图计划（待执行确认）

用户要求参考圆圈模型，为三个场景重新多种子、多参数采样、训练、运行神经网络实验并出图，
明确先提供详细计划、确认后执行。起始HEAD为`f6347bb`，工作区干净。
使用用户指定的`grill-me`所指向的`grilling`流程，只读核查代码、既有方案、
训练/推理接口、历史图和本机资源，未运行构建、测试、采样、训练或仿真。

用户已确认四项设计：导师新增图与旧风格补图都输出；每场景一个固定模型；
标签采用Data首次回到原请求RSU时车辆的服务站；按每条件20个最终种子的完整规模规划，
先独立预实验估时，再冻结训练采样量与批次。这些设计回答不代替最后的执行确认。

新增[详细计划](RETRAIN_AND_FIGURES_PLAN_20261021.md)。关键事实与安排：

- 旧结果回调CSV不等于在线hello观测，新正式runner又关闭旧CSV输出，
  因而先补与在线共用的10×6旁路快照及统一回程标签、manifest和显式split。
- 方阵原路线不能保证七站覆盖；需在独立输入中生成并验证合法路线族。
- 保持现有TKAN-LSTM结构，三个场景分别重新训练，按验证集选模，
  新模型评估与四算法正式测试独立；不把旧100%验证准确率当新验收条件。
- 当前仍是12张L3性能主图＋3张应用额外提交机制图，另补固定K扫描、旧风格图及模型图；
  共30张编号图，诊断附图另计；不将最近底层修复误写成已扩展LP/MAC计量。
- 共享完全一致基准的正式四算法矩阵为4080轮；NoForward采样候选918轮，
  合计4998轮只是估时用候选，另加pilot与训练。采样数待pilot冻结，未实际执行。
- 本机CPU训练、约9.5GiB内存；计划包含流式数据、串行进程、增量waf/JOBS4、
  失败保留及配对统计，避免凭两车短验收估算大规模耗时。
- 交叉复核后明确多源样本身份、Router回程Face和截止期筛选、类别权重/早停规则、
  独立评估集预先完整性审计与性能反馈隔离；七类真实闭环放在路线覆盖验证之后，
  预实验先冻结设计，模型冻结后再核定Neural成本与正式进程timeout。

本轮只新增计划及此记录；不修改生产实现、原模型、历史数据或`ns-3_old`。
纯文档按事实、链接和差异检查，不用未执行的测试结果标记通过。

## 2026-10-21：执行三场景重新训练与出图计划（进行中）

用户明确“确认并执行”，授权计划P0–P6。详见
[执行记录](RETRAIN_EXECUTION_20261021.md)，不再逐阶段重复索要许可。
已保护起始暂存文档、冻结源码和两旧模型哈希；统一基线13步骤全部通过，
报告`build/validation/20261020T163654.266822Z-17bec152/report.json`。
已实现真实hello旁路快照、Router回程服务站标签、mmap监督训练与严格模型契约，
以及完整矩阵的串行调度/恢复、冻结后的独立评估和统计出图阶段工具。
新行为均保存基线、有效红灯和相应绿灯。统一14步骤已全部通过：
`build/validation/20261020T172150.744626Z-2483a09e/report.json`；
八个C++套件及Python 2/16/16/24/149项全部通过，无跳过。
模型/绘图实际小流程使用明确标记的合成验证数据，不是正式结果。

真实SUMO预检发现圆圈重复循环索引导致40车高速度条件仅39车入场，测试先行后
归约最短循环；方阵/蜘蛛网新覆盖路线排除掉头但保留原网全部道路和原RSU布局。
严格路口检查另揭示蜘蛛网原交通模型的左转几何重叠，未通过的诊断保留；
不继续按已见种子筛选路线，不修改原交通模型。按生产默认设置另行验证
实际入场/留场、碰撞处理与传送；两类证据和紧急刹车告警分别记录。
本轮未修改底层转发/传输/重组、四算法协议或0.10选择规则，也未覆盖两旧模型。
NoForward真实三场景采样开关六轮全部通过，原始六份协议日志成对逐字节一致，
同进程重算指标一致；三场景每轮450请求闭合，DATA分别171/300/227。
有效真实标签分别450/410/243；未观测请求仍计入失败分母，不将同站TIMEOUT归因于预测错误。
完整结果、浮点平均速度缓存尾差及二进制证据范围已写入执行记录。
预实验源码SHA为`ba577ef0090a7715387dca6dec8fd763930fa090746426116de6a96556d378b6`，
已归档，正在串行执行独立seed10001三场景300秒基准轮。
其余策略采样开关、临时模型Gym闭环及资源测量仍在推进；
详细命令、日志、错误和后续状态持续记入执行记录。
另在`build/validation/retrain-20261021-*`实现分阶段验收辅助插件：
P1/P4编排20项、临时采样/训练与资源记录15项轻量测试通过，
有效红灯、信号/超时清理、失败保留及哈希清单均归档。
这些工具未改生产源码，也尚未实际启动其对应仿真/训练；
长期驱动16项、等待器2项、资源报告4项通过，交叉复核后封存31个执行/测试/证据文件。
已实际启动后台等待队列PID15438，等待既有基准批次PID7969通过后，
串行继续验收、完整预实验、临时模型闭环和资源报告，当前状态waiting。
执行配置、启动身份、日志、归档哈希及冻结关口见执行记录；
本次队列目标为pilot-report，不能把该前缀完成标记当成整个研究任务完成。
暂未运行正式采样/训练/4080轮测试，不能将开发测试通过写为科研实验完成。

## 2026-10-21：核查旧队列失败，恢复验收及运行成本诊断（进行中）

用户要求查看进展并开始正式测试、出论文图。只读核查发现首个圆圈 baseline
在7200秒超时（仿真215.047652600秒，9753/15000请求），旧等待器随后失败退出。
实际正式结果0/4080、新正式模型0/3、正式图0；保留失败attempt，不纳入训练或统计。
生产源码SHA仍为`ba577ef0090a7715387dca6dec8fd763930fa090746426116de6a96556d378b6`。
10:12:39（北京时间）恢复既有驱动器的12轮转发策略采集开关验收，PID6664。
只读CPU采样显示事件调度、NDN、Wi-Fi及TraCI均有运行成本；不据短时采样断言唯一瓶颈。
已备份原debug/O0配置及链接产物，拟验证只改O2的构建，不改协议或实验设计。
状态、更正、实测路径及采纳门槛记录于[运行恢复记录](RETRAIN_RUNTIME_RECOVERY_20261021.md)，
同步更新AGENTS及执行记录。此处阶段仍进行中，不能把已启动验收当作正式实验已启动。

10:34新增实际证据：12轮VTDF/RealTimeVTDF三场景采集开关全部通过，
各对原始协议记录一致。随后备份原debug/O0链接产物并启动O2构建试验；
一次configure已返回0，保留debug宏、依赖、MPI、examples、Python及tests，
仅另关闭研究不使用的真实设备helper的sudo权限安装（本机没有免密sudo）。
源码SHA未变。统一回归报告`build/validation/20261021T023443.169930Z-0ed0fc89/report.json`
仍在执行，不能标记通过。后台序列会在单元及三场景原始事件/快照对照通过后，
明确将pilot诊断超时提高到43200秒并恢复至资源报告；正式模型和4080轮尚未启动。

10:50按用户最新指令改为立即运行现有程序。此前统一回归14步骤已全部通过；
不再configure或新增批量构建，未执行的O0/O2场景对照不标通过。
实际恢复三场景NoForward baseline，父PID30210，圆圈attempt-002的ns-3/SUMO已运行并写入请求事件。
操作包装入口位于`build/validation/runtime-diagnosis-20261021/no-build-entry/`，
复用原runner/campaign并只将`--run`改为`--run-no-build`；代码哈希清单、启动命令及日志均记录。
未修改生产协议/训练源码，未覆盖失败attempt或旧模型。用户接受非致命瑕疵不意味着可伪造完成、
混用训练/测试种子、删除失败数据或把采样说成正式论文结果。正式仍0/4080、新正式模型0/3。

11:01按用户“快点开始跑实验、接受一点小瑕疵”的最新要求，保留当前真实采样进程，
启动自动接续队列PID963。它在当前三场景baseline通过后直接继续918轮采样、数据集与三模型训练，
再执行既有最终模型工程核查、4080轮正式实验和出图，不再停在pilot-report后等待另一次人工开跑。
省去未执行的其余pilot及临时模型预演，未将这些项目标为通过；17条件、20正式种子、
模型冻结及真实数据完整性要求保持不变。生产源码不变，没有追加configure或编译。
新入口仅在build/validation下编排既有工具；路由检查核对完整矩阵与36个no-build工程命令，
没有另起仿真或把检查当作正式数据。文件哈希、启动身份、状态、日志和范围调整见
[运行恢复记录](RETRAIN_RUNTIME_RECOVERY_20261021.md)。11:02实际圆圈输出到仿真133.9345704秒，
新正式模型与正式实验仍为0/3、0/4080，后续以实际阶段产物为准。

11:25应用户询问只读核查队列进度：当前圆圈226.51/323.5仿真秒，10325/15000首次请求；
80.20秒内快照增长321355字节，确认持续推进。状态JSON只记录阶段，等待未结束的三场景基准，
不代表卡死。按局部速度当前轮剩余约31.7分钟；全4998轮若同速约230天仅为规模换算，
尚非可信跨场景工期。实验保持运行，未改源码、编译、参数或种子。证据及限制写入运行恢复记录。

11:32核对用户手动截图与当前源码/输入：手动是1辆车、80秒仿真，SUMO报告25.773秒现实耗时；
批量是10辆车、323.5秒、15000请求、NoForward及完整采集。正式采样0/918、测试0/4080；
约40分钟属于当前单个pilot轮次，不是整批。已明确规模不同但未证明全部慢因，
更正此前数百天外推不能作为可靠工期。继续保持当前运行，未编译或改实验参数。

11:39针对用户grid十车仍很快的反馈，完成现有慢进程12秒只读CPU采样：1174样本、无丢失，
直接指令热点集中于事件执行及事件队列操作，未显示写训练文件为主要热点。
定位ndn-cxx scheduler覆盖旧唤醒句柄而未取消的重复调度疑点，旧项目同样存在；
仍未通过最小复现证明唯一根因，不标为已修复。当前266.98/323.5秒、12350/15000请求，
单轮48.9分钟，正式采样0/918、测试0/4080。原始采样、符号化结果和限制见运行恢复记录。

2026-10-21 11:44按用户“关闭现在进行的仿真”停止运行：先SIGTERM自动接续队列PID963，
确认退出后SIGTERM基准调度器PID30210，由已有清理逻辑终止本轮ns-3/SUMO。
未删除原始数据和日志，未启动下一轮。中断轮次不可作完整实验结果；
停止身份记录在`plan/user-stop-20261021.json`，后续须用户重新授权执行。

## 2026-10-21：渐进减速只读排查与精简实验计划（实施待确认）

- 起始提交`c9492aa`，工作区干净。用户要求排查手动蜘蛛网前20秒快、之后极慢的原因，
  并先给缩减实验轮数的详细计划；本轮没有修改生产源码、configure、编译或重启实验。
  用户自己的手动进程未被停止。
- 对手动蜘蛛网PID14818做6.0118秒只读CPU采样：579样本、lost=0，
  直接热点为事件执行20.38%、ns-3事件插入14.68%、红黑树删除13.99%。
  原批量圆圈1174样本也以事件调度为热点，不能只归因于批量采集文件写入。
  证据位于`build/validation/runtime-diagnosis-20261021/manual-spider-cpu-14818.json`
  及同目录`manual-spider-cpu-symbols-14818.json`。
- 读取手动蜘蛛网12-04-48的L3日志：15/19/20/25/30秒网络Face每秒出站包数没有数量级跃升。
  默认20车在1.0～9.5秒出发，手动请求随OBU启动；批量模式20秒才开始测量请求，
  不能把批量阈值当作手动20秒退化的原因。日志不是墙钟或MAC重试证据。
- `ndn-cxx/util/scheduler.cpp`确认新队首调度覆盖旧ns-3句柄而未Remove，旧唤醒可再次安排下一次唤醒。
  与`ns-3_old`对应文件同SHA256，属于旧有路径，不是本轮新增采集造成的源码差异。
  Python控制流演示的100任务产生5050唤醒只能解释机制；实际C++复现、修复和场景加速均未执行。
  将其列为首要嫌疑，不宣称唯一根因或已获实测加速。
- 用户确认1～2天优先完整初稿、三点请求/速度、车辆5/10/15/20、5个正式配对种子；
  8个唯一条件对应480轮正式。探索采样48轮（24训练/12验证/12独立评估），最多追加24轮覆盖补采。
  计划独立run共528～552；短诊断、失败attempt和9次模型初始化训练另列，全部耗时计入预算。
  独立离线评估仅4个代表条件，正式覆盖8条件；小样本局限与补采规则明确记录。
- 新增[详细计划](SLOWDOWN_AND_REDUCED_EXPERIMENT_PLAN_20261021.md)，更新`AGENTS.md`最新范围与停止边界。
  计划包含测试先行的最小调度修复、最多12轮短对照、增量构建边界、显式采样清单、
  新设计身份及仅追加补采、旧硬编码队列替换、模型冻结/离线评估、480正式和25张真实图。
  不执行configure；后续真正C++修复需要`JOBS=4`及`-j 4`的目标增量编译，实施前整体确认。
- 本轮仅文档变更；不新增无意义行为测试，也不把只读审查写为C++或四策略回归通过。
  新计划经实验设计与调度代码两方向交叉审查，纠正RTT加权中心、失败attempt预算和计数可观测范围。
- 文档验证：`git diff --check`退出0；新文件空白/冲突标记检查通过；15个文档相对链接存在。
  Python只读检查确认8条件、48/72采样、480正式与528/552合计，调度器新旧SHA相同，
  四份CPU证据及已有单元测试二进制存在。以上均不属于新C++测试或真实仿真验收。

## 2026-10-21：执行精简方案1～4，正式实验交由用户手动（进行中）

- 用户授权调度器复现修复、短对照、48～72采样、三场景训练/冻结和独立评估；明确正式480轮自行手动执行。
  新准备入口止于`ready-for-formal`，正式和出图分别为独立命令；不恢复已停止的旧队列。
  起始提交`c9492aa`，保留上一轮计划/AGENTS/CHANGELOG文档差异。
- C++只改`scheduler.cpp::scheduleNext()`9行，新增12个Boost测试。真实红灯100回调产生5050内核事件；
  修复后100事件，22个新增及相关测试、381断言通过，另八个研究C++套件通过。
  两次目标增量构建分别只编译新测试对象和scheduler对象，无configure、无profile或批量重编译。
  旧库/二进制独立保留；代码、红绿和Waf实际任务证据见`build/validation/scheduler-fix-20261021/report.json`。
- `campaign.py`新增精简profile、显式24/12/12采样、8条件/5正式种子480轮、最多24覆盖补采及修订事务恢复。
  补采保留原job/manifest，拒绝训练开始后追加；workflow按datasets-revision-NNN保存新版数据集，旧路径不移动。
  正式首12轮为seed51001、三个场景baseline、各四算法；后续按seed分批。
- `run_experiment.py`新增`--no-build`，保存现有程序/依赖前后哈希；先复现并修正双poll漏判非零退出的竞态。
  `run_campaign_pipeline.py`区分prepare/formal/figures/status/stop，封存源码、管理专属子树与可恢复状态。
  当前终端每10秒、status --watch每5秒显示阶段/轮次/完成剩余/本次及累计耗时，不显示ETA。
- `training_coverage.py`在真实哈希和样本契约之上检查每split全类及跨站目标，记录细分支持数和排除量。
  旧loader可接受类别完整但跨站目标全0的真实合成fixture，行为红灯保留；新增13＋原数据22测试通过。
- aggregate/plot/workflow按声明验收25图，保留旧30图兼容；compact主图给种子点与SD，RTT中心仍按成功请求加权。
  workflow先得到25被旧30约束拒绝、补采后旧dataset被误复用两个有效红灯，再修正并通过回归。
- 工具证据：`compact-design-20261021/`（58项含真实25/30图渲染，后续正式顺序30项），
  `compact-pipeline-20261021/`（旧runner23＋新增3＋pipeline10），`compact-workflow-20261021/`（workflow34）。
  整合`tools/validate.py --skip-build`通过8个C++套件＋256项Python，13步骤无跳过，
  报告`build/validation/20261021T052609.726576Z-11058bc9/report.json`。
- 三场景两策略各旧/新短对照共12轮全部完成；六对汇总、请求内容、快照和动作一致，
  四类原始协议日志逐字节一致，仅同纳秒请求记录排序不同；测试控制器无fallback。
  蜘蛛网NoForward旧87.31/新52.39秒，神经测试分支旧101.36/新48.36秒，后段推进退化显著缓解。
  短对照不是最终模型性能结论，详细证据`scene-ab/paired-comparison.json`。
- 13:32:38北京时间实际启动prepare PID7402，新目录`data/experiments/retrain-compact-20261021`，
  源码哈希`2c410ef3fd0504441e6fe9c7fc4c2a2e78d3b6c6b9284d9776a48af725919910`已归档。
  先24/12/12真实NoForward采样，后覆盖/训练/冻结/独立评估；不自动执行480正式。
  进度、命令、模型路径与后续实际完成情况见[精简执行记录](COMPACT_EXECUTION_20261021.md)。
  本条启动时采样未完成，不能写成模型或论文图已完成。

用户随后表示每轮约3分钟可接受，又要求“先结束任务”。按最新停止要求执行
`python3.8 tools/experiments/run_campaign_pipeline.py stop --root data/experiments/retrain-compact-20261021`
→ exit0、stopped/data_preserved。核查采样1/48完整完成、正式0/480，准备累计约4.7分钟；
训练及独立评估未开始。本次队列与仿真子进程已退出，旧孤立SUMO11059未触碰。
原始数据及中断attempt保留，AGENTS与执行记录已明确等待新的续跑指令，不能自动重启。

## 2026-10-21：保留调度器修复，旧参数12轮采样计时（进行中）

- 用户确认三场景各测10车/15000请求、20车/30000请求、40车/60000请求、40车/15000请求。
  全部v30、seed10001、NoForward＋真实训练快照、20＋300＋3.5仿真秒；每轮上限1800现实秒。
  本任务不恢复旧918/4080或新48/480完整队列，不训练模型，留待用户选择实验规模。
- 起始HEAD为用户已提交scheduler修复的`c827c39`，保留已有全部工作区差异；生产源码无修改。
  13:45:36复用旧圆圈baseline输入开始首轮，其余11份由现有generator生成到新诊断目录。
  输入/命令清单核对12唯一条件，全部`JOBS=4`、`--no-build`和snapshots，无configure/编译。
- 当前库在本任务开始前已更新，与此前短对照库哈希不同；直接运行现有NdnCxxScheduler测试，
  12例347断言通过，未触发构建。编排脚本在build/validation内，`--check`退出0后启动接续，
  只调既有runner并记录进度、整轮现实耗时、RSS及完成状态，不改实验实现。
- 新增[旧参数计时记录](OLD_DESIGN_TIMING_20261021.md)并更新AGENTS范围。
  新产物在`data/experiments/old-design-timing-20261021/`，此记录创建时测试仍在进行，结果待补。

14:04用户要求“停止实验”，核对PID身份后SIGTERM本次driver12714，已有清理逻辑终止自有子进程，
driver退出130。进程核查无本次runner/ns-3/SUMO残留；旧无关SUMO11059未触碰。
三轮10车/15000请求均complete，整轮circle256.15秒、grid230.99秒、spidermap203.64秒；
第4轮circle20车/30000请求在约304.2仿真秒中断，记录SIGTERM失败，不当作完整结果。
其余8轮未开始，40车成本尚未测得。保留数据及STOP/user-stop.json，更新AGENTS与计时记录，
不自动续跑。整个任务无生产代码修改、configure或编译。

## 2026-10-21：分步骤执行与中断恢复方案定稿（仅文档）

- 用户确认仿真以完整轮为恢复单位、手动分步及限制轮数、训练每epoch断点并跳过完成候选；
  明确只保留立即停止，不实现轮末暂停。实验规模仍待用户选择，全部已停止队列保持停止。
- 只读核查发现已有完整run/stage复用与筛选限轮入口；缺口包括累计attempt上限计入人为中断、
  半生成输入目录、状态重建、缺少fsync提交及训练缺optimizer/RNG/earlystop恢复。
  两个方向交叉审查了旧证据兼容和训练last/best/history一致提交，未启动测试或实验。
- 新增[分步恢复实施计划](STEPWISE_RESUME_PLAN_20261021.md)，列出六手动步骤、拟议入口、
  实际文件与影响范围、持久化边界、受限旧来源接纳、测试先行和小规模故障恢复验收。
  已明确工具修改会改变整体source hash，禁止篡改旧manifest或只放宽单处身份检查。
- 现有compact的1轮完整采样保留，升级后须核验兼容；3轮validation_only计时只作预实验证据。
  更新AGENTS与PROJECT导航；本轮不改生产/训练实现，不configure、不编译、不运行采样/训练/正式测试。
  用户已有暂存与未暂存差异均保留，不操作Git暂存区。
- 文档校验`git diff --check`退出0，69个相对链接目标存在、无冲突标记；已核对旧完整采样所用NDN库
  与当前库哈希不同，将其列为实际兼容审查项，未宣称仅凭源码一致即可无条件混用。

## 2026-10-21：执行10小时探索初稿方案（运行中）

- 用户最新授权独立新批次`retrain-quick-20261021`自动采样、训练、四策略对比和出图。
  保留旧数据、已停止队列及全部用户暂存/未暂存改动；不操作index，不configure或编译。
- `campaign.py`新增`quick-draft-v1`：20/120/3.5秒窗口、8条件、48采样、两配对种子192正式、25图，
  使用独立种子域，拒绝在本固定预算内隐式补采。旧full/compact行为保留。
  `run_campaign_pipeline.py`增加显式`all`及profile校验；`prepare`仍止于模型就绪。
- `aggregate_campaign.py`严格核查quick真实矩阵及窗口；`plot_campaign.py`标记探索初稿/n=2，
  主图及总流量展示实际运行点与SD，新增本地HTML预览并输出PDF/SVG/PNG。
  未扩大L3负载与额外Data的既有统计口径。
- `campaign_workflow.py`和`formal_training.py`适配一次初始化、最多30epoch及稳定训练会话续训。
  训练配置固定初始化62021、patience5、其余默认32隐藏单元、CPU单线程，具体见执行文档。
  整合审查发现workflow误读profile字段，已通过真实quick计划调用补出有效失败测试并修为design_profile。
- 测试先行证据在`build/validation/quick-draft-20261021/`：设计30基线/7新增先红/37绿；
  图表44基线/7新增先红后绿/44旧回归绿；pipeline10基线/4新增先红/14绿。
  训练保存、恢复及最终整体回归仍在执行，不提前标记本批次真实数据或论文图完成。
- 新增[quick执行记录](QUICK_DRAFT_EXECUTION_20261021.md)，同步AGENTS与PROJECT最新授权；
  原分步恢复计划仍有未实现范围，不把本次最小适配当作完整迁移/掉电恢复系统。

训练相关13项、workflow旧34项和quick实际计划集成3项通过；三场景实际TKAN稳定session保存/现有控制器加载推理通过。
最终`export JOBS=4; python3.8 tools/validate.py --skip-build`退出0，8个C++套件和283项Python通过，无跳过；
报告`build/validation/20261021T065832.662374Z-25b8d4da/report.json`。差异空白和新增导航链接检查通过。
15:00:11北京时间启动真实all队列PID1881，源码SHA256
`142365d8cc9af24f8028f6cc5bf11dd30af9baa0ac7c9ecb538ac3e9487c90a4`已冻结归档；
首轮circle/baseline/seed23001确实以`--run-no-build -j 4`启动。本条仅记录开跑，尚未完成新模型或真实图集。

15:04核查已真实完成2/48采样：circle6000请求109.07秒、1500请求102.22秒，均完整校验通过，
第三轮12000请求自动进行中；正式仍0/192。完成数据与所有日志保留，进度入口显示实际轮数及已用时间。

## 2026-10-21：完成结果归档、原始数据索引与手动复现说明（仅文档）

- 用户要求按今天日期记录这批数据/模型/图表位置，并给出重新出图和手动重新仿真命令。
  22:32核查pipeline已于22:29:04正常结束：48采样、192正式均complete，240轮全部首次attempt成功；
  总耗时26931.15秒（7小时28分51秒），25计划图＋9诊断图，共102个图文件。
- 新增[结果归档](QUICK_DRAFT_RESULTS_20261021.md)，记录三模型准确目录、实际epoch/选中epoch、
  训练数据与独立评估、raw日志和汇总CSV、图编号与口径、仅重画/重新汇总/单轮四策略/新完整批次四类命令。
  说明完成阶段会复用、不覆盖旧图、同种子复跑不增加独立重复，以及三模型须另外保留。
- 新增`docs/ai/records/quick-draft-20261021/`：240行run-index.csv，5649文件file-index.csv，
  model-index.json和archive-check.json。逐文件重新计算SHA256，核查240个run manifest、3312个run产物、
  1440个输入引用、48个模型引用、395个workflow产物、255个依赖、来源归档和三模型，全部匹配；
  另核查102图文件与figure-index.json匹配。模型目录约36.7MB，主批次约4.245GB。
- 同步AGENTS、PROJECT及quick执行记录的最终状态，保留历史进展，不改旧manifest、原始数据、模型或图片。
  本次无生产代码修改，无仿真/训练/configure/编译；纯文档不新增伪行为测试。
  手动命令依据实际CLI、输入模板及冻结模型检查；不把语法/路径核查写成重新执行实验成功。
- 最后验证退出0：82个文档相对链接存在，5个Bash命令块语法通过，48份正式输入模板及哈希通过，
  三场景手动runner参数解析通过，240行run索引/5649文件索引唯一且路径存在；
  当前生产源码SHA仍与本批次冻结SHA一致。`git diff --check`通过，检查详情记入archive-check.json。

## 2026-10-21：独立出图代码、模型与AI交接包

- 按用户指定创建`data/experiments/retrain-quick-2026102-others/`（保留2026102拼写），
  原样保留用户已有`解释.md`。三个统计绘图脚本及相关测试从原工程逐字复制，原工程实现不变。
- 补齐主数据包以外的三个完整模型会话（36723684字节），附原归档索引与历史文档，
  新增README、AGENTS、数据/图号/指标对照、结论边界及后续AI变更记录。
- `code/replot.py`提供check/plot/rebuild：仅对三个复制模块的Path构造做历史数据/模型根映射，
  不改原JSON或哈希，不回退旧根，拒绝覆盖输出；新产物记录入口代码SHA256和映射。
- 测试先行：5项原绘图基线通过，迁移夹具因旧路径读取而先失败，新增13项通过；
  实际交接目录原统计绘图52项回归及13项迁移测试均通过。无跳过、无仿真/训练/configure/编译。
- 真正解压用户tar.zst到带空格的新临时路径，并用审计钩子禁止open原工程：
  check、25计划图＋9诊断图重画、192轮/48配对block重算并再绘均完成。
  四张主要分析表逐字一致，主性能/配对效应/计数/因子审计一致；原数据与副本5649文件分别核验共11298个SHA256全匹配。
- 原summarize按车辆set顺序累加浮点速度，重算的加权平均速度最大差5.293543381412746e-13；
  独立多PYTHONHASHSEED重现，仅对三个速度字段采用1e-12绝对容差，其余字段精确比较，未修改原统计实现。
  验收辅助脚本种子列表断言错误和浮点逐字比较的初始失败均留档，最终修正后的校验退出0。
- 来源、测试日志、真实搬迁对照报告与交付SHA清单保存在包内provenance；
  运行时用户归档名字变化未被本任务修改，记录实际提取来源而不臆造归档整体SHA。
  同步主AGENTS、PROJECT、VALIDATION和结果归档导航；用户其他差异及Git暂存区不动。
  最终交接包117文件、39823865字节，SHA清单核验全通过；6份新增文档的12个本地链接和6个Bash块语法通过，
  `git diff --check`通过。真实验收的临时解压/重画副本已清理，原实验、交接包及验证报告保留。

## 2026-10-21：初稿性能与控制口径的只读实现诊断

- 用户质疑F01/F02/F04等结果，并选择优先ISR/交接RTT、本轮只诊断实现不增加统计指标。
  新增[诊断记录](FIGURE_IMPLEMENTATION_DIAGNOSIS_20261021.md)及`records/figure-diagnosis-20261021/`九份诊断证据与索引。
- circle四策略共同成功2922请求仍有NN高RTT；64轮原始L3出站/OBU交付分段表明NN基准末跳约282ms，
  K12000约469ms，RTVTDF高负载同样退化。与默认500ms队列寿命高度吻合，但缺MAC重试/过期记录，未宣称确证根因。
- 核实Naive常规广播、NN目标单播及所有分片目标、非QoS共享设备队列、6Mbps物理速率/10KiB载荷。
  排除正常神经路径的固定应用等待，区分Python墙钟推理与仿真RTT。
- 控制分解核实RTVTDF读取TraCI即时位置且不产生定位通信，NN每请求route/pit有正确性用途。
  列出共享Hello漂亮JSON压缩、模型时点/历史新鲜度、神经备用回调sender身份不一致的候选排查；均未实施。
- 只读比较中曾计算补充口径作为诊断，未修改主指标/图。保存其来源和限制，不把它们替换为论文结果。
  原始数据、源码、模型、图和已校验的便携交接包均保持原样；不运行仿真/训练/configure/编译，不新增形式单测。

## 2026-10-21～22：候选实现小批量筛选、hello减冗余及回程缓存修正

- 用户随后明确授权尝试候选，小批量通过再报告，无效则继续尝试；优先ISR及交接RTT，保持原统计定义。
  起始HEAD为`757701f8ebf16b34a02e72d09314f84f26ff4dd3`，保留已有AGENTS/AI文档和归档差异。
  完整证据和命令见[小批量记录](PERFORMANCE_PILOT_20261021.md)，持久小型证据见
  [记录索引](records/performance-pilot-20261021/README.md)。
- 基线真实MAC日志确认circle测量窗口RSU队列过期3154次、重试21543次、重试上限失败987次，
  过期队列年龄均值514～515ms。没有请求名的过期帧不能全认定为业务Data。
  20个旧运行的模型目标核查显示“选对站仍丢包”是主要剩余问题；不把目标覆盖率当作交付率。
- 保留A：`vndn-obu.cc`将hello `dump(4)`改为紧凑序列化；真实C++13夹具解析基线通过，
  紧凑要求旧版13失败，候选13通过。字段和模型特征无改动。
- 保留B：`vndn-rsu.cc`严格识别Router已准备PIT格式，避免发送RSU被误当OBU缓存。
  新增`vndn-rsu-neural-return-buffer-test.cc`和wscript注册；旧版真实网络测试重复交付2次（期望1），
  修正后三例通过，保留两种旧OBU标签回退。circle A与A+B逐请求/RTT及7文件相同，不能归因为吞吐提升。
- 保留E：仅在已登记且added/removed同时空时省略三个增量字段；初次完整缓存和非空增量仍完整发送。
  提取真实OBU编码和RSU缓存分支，旧版16步语义通过、6步空增量要求失败，候选16步全部通过。
  单个空增量紧凑JSON少44B；实际负载以新仿真计数为准，不修改旧结果数字。
- 拒绝C：RTS/CTS阈值1000且短/长重试上限同为7，circle ISR80.77%→57.02%，不因RTT下降而保留。
  拒绝D：hello错峰的真实调度/轨迹检查通过，但完整circle相对A+B的ISR83.07%→80.52%、RTT恶化。
  原始失败方案和夹具修正记录保留；两者均未进入生产源码。
- 修改`tools/validate.py`和其测试，新增第九C++套件。入口基线22通过，扩展要求旧入口5次预期失败，
  补齐后22通过；没有减弱断言或跳过测试。A/B/E均先在隔离共享库真实仿真后才应用到生产。
- 19轮开发/诊断完成，最终候选包含两个circle种子、同配置RTVTDF及grid/spidermap基准。
  circle/52001原NN→新NN为80.77%→85.30%、476.99→435.68ms；63011为79.17%→86.35%、498.01→420.53ms。
  同配置RTVTDF分别88.57%/397.39ms、89.00%/375.14ms，**总体仍未达到不劣于RTVTDF**。
  grid/spidermap ISR与原版相同，RTT变化小，交接子集有轻微退化，均如实保留。
- 最终生产与冻结候选逐字一致；定向串行编译3对象、链接并备份替换2库，其他202个保护文件哈希不变。
  未configure、未运行waf构建、未改公共头或重链三场景程序；没有伪造原waf缓存签名。
  暂存9套件45例通过后安装；`python3.8 tools/validate.py --skip-build`退出0，45 C++＋283 Python全部通过。
  实际报告`build/validation/20261021T163616.028884Z-5a3380bc/report.json`，持久副本在
  `docs/ai/records/performance-pilot-20261021/production-validation/`。安装安全测试6例通过，独立复核也通过。
- 安装后原运行器`--no-build`四策略各一轮短测全部完成并通过数据闭合校验（5车、250请求、seed63001），
  NN加载原冻结模型。此4轮仅作安装烟测，不作性能比较；总共19筛选＋4安装短测。
  新数据仅在`data/experiments/performance-pilot-20261021/`，旧批次、模型、图和便携交接包没有覆盖。
  同步AGENTS/PROJECT/VALIDATION；完整论文队列未重启，无新训练/正式出图。
- 结论：实现正确性、定向构建、单元回归及所述小批量流程通过；所测circle自身性能改善，
  但“整体优于或不劣于RTVTDF”的研究目标未达到，不能据此替换旧论文结论。

## 2026-10-22：grid/spider新方案专项小批量实跑

- 用户明确要求检查已安装新方案对grid/spider是否有效。本次只跑实验及分析，生产源码、模型、统计器不变。
  14轮运行Git版本均为`87057a96feab620b9a526a459b0e6344e2366ac0`，生产代码快照SHA一致。
  保留起始已有A+B+E实现及AI文档差异；未configure、未编译、未训练，也未启动完整论文队列。
- 开跑前固定两场景×10/20车（6000/12000请求）×seed52001/52002×RTVTDF/NN共16个新配置结果。
  两个既有NN基准核验后复用，新增14轮串行完成，实际批次用时2142.366秒；全部退出0且原运行器闭合校验通过。
  旧版复用quick对应16轮，所有比较使用相同输入、请求/物理轨迹、模型和原指标定义。
- 独立复用审计核验16旧轮224个产物及2新overlay轮30个产物；overlay源码、8个复用对象、编译参数与正式版本一致，
  不冒充库二进制逐字一致，也不把复用当作独立重复。新14轮加载实际生产主库0b52d5...，其他148运行依赖和程序未变。
- 原始CSV重算五指标、16配对、8新NN−RT比较，独立复核8两种子均值/4差值变化/24缓存身份均通过。
  辅助分析器保存在build及新文档证据中；原统计器20项基线通过，汇总夹具先RED后4项通过，
  后发现缓存身份保护遗漏，追加有效RED后5项通过，并用真实运行副本核查错误缓存被拒绝。
  这些辅助工具验证不替代仿真；原始数据和有效缓存未被改写。
- NN结果：grid10车ISR89.8583→90.1000%、RTT316.903→315.317ms；grid20车83.2625→84.5458%、396.304→382.744ms。
  spider10车ISR60.7667→60.7417%、20车50.8167→50.8000%，成功RTT仅微降，少成功请求如实保留。
  NN控制负载各条件下降28.99%～30.08%；grid20车额外Data提交均值505→527.5，不能写五项全部改善。
- RTVTDF同样降低控制负载且grid交付改善；新NN在四条件ISR仍较低、控制量仍较高、网络总量较低。
  NN成功RTT在grid10/spider10/20较低，但grid20较高；既有算法差异不能归因于新优化或模型准确率提升。
  两个开发种子不支持显著性/正式非劣性结论；车数和请求量同步变化，不能解释为纯车辆密度效应。
- 新增[专项记录](GRID_SPIDER_PILOT_20261022.md)、`records/grid-spider-pilot-20261022/`及AGENTS导航。
  新原始数据仅在`data/experiments/grid-spider-pilot-20261022/`，旧实验/模型/图/交接包保持原样。
  计划、实际状态、完整数据位置、按seed结果、审计和手动复跑命令均归档。
- 准备时一处脚本路径拼写、结束后一次读取current=None的状态查询及独立审计工具字段名曾出错，
  均经修正复核且不涉及仿真失败；14轮实际运行没有失败、超时或重跑。
- 结论：本次执行和数据验证通过。新方案在两场景降低冗余负载，grid20车交付改善；
  spider尚无成功率/交接交付改善，不能宣称神经策略总体超过RTVTDF。

## 2026-10-22：仅神经策略启用两项hello优化

- 用户明确要求只让NeuralNetwork使用紧凑hello与省略空缓存增量，另外三策略恢复原格式；
  随后要求仅在文档解释额外优化，不在对比HTML或图中添加标注。遵循此范围，不改统计定义和旧结果。
- 修改OBU cc/h、OBU App头、circle入口和公共map入口：实际回程策略传递到OBU，默认NoForward；
  只有策略3使用紧凑编码且省略空增量。0/1/2恢复dump(4)并保留空CsAdded/CsRemoved/CsUpdate。
  保留首次全量、非空增删、模型字段、hello频率、RSU prepared-PIT身份修正。
- 修改前统一回归通过，报告`build/validation/20261022T031255.294818Z-dff2bd99/report.json`。
  新增`tools/experiments/tests/test_hello_strategy.py`：真实OBU/RSU分支探针44个状态，
  旧实现有效RED为33个格式＋9个空增量＋3个接线失败；编译/探针执行退出0，非编译错误冒充失败。
  修改后6项测试、44状态GREEN。首次探针include路径准备错误另存，不计作有效RED。
- 修改前三场景NN短跑各一轮通过。首次grid因新增测试文件触发运行期间源码变化保护而拒收，
  保留失败记录，冻结测试后另起目录重跑通过；未改失败manifest。
- 本次状态、构建和场景验收见[神经专用hello记录](NEURAL_ONLY_HELLO_20261022.md)。
  定向编译4对象/链接1库3程序，阶段9套件45例通过后安装，另同步2导出头；无configure或waf构建。
  独立复核229冻结输入/179受保护库，正确保留此前RSU修正对象，未误链旧对象。
- 三场景四策略12轮安装后短跑全部完成，耗时128.540秒。三场景NN前后五CSV逐字相同，
  两类决策排除必要运行身份后完全相同；模型/统计/绘图文件哈希保持不变。
  三种非神经策略hello Data平均单包字节恢复更大编码，精确字段及缓存语义由44状态探针保护。
- 首次安装后统一回归与真实仿真并行，4个实验编排用例因全局实验锁失败；保留失败报告，不改断言。
  仿真结束后串行同入口退出0，45 C++＋289 Python全通过，最终报告
  `build/validation/20261022T032517.668025Z-315a8fff/report.json`。
  后续统一回归与实际仿真应串行。证据及源码副本在`records/neural-only-hello-20261022/`，原始短跑在
  `data/experiments/neural-only-hello-20261022/`。未启动完整性能批次、重训或重画图/HTML。
- 结论：代码修改、生产安装及所述验收完成。已有共享优化结果保留原配置解释；
  后续神经方案收益包含报文优化，不能全部归因于预测模型。

## 2026-10-22：神经策略进一步探索，18轮配对验证及隔离CBOR候选

- 用户授权探索其它改善方案，circle小批量通过后再验证grid和spidermap；优先业务成功率与交接时延，
  保持原统计指标。仅神经策略享有额外编码收益，机制解释只写Markdown文档，不改对比HTML/图。
- 起始HEAD `f623b37c5e3da8becc673e08c1361c186604c648`，源树起始干净；当前正式主库
  `b73e0752d551e466c8f8dcec3a7015eaf98503f3f3779e6b6fb312a854da9504`保持。
  正式改动仅AGENTS入口、本记录和新增`NEURAL_EXPLORATION_20261022.md`。
- 候选源码位于`build/validation/neural-explore-20261022/candidate-wire-v1/source/`：
  NN hello改为`VNH1 + CBOR [1,[六维原值],NextRsu,cacheObject]`，双端版本/形状/数值/缓存校验，
  RSU恢复原JSON对象后走原逻辑；保留原数值精度/频率/缓存含义/模型输入和其他三策略旧JSON字节。
  没有改正式cc/h、模型、选站阈值、NFD、统计/出图实现。
- 先行基线：6项现有hello测试、5个相关C++套件通过。
  真实分支提取探针旧实现435检查中15项有效失败；版本整数边界新测试另发现下界问题，修复后
  `candidate-wire-v1/frozen-green/`441检查通过，覆盖56个策略/缓存/数值状态及24个坏输入。
- 隔离工具`overlay.py`沿用最新神经专用hello构建计划中的10对象，复用8个正确对象，只编译OBU/RSU两对象、
  链接1库；不采用早期构建树的陈旧对象，保留prepared-PIT身份修复。库SHA
  `a930351bd444aaa3f1bf6a3291ce56d3ba247a1b3b5b50c1b01f93674998ba4f`。
  三场景程序及其余动态依赖未改；每轮封存overlay-provenance，普通源树快照不冒充候选源。
  `JOBS=4`，没有configure或批量重编，真实仿真串行。
- 候选库实际加载到debug test-runner，5套件19用例全部通过（forwarding-policy、return-selection、
  neural-return-buffer、training-snapshot、router-neural-pit）；ldd及XML在`candidate-cpp-tests-debug/`。
  最初误选optimized test-runner无匹配测试，保留于`candidate-cpp-tests/`，不计有效RED或通过。
  私有头/编解码独立复核未发现阻断缺陷，正式安装需同步双端并更新现有NN必须JSON的测试假设。
- 隔离工具6项、新性能门槛6项、源站标签/分母审计13项行为测试先红后绿；相关旧固定交接工具7项基线通过。
  `analyze.py`首次读取实际manifest时纠正execution_mode应为existing-binary，错误日志保留；
  不完整运行标pending/null，不能计0或失败，也不挑多个完整attempt中的有利结果。
- 先冻结`plan.json`，实际18轮全部complete且原始闭合/输入/模型/库/轨迹/请求配对核验通过。
  三场景10车、速度设置30km/h、6000请求，20秒预热+120秒测量+3.5秒排空，种子52001/52002；
  每场景当前RTVTDF/当前NN/候选NN各2轮。现有三模型权重不变。
  circle门槛通过后才启动grid/spider。原始数据`data/experiments/neural-explore-20261022/`，
  三场景完整报告在本轮build的`analysis/`；最终路径/SHA见`final-summary.json`和`runs-index.csv`。
- circle当前NN→候选：ISR85.4083→90.6250%，RTT430.8669→346.4444ms，固定交接成功765→853，门槛通过。
  grid：ISR90.1000→90.4667%，RTT315.3170→314.0629ms，交接1716→1747，通过但收益小；ISR仍低于当前RTVTDF。
  spider：ISR60.7417→60.7167%，RTT301.3849→301.5705ms，交接547→545，性能门槛未通过。
  候选控制负载三场景均下降，但不能替代成功率/时延门槛，不删除负向结果或修改门槛。
- 严格源站实际回程子集审计完成12个NN运行，6个RT按定义跳过；模型输入契约及控制器/C++动作一致。
  将模型top1、目标集合覆盖与业务交付分开；源站未回/无决策/多源等保留性能分母。
  早期11808/11824是“任一选中站最早回程时刻”的集合覆盖，不是源站训练标签准确率。
  grid可评价子集top1反而略降，不能宣称模型分类提高。两个开发种子不构成独立泛化/显著性结论。
- 结论：候选保留隔离，完成本轮探索；不全局合入，不启动完整论文重跑或重训练。
  相关小型代码/证据副本保存在`docs/ai/records/neural-explore-20261022/`，沿用原Git忽略规则，未自动提交。
  详细结果、复算/单轮复跑命令、来源和已知失败见`NEURAL_EXPLORATION_20261022.md`。

## 2026-10-22：按用户决定正式合入三场景神经专用无损hello编码

- 用户明确选择“三个场景均启用，接受spider本轮小幅退化”。覆盖此前探索结束时不全局安装的限制，
  保留spider未通过性能门槛的原事实，不重写门槛或结果。仅NN发送新编码，其他策略维持原JSON。
- 起始保留前一任务AGENTS、CHANGELOG及探索记录的文档差异；未提交、重置或覆盖用户其它工作。
  合入`vndn-obu.cc`、`vndn-rsu.cc`与新增`vndn-hello-wire.h`，三源与被冻结候选逐字一致。
  NN发送VNH1/CBOR六维原值和缓存状态，RSU先校验后恢复原对象；旧JSON继续兼容，非NN保留dump(4)/空增量。
  模型、选站阈值、hello频率、统计/HTML/绘图和三场景默认策略不变，不修改底层。
- 修改前统一回归退出0，45 C++＋289 Python，报告`build/validation/20261022T064408.850439Z-e0ce2a1a/report.json`。
  先扩展`tools/experiments/tests/test_hello_strategy.py`为8项测试，真实旧源码探针编译成功，
  441项检查中15项有效RED：14个NN新编码断言、1个RSU新格式接受断言。证据目录准备错误单独保留，不计RED。
  合入后同一测试SHA不变，8项/441检查全GREEN，覆盖56状态、24坏输入；保护数值、缓存和非NN字节。
- 安装前新跑三场景候选NN参考；定向冻结3404输入/保护文件、编译2对象/链接1库，复用核验后的8对象。
  阶段库实际通过9 C++套件45例后，备份并原子安装主模块库；三场景程序、其它依赖和公有类头不变。
  当前库SHA`f51b177817af6b4b2c83f5e9d4d3ab4f02bef02a7c192705db760b962dbb2665`；
  原b73库备份在本次build的before目录。全程JOBS=4，无configure、waf构建或批量重编。
- 安装后12轮（三场景×四策略）串行全部complete且闭合校验通过，累计墙钟120.534秒。
  配置5车/250请求/seed63021，5秒预热＋10秒测量＋3.5秒排空；NN加载各场景原quick模型。
  非NN与原b73库九轮、NN与本次a930候选三轮比较，60原始CSV逐字相同，6决策JSONL按既定run_id规则一致。
  安装核验工具6行为用例先RED后GREEN；真实核验包含全部24个manifest，不忽略失败/重复attempt。
- 仿真结束后串行执行`export JOBS=4`及`python3.8 tools/validate.py --skip-build`，退出0，
  45 C++＋291 Python全通过，无跳过。报告`build/validation/20261022T065928.532065Z-913c9547/report.json`。
  源码/模型/依赖独立只读复核及实际loader身份检查保留；不把实现测试当作科研非劣性证明。
- 新增[正式合入记录](NEURAL_WIRE_INSTALL_20261022.md)，同步AGENTS/PROJECT/VALIDATION和两份历史记录的后续状态说明。
  本次证据`build/validation/neural-wire-install-20261022/`，原始数据`data/experiments/neural-wire-install-20261022/`。
  小型代码/测试/日志副本位于`docs/ai/records/neural-wire-install-20261022/`，沿用Git忽略规则，仅本机存档。
- 结论：正式实现和所述部署/回归验收完成。18轮探索性能仍是circle改善、grid小幅改善、spider小幅退化；
  用户接受采用不改变负向结果，两开发种子不能证明泛化或统计显著性。额外机制只记Markdown，未改对比图/HTML。
  未重训、未出新论文图、未启动完整实验队列；新源码后续性能须使用新数据，旧结果保留原版本解释。

## 2026-10-22：固定昨日模型的264轮quick扩展实验

- 用户完成grill确认后明确“确认并执行”：Interest1500/3000/6000/9000/12000、速度15/30/50/60、
  车辆5/10/15/20；20秒预热+120秒测量+3.5秒排空，11条件×3场景×4策略×2种子=264轮。
  circle23001/23002、grid23009/23010、spidermap23017/23018固定，明确复用训练种子进行探索对比。
  复用昨日三模型、固定阈值，不重新采样/训练，不生成训练图；444分钟是目标，允许完成整批约8小时。
- 起始HEAD `c64023a4af55b0f47fa01898a1a86352aae28889`且工作区干净；保留原实验和三模型。
  新目录`data/experiments/quick-fixed-model-20261022`，旧批次不恢复，不向旧结果续写。
- 新增`quick-fixed-model-v1`独立profile，修改`campaign.py`、`run_campaign_pipeline.py`、
  `campaign_workflow.py`、`aggregate_campaign.py`、`plot_campaign.py`，新增`fixed_models.py`来源核验。
  历史训练source与当前运行source分别绑定，核对模型manifest/dataset来源/契约与13项文件依赖，
  不改历史checkpoint或解除旧profile隔离规则。新profile直接模型复用→test→figures。
  保留每轮校验与完成复用、立即停止、累计与当前轮时间；n按各场景2seed计算，不把union6当重复数。
- 原五指标公式不变；图集22编号图+6诊断图，取消混淆矩阵/学习曲线；RTT三维图取场景首个指定seed。
  机制说明仍只记Markdown，不在比较HTML/图里添加额外优化说明。三场景默认策略和底层均未修改。
- 测试先行：原实验工具228项基线通过；新增campaign10/pipeline7/workflow9/figures7共33项行为测试。
  旧实现因unknown profile/不接受空development splits等目标行为缺失而有效RED，最小实现后GREEN。
  duration为float导致请求数类型错误、代表seed篡改可能生成空图另有有效RED并修复。
  首次figure fixture seed未同步的准备错误保留，不计有效RED。分项日志在本次build目录。
- 真实264个合成run原始CSV经完整汇总/绘图，28图的84个PDF/SVG/PNG实际生成，验证全5/4/4点、
  每条件2seed、缺轮/错seed/模型篡改拒绝。这是工具验证，非真实性能结果。
  实际三个历史模型通过当前控制器formal loader及13依赖核验（0.870秒），新旧源码分别记录。
  真实make_plan/workflow/aggregate契约预检264jobs/66blocks/11conditions通过；未把占位run引用作为运行验收。
- 修改后`export JOBS=4`及`python3.8 tools/validate.py --skip-build`退出0：45 C++＋324 Python全通过，
  无跳过。报告`build/validation/20261022T081555.483901Z-cb6a7d7a/report.json`。
  三场景程序、模块库、waf配置缓存SHA未变，C++源差异为空；没有configure、waf构建或训练。
- 2026-10-22北京时间16:19:56以独立后台会话启动`all`，PID8901，身份与精确argv在新批次`plan/launch.json`。
  全部源码先封存，首12基准轮计入264；自动串行运行并最终出图，进度约每10秒写控制台。
  实验已进入running/test，首轮circle/NoForward/23001/基准；本条不宣称264轮或真实图已完成。
  `--run-timeout 900`限制单轮，`--stage-timeout 7200`用于汇总/绘图子命令，不是8小时仿真总时限。
- 新增[执行记录](QUICK_FIXED_MODEL_EXECUTION_20261022.md)，同步AGENTS/PROJECT/VALIDATION；
  记录模型与数据位置、启动/查看/立即停止/恢复/重新出图命令。现有同轮两次attempt上限保留并明确说明。
  运行期间不得修改封存代码或并发启动仿真/统一测试。后续实际结果以状态与完整manifest为准。
- 启动后首个circle基准四策略真实运行均complete；每轮6000请求终态闭合、共享输入一致、使用正式f51运行库。
  NN加载昨日circle checkpoint，5935条Python/C++动作逐条一致且全部接受；未采样/训练。
  只读审计`first-block-audit.json`已归档。北京时间16:28:25为5/264完成、第6轮grid/策略1运行中，
  不把终态闭合解释成100%交付，也不把首组验收解释成性能优势或整批完成。
