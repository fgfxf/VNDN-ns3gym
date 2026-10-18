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
