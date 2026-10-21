# 受控实验的正式训练入口

本入口实现 [2026-10-21 计划](../../../docs/ai/RETRAIN_AND_FIGURES_PLAN_20261021.md)
的新观测与监督契约。旧场景训练入口仍支持七列 CSV；这批正式结果不使用旧 CSV，
不混入旧 checkpoint。这里的命令准备和执行数据处理，不会运行 SUMO 或 waf。
如调用仿真或统一验证，仍须先 `export JOBS=4`，复用已有配置，不运行 configure。

## 输入与标签

使用成功完成的 NoForward 受控实验。运行时启用 `training_snapshots`，由生产运行器
封存 `training-observations.jsonl`、`face-roles.json`、请求、移动、收包日志和完成标记。
六特征顺序为 `x,y,speed,acceleration,angle,lane_index`，每条就是一个10×6的真实
hello窗口；不再对完成顺序的请求行做滑窗。空历史全零，短历史左填充必须与在线一致。

每个 `(run, request, OBU, source_rsu)` 保留第一次合格决策，同源后续记录作为重复诊断，
不同源分别保留。源RSU从 Router 回程Face首次收到对应Data时的车辆服务RSU为标签。
排除无线副本、缺回程、晚于请求截止期的回程、因果错误、失联和同纳秒关联歧义；
有回程但车辆TIMEOUT的合法样本仍纳入。DATA诊断行不增加请求终态或分母。
这是NoForward回程时刻的监督代理，不保证其他路径的反事实到达时刻或无线交付。

圆圈固定0–1类，方阵和蜘蛛网固定0–6类。构建器核验源manifest与原始文件哈希、
进程完成、采样计数、身份、候选RSU、填充及hello时间，输出逐条接受/排除索引。
缺类时保留`audit.json`并失败，不生成可接受的数据集manifest。

## 1. 显式run清单与mmap数据集

创建如下JSON。路径可为绝对路径或相对于这个JSON；`manifest_sha256`是对应生产
`manifest.json`的SHA256。每个split可以包含多个参数条件和run。

```json
{
  "schema_version": 1,
  "scenario": "grid",
  "split_version": "campaign-v1",
  "validation_only": false,
  "runs": [
    {"path": "/absolute/train-run", "split": "train", "seed_family": 20001,
     "condition_id": "baseline", "manifest_sha256": "<64 hexadecimal characters>"},
    {"path": "/absolute/validation-run", "split": "validation", "seed_family": 30001,
     "condition_id": "baseline", "manifest_sha256": "<64 hexadecimal characters>"},
    {"path": "/absolute/evaluation-run", "split": "evaluation", "seed_family": 40001,
     "condition_id": "baseline", "manifest_sha256": "<64 hexadecimal characters>"}
  ]
}
```

不同split不得共享master种子族或实际完整仿真种子元组。完整run、车辆、多源请求
均留在同一split；不按窗口随机切分。重复路径或run_id不能重复计入，
即使将同一run复制到另一目录也拒绝。三个split各自需覆盖完整类别。
`validation_only=true`仅用于合成夹具和pilot临时模型，不能进入正式图集。

从ns-3根目录运行：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 tools/experiments/build_training_dataset.py \
  --sources /absolute/sources.json --output-dir /absolute/new-dataset
```

输出`dataset-manifest.json`、`audit.json`和逐run的`.features.npy`、`.targets.npy`、
`.samples.jsonl`。mmap特征是在线转换后的float32；接受/排除索引保存原始观测行、
关联行、Face和回程时刻。原始double快照仍在封存源目录。
构建按run处理，训练以mmap及最多8个run映射的缓存读取，不把整个campaign堆入内存。
当前使用全部train样本，不做静默截断或子采样。

## 2. 各场景保留自己的训练入口

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 \
  contrib/vndn-nn-rd/ai-training/grid/train_tkan_lstm.py \
  --dataset-manifest /absolute/new-dataset/dataset-manifest.json \
  --output-root /absolute/new-model-root \
  --initialization-seeds 61021 61022 61023 \
  --epochs 100 --hidden-size 32 --grid-size 5 --spline-order 3 \
  --dropout 0.1 --batch-size 256 --learning-rate 0.001 --patience 15 \
  --threads 1 --device cpu
```

