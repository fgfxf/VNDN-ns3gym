# 精简实验执行记录与手动入口

日期：2026-10-21，Asia/Shanghai。起点：`c9492aa`，保留前一轮三份计划文档差异。
依据：[已确认方案](SLOWDOWN_AND_REDUCED_EXPERIMENT_PLAN_20261021.md)。

用户授权执行调度器修复、短对照、48～72轮采样、训练与模型冻结、独立评估；
**480轮正式四策略对比留给用户手动启动**。旧`retrain-20261021`队列不恢复。

## 当前执行状态

**已按用户“先结束任务”停止准备流程；不自动恢复。**
生产调度器最小修复、针对性及整合回归、12轮三场景短对照全部通过。
13:32:38（北京时间）已启动新批次准备流程，PID7402，先执行24训练＋12验证＋12独立评估采样。
运行约4.7分钟后按用户指令停止，采样1/48完整通过、47轮尚未完成；中断attempt和原始数据保留。
训练/模型评估尚未开始；正式测试0/480，并留给用户手动执行。
停止命令`run_campaign_pipeline.py stop --root data/experiments/retrain-compact-20261021`退出0，
状态为`interrupted`，本队列及其仿真子进程均已退出；旧的用户SUMO进程未触碰。

新目录：`data/experiments/retrain-compact-20261021/`。
状态：`plan/pipeline-state.json`；人读日志：`plan/prepare-terminal.log`；启动记录：`plan/prepare-launch.json`。
源码已封存至`plan/source.tar.gz`和`plan/source-seal.json`，源码哈希为
`2c410ef3fd0504441e6fe9c7fc4c2a2e78d3b6c6b9284d9776a48af725919910`。

## 1. 调度器修复证据

- 修改范围：`src/ndnSIM/ndn-cxx/ndn-cxx/util/scheduler.cpp::scheduleNext()`增加9行，
  在重排队首唤醒前Remove旧ns-3事件并清理句柄，保证唯一待执行唤醒；转发协议和模型结构不变。
- 新测试：`src/ndnSIM/tests/unit-tests/ndn-cxx/scheduler.t.cpp`，共12例。
  使用真实模拟时钟和内核事件计数，覆盖不同期限/同时间/零延时、取消、析构、context与同纳秒UID顺序。
- 实现前真实红灯：100个业务回调产生5050次内核事件；12例中8失败、4通过，退出201。
  最初一次新测试编译API错误另存，未把编译失败作为行为红灯。
- 最小修复后：100回调仅100次内核事件；新增与Face/L3/NCC相关回归22例、381断言PASS。
  另用现有test-runner执行八个VNDN套件，全部PASS。
- 没有configure或profile变更。`export JOBS=4`后执行
  `./waf build -j 4 --targets=ndnSIM-unit-tests`；红灯阶段只编译新增测试对象并链接，5.542秒；
  修复阶段只编译scheduler.cpp，链接ndnSIM库和测试程序，9.532秒。
  两次均先检查Waf任务图，没有全量重编译。
- 证据：`build/validation/scheduler-fix-20261021/report.json`、`red-scheduler.log`、
  `green-scheduler-regression.log`、`vndn-regressions.json`。
  旧库/场景程序保存在该目录`before/`，哈希清单`before-manifest.json`。

## 2. 短场景对照

`build/validation/scheduler-fix-20261021/scene_ab.py`使用隔离旧/新库，直接启动已构建程序，
`ldd`记录实际库解析；不反复回退生产源码，不调用waf构建。
三场景各比较NoForward与神经分支，后者使用明确标记的均匀测试控制器；这些是工程数据。
seed=11021，速度30km/h；circle/grid各10车、spidermap20车；
预热5秒、测量30秒、排空3.5秒，每车5Hz。每轮墙钟上限120秒，超过则保留失败。
记录墙钟、文件可观测进度、RSS和完整原始事件；真实模型的最终在线行为由用户正式首批验证。

全部12轮完成：

| 场景 | 策略 | 旧版墙钟秒 | 修复版墙钟秒 |
|---|---|---:|---:|
| circle | NoForward | 65.00 | 30.80 |
| circle | Neural测试控制器 | 44.40 | 33.22 |
| grid | NoForward | 38.84 | 28.82 |
| grid | Neural测试控制器 | 50.22 | 30.04 |
| spidermap | NoForward | 87.31 | 52.39 |
| spidermap | Neural测试控制器 | 101.36 | 48.36 |

