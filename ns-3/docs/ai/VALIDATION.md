# 测试与验收指南

开发规则见 [工作区 AGENTS.md](../../../AGENTS.md)，项目结构见 [PROJECT.md](PROJECT.md)。
本文件中的命令除特别说明外均在 `/home/fgfxf/ndnSIM/ns-3` 执行。

## 修改前后必须做什么

1. 先选择与修改相关的现有测试，运行并保存基线。
2. 新功能/修复先写行为测试，确认旧实现因预期行为不符而失败；保留失败原因和命令。
3. 完成实现后运行该测试和相关回归；必要的场景断言也必须通过。
4. 将命令、退出码、实际断言、配置及报告位置记入 [CHANGELOG.md](CHANGELOG.md)。
   报告记录测试结果；它无法证明测试一定先于代码编写，先后证据需在变更记录中明确保存。

纯文档改动检查事实与链接；重构先建立行为保护。
失败、超时、缺依赖、跳过或零项测试都不能标为验收通过。

## 环境与首次启用测试

所有 waf 及间接调用 waf 的操作必须先限制并行数：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
```

当前研究环境使用 Python 3.8、debug 构建、MPI、Boost Python 38、SUMO / TraCI、ns3-gym。
先检查本地 `.lock-waf_linux_build` 的配置选项以及 `build/c4che/_cache.py` 的 `ENABLE_TESTS`，
不要直接覆盖其他机器已有的编译配置，也不要将包含完整环境变量的锁文件公开到日志。

初始化时 tests 原为禁用；以下命令在本机保留原有有效选项并启用测试：

```bash
export JOBS=4
./waf configure -d debug --enable-sudo --enable-mpi --enable-examples \
  --with-python=/usr/bin/python3.8 --boost-python=38 --enable-tests
```

`--enable-sudo` 是这台机器原有配置，不能当作其他环境的必需选项。
原命令中参数不完整的 `--with-openflow --with-nsc` 未照搬；两个集成原来均未启用。
配置缓存和构建产物不纳入 Git，新检出项目仍需在本地配置。

## 统一单元回归入口

```bash
export JOBS=4
python3.8 tools/validate.py
```

入口自动定位项目根目录，子进程强制 `JOBS=4`。依次执行：

1. 检查测试已启用，不自行重新 configure。
2. `./waf build -j 4 --targets=test-runner`，仅构建测试运行器及依赖。
3. `vndn-rsu-forwarding-policy` 和 `vndn-neural-return-selection` 两个 C++ 套件。
4. `ai-training/circle/tests` 的 Python unittest。

标准 ns-3 test-runner 链接所有启用模块的测试库，首次构建会编译部分上游测试。
实际执行范围仍只有两个研究套件；不意味着所有 ns-3 测试都已运行。

报告保存在 `build/validation/<唯一运行目录>/report.json`，附每步日志、C++ XML 和 Python 测试统计。
只有选中的套件实际执行并通过、Python 测试数大于零且未跳过时才成功。
失败或超时立即停止并返回非零状态，不能把未执行的后续步骤认作通过。

- `--python /path/to/python3.8`：指定具备 NumPy、PyTorch 等依赖的测试解释器。
- `--build-timeout 1800`、`--timeout 600`：构建和每个测试步骤的墙钟超时（秒）。
- `--skip-build`：仅对已明确构建过的同一份源码复测；报告会注明跳过构建。
  不可用于声称源码变更已完成编译验证。

修改验收工具本身还要执行：

```bash
python3.8 -m unittest discover -s tools/tests -p 'test_validate.py' -v
```

这些是工具的行为测试，使用临时测试夹具，不替代真实 C++ / 模型测试。

## 手动诊断命令

```bash
export JOBS=4
./waf build -j 4 --targets=test-runner
python3.8 test.py --nowaf --suite=vndn-rsu-forwarding-policy
python3.8 test.py --nowaf --suite=vndn-neural-return-selection
python3.8 -m unittest discover \
  -s contrib/vndn-nn-rd/ai-training/circle/tests -p 'test_*.py' -v
```

本项目跳过 test.py 自动构建的选项是 `--nowaf`。test.py 会将 SKIP 计入成功，
所以仅退出码 0 不足以证明套件通过；正式记录优先使用统一入口及其断言结果。

## 三场景验收与复现实验

共用转发、NFD 控制/PIT 或跨场景逻辑改动，除单元回归外还需针对圆圈、方阵、蜘蛛网验收。
先建立能触发目标行为的复现与断言，再改实现。仅启动成功或运行几秒不能证明发生过切换。

```bash
export JOBS=4
./waf build -j 4 --targets=vndn-circle-simulator,vndn-grid-simulator,vndn-spidermap-simulator
```

以下为圆圈 NoForward 的可复现运行模板；改用另两个目标时，设置相应时长（默认 230 秒）：

```bash
export JOBS=4
timeout --signal=TERM --kill-after=10s 300s ./waf --run \
  "vndn-circle-simulator --s=80 --rsu-forward-strategy=0 --sumo-gui=0 --save-data=1 --RngSeed=1 --RngRun=1 --sumo-seed=1 --srand-seed=1"
```

这是运行模板，不是自动验收：必须核对进程退出码、仿真完成状态和与本次修改相关的断言。
时限应按负载设置；timeout 不能解释成成功。

神经网络策略须显式使用 `--rsu-forward-strategy=3`，先启动对应场景的 Python 控制器，
例如 `python3.8 scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py --model-file /absolute/path/model.pt --port 5555`，
仿真端指定 `--open-gym-port=5555`。完成或失败后都要收敛本次控制器与 SUMO 进程。
方阵和蜘蛛网必须提供匹配本场景全部 RSU 标签的模型；不能用圆圈两类模型代替七类模型。
同机仿真默认共用 SUMO 3400 / gym 5555 端口，应顺序运行，避免端口冲突和产物混杂。

场景验收至少记录：

- 代码版本/未提交差异、场景、策略、时长、ns-3 Seed/Run、SUMO seed、C rand seed。
- 模型路径与校验值、训练数据来源、标签映射、阈值和网络配置。
- 确认实际发生目标切换；对同一请求追踪预测 RSU、Router 控制消息、PIT 和最终 Data 交付。
- 核对目标 RSU 可以为原基站或其他基站；按修改范围覆盖单双路径、回退、超时等分支。
- 在运行前确定断言及评价指标，按固定种子和一致负载比较基线，保存配置、日志和统计文件。

当前统一入口只提供单元回归，**尚未自动断言上述三场景端到端行为**。
以后修改这些行为时应补上对应验收，不能以当前入口绿灯替代。
`scratch/` 下现有批量采样脚本可能吞掉单轮失败；不要用它们的整体退出码验收。

## 已有单元覆盖的边界

| 层次 | 已覆盖 | 仍需针对任务补充 |
|---|---|---|
| C++ 策略 | 最近 RSU、空候选、单双路径概率选择、长度不匹配 | NFD/PIT 生命周期、无线交付、控制时序 |
| Python | 窗口时序与运行隔离、输出形状和反向传播 | 模型泛化、实际 checkpoint 与跨进程推理一致性 |
| 仿真 | 已有三个场景入口 | 固定种子下切换与回程的自动断言、统计意义上的效果 |

现有测试通过仅能支持相应覆盖范围。科研有效性还需要合适的对照、重复实验和统计分析。