圆圈/蜘蛛网只替换入口目录；场景与数据manifest不一致时拒绝。
每个初始化独立训练。归一化仅从train估计；类别权重为最终train计数的
`N/(C*n_c)`，不叠加均衡采样器。保存、早停和跨初始化选模均使用验证macro-F1
优先、未加权交叉熵次优，再按较早epoch/较小种子确定顺序，默认容差`1e-10`。
模型结构和KAN模块沿用各场景代码；单双路径阈值维持现有0.10，不训练校准器。

唯一新目录内保存各初始化checkpoint和逐epoch JSONL、`training-config.json`、
所选模型的`training-history.csv`、`checkpoint.pt`和`model-manifest.json`。
正式checkpoint包含观测/标签契约、数据manifest哈希、源码来源、split版本、
初始化种子及归一化来源。冻结前再次核验数据与源文件未变。
训练期间只计算train/validation指标，不计算独立evaluation预测。

pilot使用同一入口，加`--allow-validation-only`；临时模型仍携带明确标记。
测试可以用1 epoch和较小hidden，但这些不是正式训练参数或论文质量结论。

## 3. 冻结后独立评估

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 \
  contrib/vndn-nn-rd/ai-training/formal_training.py \
  --model-manifest /absolute/model-output/model-manifest.json \
  --output-dir /absolute/new-evaluation \
  --bootstrap-repetitions 10000 --analysis-seed 61021
```

只评估`evaluation`，拒绝模型/数据哈希变化。输出`evaluation.json`和逐样本
`predictions.jsonl`，包括固定类别混淆矩阵、macro-F1、balanced accuracy、未加权CE、
Brier、15箱ECE、真实候选集下的单双路径覆盖及候选数，并保留run、种子族与历史长度/
交接子集。分类指标使用全场景类别，选站覆盖会按当时实际候选重新归一化。
置信区间按完整master种子族重采样；仅一个族时不伪造区间。
零有效样本的种子族仍保留；若重采样出现总样本为零，报告未定义次数并将区间标为不可用，
不通过丢弃这些重复样本来人为缩窄区间。
未知标签和排除样本独立报告，不当作正确预测。

评估JSON提供绘图需要的`scenario/split/model_sha256/label_values/confusion_matrix/
dataset_manifest_sha256`及选中训练曲线的路径与哈希。临时评估仍需显式
`--allow-validation-only`，输出不转为正式结果。

## 4. 在线严格加载

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 \
  scratch/vndn-grid-simulator/vndn-grid-tkan-gym.py \
  --model-file /absolute/model-output/checkpoint.pt --port 5555 --device cpu \
  --threads 1 --require-formal-contract --decision-log /absolute/new-decisions.jsonl
```

严格模式在连接Gym前拒绝旧契约、错场景、维度/类别/归一化错误以及非有限权重。
正式运行拒绝`validation_only`模型；pilot只有显式加`--allow-validation-only`才允许。
不带严格开关的旧入口仍能加载旧模型，但不能冒充本批正式模型。

概率日志保留当前观测的extraInfo、模型哈希、完整float32动作和
`expected_selected_rsu_ids`。后者是Python按当前规则的预期集合；
真正C++选择以生产`neural-decisions.jsonl`中的`selected_rsu_ids`为准。
一次控制器服务一轮仿真，由正式运行器逐轮管理，不同时占用相同端口。

## 行为验证

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 -m unittest discover \
  -s tools/experiments/tests -p test_training_dataset.py -v
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3.8 -m unittest discover \
  -s contrib/vndn-nn-rd/ai-training/tests -p 'test_*.py' -v
```

这些包含三个场景的小数据真实优化、模型保存/加载/推理与显式独立评估，不采集正式
SUMO数据。三场景真实输入和Gym链路仍由P2独立预实验验收。
