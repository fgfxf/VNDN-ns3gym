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
