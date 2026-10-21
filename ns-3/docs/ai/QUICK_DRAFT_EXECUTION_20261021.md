# 10 小时初稿批次：参数、运行和证据

用户最新明确授权“同意并执行10小时初稿方案”。本批次独立保存于
`data/experiments/retrain-quick-20261021/`，不恢复或覆盖旧批次。
10小时是工作预算，不是已测得的完成承诺；真实神经推理和重条件耗时仍需运行确认。
15:00:11北京时间已启动真实采样，后续按顺序自动训练、正式对比及出图。
最新完成轮数以本文进度命令和`plan/pipeline-state.json`为准，不能把启动当作图集完成。

## 本批次固定范围

- `quick-draft-v1`：圆圈、方阵、蜘蛛网，四种策略，三个自变量、五个指标。
- 每轮20秒预热、120秒测量、3.5秒排空，总143.5仿真秒。
- 8个唯一条件，共48轮采样（24训练、12验证、12独立评估）、192轮正式对比。
  每条件两个配对正式种子52001、52002；正式第一组12轮覆盖三场景基准四策略。
- 采样种子为23001–23024、33001–33012、43001–43012，按完整run隔离。
  不混入旧300秒数据，不自动增加采样量；缺类或无跨站目标需报告。
- 每场景一个固定TKAN-LSTM模型；一次初始化62021，最多30epoch，验证早停patience=5。
  hidden_size=32、grid_size=5、spline_order=3、dropout=0.1、batch_size=256、
  learning_rate=0.001、CPU单线程；模型冻结后不按正式结果重新调参。
- 15张导师主图与10张旧风格补图，导出PDF/SVG/PNG及本地HTML预览。
  图中明确标记探索初稿、在线n=2；展示实际重复点及SD，不宣称统计显著性。
- 保留本次调度器修复、所有C++协议与统计口径，复用现有二进制。
  仅运行`--no-build`入口；不执行configure或编译。

| 扫描 | 取值 | 其余固定值 |
|---|---|---|
| 首次业务Interest总数 | 1500 / 6000 / 12000 | 10车、30km/h |
| 速度设置 | 10 / 30 / 50km/h | 10车、6000请求 |
| 车辆数 | 5 / 10 / 15 / 20 | 30km/h、每车5Hz，对应3000/6000/9000/12000请求 |

三条扫描共用10车、30km/h、6000请求的基准，因此不是10个独立条件。
速度横轴是预设速度，实际SUMO车速另存；平均RTT仅成功请求，须结合满足率读图。
负载为网络Face的L3发送字节，二次转发为应用显式提交的额外Data数，不能改称MAC空口成本。

## 用户操作

本次用户已授权自动从采样运行到出图。`prepare`仍只准备模型；只有显式`all`才连续跑完整批次。
关闭查看进度的窗口不会停止后台实验。关机后需重新执行启动命令，程序核验并跳过已完成轮次。

查看进度（Ctrl+C只退出查看）：

```bash
cd /home/fgfxf/ndnSIM/ns-3
python3.8 tools/experiments/run_campaign_pipeline.py status --root data/experiments/retrain-quick-20261021 --watch
```

立即停止本批次，保留数据：

```bash
cd /home/fgfxf/ndnSIM/ns-3
python3.8 tools/experiments/run_campaign_pipeline.py stop --root data/experiments/retrain-quick-20261021
```

启动或继续同一批次（已有任务运行时不要重复启动）：

```bash
cd /home/fgfxf/ndnSIM/ns-3
export JOBS=4
python3.8 tools/experiments/run_campaign_pipeline.py all --root data/experiments/retrain-quick-20261021 --profile quick-draft-v1 --training-config data/experiments/retrain-quick-20261021/plan/training-config.json --run-timeout 900 --stage-timeout 7200 --python /usr/bin/python3.8
```

进度显示阶段、当前场景/策略/条件/种子、本阶段第几轮、累计完成与剩余轮数、本次和累计已用时间。
`sample-train/validation/evaluation`均为无策略采样；`train`才是训练模型；`test`为四策略对比；`figures`为出图。
不显示预计剩余时间。所有运行日志及失败attempt保留。

## 实施与恢复边界

- Python新增quick参数及完整执行入口，旧compact/full参数与`prepare`停止边界保留。
- 训练新增稳定会话的epoch保存及完成候选复用；旧推理`.pt`本身不等于续训状态。
  训练保存对象包含当前/最佳权重、Adam、随机状态、训练shuffle状态、早停及数据/配置身份。
- 现有运行恢复会核验已完成manifest、输入和输出哈希；当前轮中断重跑，不尝试恢复半轮仿真内存。
  现有每job两次attempt上限仍保留，多次中断达上限需明确调整重试预算。
  本任务没有实现旧批次迁移、通用菜单或完整掉电故障注入验收；不得把所有恢复计划写成已上线。
- 运行前冻结源码与配置并归档；运行期间不要改脚本、模型、仿真源码或输入文件。
  文档进展可追加；正式数据和历史数据不删改。

## 验证与运行进展

测试先行日志位于`build/validation/quick-draft-20261021/`。
参数部分旧30项通过、新7项有效失败后37项通过；图表旧44项通过、新7项有效失败后通过，旧44项回归通过；
连续执行入口旧10项通过、新4项有效失败后14项通过。图表测试使用合成夹具，仅证明渲染和核验行为，不能冒充真实论文图。
训练相关13项、原workflow34项、quick配置与实际计划集成3项通过；三场景真实TKAN经稳定session保存并由现有控制器加载推理通过。
整合`python3.8 tools/validate.py --skip-build`退出0：8个C++套件和283项Python测试全部通过，无跳过。
报告：`build/validation/20261021T065832.662374Z-25b8d4da/report.json`。
没有configure、编译或修改C++。

15:00:11北京时间后台启动`all`，PID1881，身份及准确命令在`plan/launch.json`；
终端记录`plan/console.log`。真实首轮为circle/baseline/seed23001/NoForward，
已核查现有二进制、`waf --run-no-build -j 4`及独立SUMO输入实际运行。
冻结源码SHA256：`142365d8cc9af24f8028f6cc5bf11dd30af9baa0ac7c9ecb538ac3e9487c90a4`。
此前无关SUMO11059/3401端口保持不动，本次串行实验使用3400。
本条启动记录为采样0/48、正式0/192；模型和真实论文图尚未产生，后续追加实际结果。

15:04运行核查：采样2/48完成，正式0/192。圆圈基准6000请求用时109.07秒，
圆圈低负载1500请求用时102.22秒；均退出0、manifest complete，输入/输出哈希和源身份校验通过。
首轮真实生成6000首次请求、2169成功、3831超时，45次交接；这是NoForward单轮采样，不能推广为四策略效果结论。
当前自动执行第三轮circle/12000请求/seed23003，未触发构建，完成数据保留。
