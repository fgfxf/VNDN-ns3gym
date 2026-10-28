"""把封存的三维、箱线、CDF 和总流量数值写入独立可编辑绘图脚本。"""
import csv
import json
from pathlib import Path

import numpy as np
from matplotlib.cbook import boxplot_stats

from editable_plot_common import literal, make_script, nice_limits


SCENES = ('circle', 'grid', 'spidermap')
LABELS = dict(circle='Circle', grid='Grid', spidermap='Spider')
ALGORITHMS = ('Naive NDN', 'VTDF', 'RTVTDF', 'TKAN-PDF')


def _csv(path):
    with Path(path).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def _padded(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return (0., 1.)
    lower, upper = min(values), max(values)
    margin = (upper - lower) * .05 or max(abs(upper) * .05, 1.)
    return max(0., lower - margin), upper + margin


def _three_dimensional(scene, index, rows):
    data = []
    for strategy in range(4):
        selected = [row for row in rows if row['scene'] == scene and int(row['strategy']) == strategy]
        if not selected:
            raise ValueError('缺少三维分箱数据：{} / {}'.format(scene, strategy))
        data.append(dict(strategy=strategy,
                         x=[(float(row['bin_start_s']) + float(row['bin_end_s'])) / 2 for row in selected],
                         rtt_ms=[float(row['mean_success_rtt_ms'])
                                 if row['mean_success_rtt_ms'] else None for row in selected]))
    xlim = _padded([value for row in data for value in row['x']])
    zlim = _padded([value for row in data for value in row['rtt_ms']])
    parameters = '''# 可调外观：图宽高单位英寸；X=发送时刻，Y=算法编号，Z=成功请求平均 RTT。
FIGSIZE = (8.2, 4.6)
X_LIM = {xlim}
Y_LIM = (-0.15, 3.15)
Z_LIM = {zlim}
X_TICKS = None  # 例如 [20, 40, 60, 80, 100, 120, 140]；None 为自动刻度。
Z_TICKS = None  # 例如 [0, 100, 200, 300, 400, 500, 600]。
VIEW_ELEVATION = 30
VIEW_AZIMUTH = -60
LINES = ('-', '--', '-.', ':')
MARKERS = ('o', 's', '^', 'D')
'''.format(xlim=literal(xlim), zlim=literal(zlim))
    draw = '''def draw():
    fig = plt.figure(figsize=FIGSIZE)
    ax = fig.add_subplot(111, projection='3d')
    for series in DATA:
        strategy = series['strategy']
        # None 是没有成功请求的时间桶，使用 NaN 断线，不能补成 0。
        z = [np.nan if value is None else value for value in series['rtt_ms']]
        ax.plot(series['x'], [strategy] * len(z), z,
                color=COLORS[strategy], linestyle=LINES[strategy],
                marker=MARKERS[strategy], markersize=3)
    ax.set(xlabel='Interest generation time (s)', ylabel='Scheme',
           title=TITLE, xlim=X_LIM, ylim=Y_LIM, zlim=Z_LIM)
    ax.set_yticks(range(4), ('Naive', 'VTDF', 'RTVTDF', 'TKAN-PDF'), fontsize=7)
    if X_TICKS is not None:
        ax.set_xticks(X_TICKS)
    if Z_TICKS is not None:
        ax.set_zticks(Z_TICKS)
    ax.view_init(elev=VIEW_ELEVATION, azim=VIEW_AZIMUTH)
    fig.text(.92, .55, 'Mean successful RTT (ms)', rotation=90,
             ha='center', va='center')
    finish(fig, three_d=True)
    return fig
'''
    identifier = 'F{}-{}-rtt-3d'.format(index, scene)
    return identifier, make_script(identifier, parameters + 'TITLE = ' + literal(LABELS[scene]),
        draw, '# 完整时间分箱均值；保留原始精度及无成功的空桶。\nDATA = ' + literal(data),
        related=('C-all-scenes-rtt-3d',), description='固定代表种子的发送时间分箱 RTT；不是独立重复的置信区间。')


def _box(scene, index, successes):
    boxes, all_values = [], []
    for strategy in range(1, 4):
        values = successes[scene][strategy]
        all_values.extend(values)
        if not values:
            boxes.append(None)
            continue
        box = boxplot_stats(values, labels=[ALGORITHMS[strategy]])[0]
        boxes.append({key: value.tolist() if isinstance(value, np.ndarray) else float(value)
                      if isinstance(value, np.generic) else value for key, value in box.items()})
    full_limits = nice_limits(all_values)
    zoom_upper = max(float(np.percentile(all_values, 95)) * 1.08, np.finfo(float).eps) if all_values else 1.
    parameters = '''# 左图包含完整尾部；右图按原图放大至全部三算法合并 P95 的 1.08 倍。
FIGSIZE = (9.5, 4.35)
X_LIM = (0.5, 3.5)
Y_LIM = {ylim}
Y_TICKS = (None, None)  # 可分别改为明确刻度列表，如 ([0, 1000, 2000, 3000], [0, 100, 200])。
BOX_WIDTH = 0.5
'''.format(ylim=literal([full_limits, (0., zoom_upper)]))
    draw = '''def draw():
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE)
    titles = ('Full successful distribution', 'Body zoom; full tail shown at left')
    for panel, ax in enumerate(axes):
        for position, box in enumerate(DATA['boxes'], 1):
            if box is None:
                ax.text(position, .5, 'NA\\n(no success)', ha='center',
                        transform=ax.get_xaxis_transform(), fontsize=8)
                continue
            # 统计量和全部离群点已由原数据计算好；绘图时不重新读取实验。
            artists = ax.bxp([box], positions=[position], widths=BOX_WIDTH,
                             patch_artist=True, showfliers=True,
                             flierprops={'markersize': 2, 'alpha': .35})
            artists['boxes'][0].set_facecolor(COLORS[position])
        ax.set_xticks([1, 2, 3], ('VTDF', 'RTVTDF', 'TKAN-PDF'))
        ax.set(xlim=X_LIM, ylim=Y_LIM[panel], ylabel='Successful RTT (ms)', title=titles[panel])
        if Y_TICKS[panel] is not None:
            ax.set_yticks(Y_TICKS[panel])
    finish(fig)
    return fig
'''
    data = dict(boxes=boxes, pooled_success_count=len(all_values))
    identifier = 'F{}-{}-rtt-box'.format(index, scene)
    return identifier, make_script(identifier, parameters, draw,
        '# 箱统计：med=中位数，q1/q3=四分位数，whislo/whishi=须，fliers=全部离群点。\n'
        '# 仅保留成功请求；无抽样、无舍弃尾部。大量数值集中在此，通常只需改顶部外观。\nDATA = ' + literal(data),
        description=LABELS[scene] + '：两个种子的全部成功 RTT 箱线图；包级分布不等于独立重复。')


def _cdf(scene, index, successes, handover):
    data = {}
    for name, groups in (('all_success', successes), ('handover_success', handover)):
        data[name] = []
        for strategy in range(4):
            values = groups[scene][strategy]
            x, counts = np.unique(values, return_counts=True)
            cdf = np.cumsum(counts) / len(values) if values else np.array([])
            data[name].append(dict(strategy=strategy, x=x.tolist(), cdf=cdf.tolist(), count=len(values)))
    x_limits = [_padded([x for row in data[name] for x in row['x']])
                for name in ('all_success', 'handover_success')]
    parameters = '''# 两个子图依次为全部成功请求、共同交接组内的成功请求。
FIGSIZE = (10.0, 4.35)
X_LIM = {xlim}
Y_LIM = (0.0, 1.0)
X_TICKS = (None, None)  # 可分别指定两个子图的 RTT 刻度列表。
Y_TICKS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
LINES = ('-', '--', '-.', ':')
'''.format(xlim=literal(x_limits))
    draw = '''def draw():
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE)
    keys = ('all_success', 'handover_success')
    titles = ('All successful requests', 'Common handover cohort, successful')
    for panel, (ax, key) in enumerate(zip(axes, keys)):
        for series in DATA[key]:
            if not series['count']:
                continue
            strategy = series['strategy']
            ax.step(series['x'], series['cdf'], where='post', color=COLORS[strategy],
                    linestyle=LINES[strategy], label=ALGORITHMS[strategy], linewidth=1.1)
        ax.set(xlabel='Successful RTT (ms)', ylabel='Empirical cumulative probability',
               xlim=X_LIM[panel], ylim=Y_LIM, title=titles[panel])
        ax.set_yticks(Y_TICKS)
        if X_TICKS[panel] is not None:
            ax.set_xticks(X_TICKS[panel])
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=4, fontsize=8)
    finish(fig)
    return fig
'''
    identifier = 'D{:02d}-{}-rtt-ecdf'.format(index, scene)
    return identifier, make_script(identifier, parameters, draw,
        '# 完整精确 ECDF：x 为每个不同 RTT，cdf 保留重复值的全部质量，count 为原成功数。\n'
        '# 不是降采样或分位点近似；这些完整数值可能较长。\nDATA = ' + literal(data),
        description=LABELS[scene] + '：全部成功请求及共同交接成功组的精确经验分布。')


def _traffic(source):
    aggregate = json.loads((source / 'source-tables/aggregate.json').read_text(encoding='utf-8'))
    rows = _csv(source / 'source-tables/plot-summary.csv')
    baseline = aggregate['baseline_condition_id']
    data = {}
    for scene in SCENES:
        data[scene] = []
        for strategy in range(4):
            selected = [row for row in rows if row['scene'] == scene and int(row['strategy']) == strategy
                        and row['condition_id'] == baseline and row['metric'] == 'network_mbit']
            if len(selected) != 1:
                raise ValueError('基准流量必须有且仅有一行：{} / {}'.format(scene, strategy))
            row = selected[0]
            data[scene].append(dict(strategy=strategy, estimate=float(row['estimate']),
                run_sd=float(row['run_sd']) if row['run_sd'] else None,
                run_values=json.loads(row['run_values'])))
    extremes = [row['estimate'] + (row['run_sd'] or 0.) for rows in data.values() for row in rows]
    extremes.extend(value for rows in data.values() for row in rows for value in row['run_values']
                    if value is not None)
    parameters = '''# 三场景共用纵轴，黑点为每次运行值，误差线为两个运行的样本 SD。
FIGSIZE = (11.5, 4.35)
X_LIM = (-0.5, 3.5)
Y_LIM = {ylim}
Y_TICKS = None  # 可指定如 [0, 500, 1000, 1500, 2000]。
BAR_WIDTH = 0.65
'''.format(ylim=literal(nice_limits(extremes)))
    draw = '''def draw():
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE, sharey=True)
    for scene, ax in zip(SCENES, axes):
        for point in DATA[scene]:
            strategy = point['strategy']
            ax.bar(strategy, point['estimate'], width=BAR_WIDTH, color=COLORS[strategy],
                   hatch=HATCHES[strategy], edgecolor='black', linewidth=.55)
            values = [value for value in point['run_values'] if value is not None]
            ax.scatter([strategy] * len(values), values, color='black', alpha=.5, s=18, zorder=3)
            if point['run_sd'] is not None:
                low = point['estimate'] - point['run_sd']
                high = point['estimate'] + point['run_sd']
                ax.vlines(strategy, low, high, color='black', linewidth=1)
                ax.plot([strategy, strategy], [low, high], '_', color='black')
        ax.set_xticks(range(4), ('Naive', 'VTDF', 'RTVTDF', 'TKAN-PDF'), rotation=15, fontsize=8)
        ax.set(xlim=X_LIM, ylim=Y_LIM, title=SCENE_LABELS[scene])
        if Y_TICKS is not None:
            ax.set_yticks(Y_TICKS)
    axes[0].set_ylabel('NDN L3 outgoing traffic (Mbit)')
    finish(fig)
    return fig
'''
    identifier = 'F27-baseline-total-traffic'
    return identifier, make_script(identifier, parameters, draw, 'DATA = ' + literal(data),
        description='三场景基准条件全网 NDN L3 出站流量；包含测量与排空，不包括 MAC 开销。')


def _combined():
    parameters = '''# 组合图自动读取三个 F21/F22/F23 单图的 DATA，不保存第二份数值。
FIGSIZE = (16.5, 5.2)
X_LIM = None  # None 复用单图范围；也可填统一的 (20, 140)。
Y_LIM = (-0.15, 3.15)
Z_LIM = None  # None 复用各单图范围；也可填统一的 (0, 1000)。
X_TICKS = None
Z_TICKS = None
VIEW_ELEVATION = 30
VIEW_AZIMUTH = -60
SOURCES = ('F21-circle-rtt-3d.py', 'F22-grid-rtt-3d.py', 'F23-spidermap-rtt-3d.py')
'''
    draw = '''def draw():
    fig = plt.figure(figsize=FIGSIZE)
    for panel, filename in enumerate(SOURCES):
        single = load_plot(filename)  # 导入只读参数，不会运行单图的 main。
        ax = fig.add_subplot(1, 3, panel + 1, projection='3d')
        for series in single['DATA']:
            strategy = series['strategy']
            z = [np.nan if value is None else value for value in series['rtt_ms']]
            ax.plot(series['x'], [strategy] * len(z), z, color=COLORS[strategy],
                    linestyle=single['LINES'][strategy], marker=single['MARKERS'][strategy], markersize=3)
        ax.set(xlabel='Interest generation time (s)', ylabel='Scheme',
               title='({}) {}'.format('abc'[panel], single['TITLE']),
               xlim=X_LIM if X_LIM is not None else single['X_LIM'], ylim=Y_LIM,
               zlim=Z_LIM if Z_LIM is not None else single['Z_LIM'])
        ax.set_yticks(range(4), ('Naive', 'VTDF', 'RTVTDF', 'TKAN-PDF'), fontsize=7)
        ax.set_zlabel('Mean successful RTT (ms)', fontsize=8)
        if X_TICKS is not None:
            ax.set_xticks(X_TICKS)
        if Z_TICKS is not None:
            ax.set_zticks(Z_TICKS)
        ax.view_init(elev=VIEW_ELEVATION, azim=VIEW_AZIMUTH)
    finish(fig, three_d=True)
    return fig
'''
    identifier = 'C-all-scenes-rtt-3d'
    return identifier, make_script(identifier, parameters, draw, '',
        description='三个固定代表种子的 RTT 分箱组合图；数据实时读取对应单图 Python 文件。')


def generate(source):
    """只在创建包时读取封存表；生成后的各脚本仅使用本文件硬编码数值。"""
    source = Path(source)
    requests = _csv(source / 'source-tables/baseline-requests.csv')
    bins = _csv(source / 'time-bin-rtt.csv')
    successes = {scene: {strategy: [] for strategy in range(4)} for scene in SCENES}
    handover = {scene: {strategy: [] for strategy in range(4)} for scene in SCENES}
    for row in requests:
        if row['terminal'] != 'DATA':
            continue
        scene, strategy, value = row['scene'], int(row['strategy']), float(row['rtt_ms'])
        if not np.isfinite(value) or value < 0:
            raise ValueError('成功 RTT 必须非负且有限')
        successes[scene][strategy].append(value)
        if row['common_handover'] == '1':
            handover[scene][strategy].append(value)
    scripts = {}
    for index, scene in enumerate(SCENES):
        for identifier, script in (_three_dimensional(scene, index + 21, bins),
                                   _box(scene, index + 24, successes),
                                   _cdf(scene, index + 1, successes, handover)):
            scripts[identifier] = script
    scripts.update([_traffic(source), _combined()])
    return scripts
