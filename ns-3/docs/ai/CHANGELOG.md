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