六对全部汇总指标去掉run_id后完全一致；请求记录多重集相同且时间单调，差异仅为同纳秒行顺序。
训练快照及神经动作去run_id后逐行一致；packet-l3/data-rx/mobility/data-attempts逐字节一致。
神经分支各场景分别1494/1407/1771次决策，测试控制器与C++完成数一致，全部ACCEPTED，无fallback。
蜘蛛网观测窗口中，修复版20秒前后推进速度相近，旧版后段明显退化。
文件缓冲、短案例及同机测试活动限制了精确加速比解释，不能外推480轮完整工期或真实模型效果。
完整比较见`scene-ab/paired-comparison.json`及`.md`，比较脚本为该证据目录的`compare_scene_ab.py`。

## 3. 工具与数据约束

- 新profile `compact-exploratory-v1`明确列出48项采样作业，正式矩阵为480；不通过validation_only绕过检查。
- `run_experiment.py --no-build`使用现有二进制并记录前后依赖哈希；新增子进程退出竞态回归，
  防止两次poll之间发生的非零退出被误记为成功。
- 准备流程：采样三个split → 数据集 → 覆盖报告 → 每场景3次初始化训练 → 冻结三模型 → 独立评估。
  只在缺类/缺跨站样本等覆盖不足时，按已批准上限追加最多24轮；不按策略优劣补采或挑种子。
- 运行入口区分`prepare`、`formal`、`figures`。准备完成状态为`ready-for-formal`，不会接着跑正式测试。
- 进度按独立作业统计，失败attempt不当作完成轮数。显示阶段、场景/条件/策略/seed、
  当前轮、完成/剩余数、本次动作和累计用时、当前轮耗时；不显示剩余时间预测。
- 训练参数在采样开始前封存：每场景初始化61021/61022/61023，hidden32、batch256、最多100epoch、
  patience15、CPU单线程，保持0.10选路规则。完整配置在新批次`plan/training-config.json`。
- 整合回归：`python3.8 tools/validate.py --skip-build`通过13个实际步骤（8个C++套件及5组Python，
  合计256项Python测试，无跳过）；这里跳过的是已验证的编译，不是测试。
  报告：`build/validation/20261021T052609.726576Z-11058bc9/report.json`。
  最后新增的正式首12轮排序用例另以目标＋相关30项通过，见`compact-design-20261021/green-formal-order.log`。

## 4. 用户手动执行命令

以下命令在准备完成、状态为`ready-for-formal`后使用；当前不代表已就绪。
默认新批次路径为`data/experiments/retrain-compact-20261021`，最终状态与模型见后续更新。

目前准备流程已由用户停止，**尚不能开始formal**。用户重新授权后，可先续跑准备：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
python3.8 tools/experiments/run_campaign_pipeline.py prepare \
  --root data/experiments/retrain-compact-20261021 \
  --training-config data/experiments/retrain-compact-20261021/plan/training-config.json
```

这会复用已通过的1轮，对中断轮创建新的attempt；不会把中断前缀当作完整样本。

运行正式480轮（顺序运行，中断后同一命令续跑，仅复用通过校验的完整轮次）：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
python3.8 tools/experiments/run_campaign_pipeline.py formal \
  --root data/experiments/retrain-compact-20261021
```

执行窗口每10秒显示进度；也可另开终端查看：

```bash
cd /home/fgfxf/ndnSIM/ns-3
python3.8 tools/experiments/run_campaign_pipeline.py status \
  --root data/experiments/retrain-compact-20261021 --watch
```

状态查看窗口按Ctrl+C只关闭查看。运行窗口按Ctrl+C会停止本次队列并清理其子进程；
也可另开终端主动停止，已完成数据保留：

```bash
python3.8 tools/experiments/run_campaign_pipeline.py stop \
  --root data/experiments/retrain-compact-20261021
```

正式480轮全部通过后生成论文图：

```bash
python3.8 tools/experiments/run_campaign_pipeline.py figures \
  --root data/experiments/retrain-compact-20261021
```

输出位置为新批次`workflow/figures/all/attempt-*/figures/`，包含PDF、SVG、PNG和`figure-index.json`。
15张主图、7张旧风格补图、3张混淆矩阵共25张编号图；旧固定K补充图不生成空壳。
实验运行期间不要修改已冻结源码/模型/输入；若确需修正，应先停止并明确新的版本边界。
