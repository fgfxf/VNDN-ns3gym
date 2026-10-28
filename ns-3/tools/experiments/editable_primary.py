"""将封存统计值展开为15份主图脚本和9份引用主图数据的组合脚本。

仅在导出时读取 aggregate.json。生成的用户脚本不用读取实验记录，
RTT中心及误差线直接保留原 estimate/run_sd，不重新估计统计量。
"""
import importlib.util
import json
import math
from pathlib import Path


SCENES = ('circle', 'grid', 'spidermap')
SCENE_LABELS = dict(circle='Circle', grid='Grid', spidermap='Spider')
SCANS = ('interest', 'speed', 'vehicles')
METRICS = ('isr_percent', 'mean_success_rtt_ms', 'network_mbit',
           'control_mbit', 'extra_data_app_attempts')
X_LABELS = dict(interest='Number of generated Interest packets',
                speed='Vehicle speed setting (km/h)', vehicles='Number of vehicles')
Y_LABELS = dict(isr_percent='Interest satisfaction rate (%)',
                mean_success_rtt_ms='Mean RTT of satisfied Interests (ms)',
                network_mbit='NDN L3 outgoing traffic (Mbit)',
                control_mbit='Custom control L3 outgoing traffic (Mbit)',
                extra_data_app_attempts='Extra Data application submissions')
SHORT_LABELS = ('Interest satisfaction rate', 'Average successful RTT',
                'Network overhead', 'Control overhead', 'Extra Data submissions')


def _common():
    spec = importlib.util.spec_from_file_location(
        'editable_primary_common', Path(__file__).with_name('editable_plot_common.py'))
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    return common


def _ticks(limits):
    """导出整洁的固定刻度，任何刻度都不得落到可见范围以外。"""
    lower, upper = limits
    target = max((upper - lower) / 6., 1e-12)
    magnitude = 10 ** math.floor(math.log10(target))
    step = next(value * magnitude for value in (1., 2., 2.5, 4., 5., 10.)
                if value * magnitude >= target)
    first = math.ceil(lower / step)
    last = math.floor(upper / step)
    return [round(index * step, 10) for index in range(first, last + 1)]


def _extent(series):
    values = []
    for item in series:
        for point in item['points']:
            mean, sd = point['estimate'], point['run_sd']
            if mean is not None:
                values.extend((mean - (sd or 0.), mean + (sd or 0.)))
    return values


def _main_script(common, identifier, data, scan):
    values = [value for series in data['scenes'].values() for value in _extent(series)]
    limits = common.nice_limits(values, percent=identifier.endswith('-isr_percent'))
    parameters = '''# ===== 可修改的绘图参数 =====
# 三场景共用Y轴范围；上限包含所有柱高及误差线，不会截去Grid等场景的高柱。
FIGSIZE = (12.8, 4.35)
# 柱状图的内部X坐标为0、1、2……；真实请求数/速度/车辆数见末尾DATA的xlabels。
X_LIM = {xlim}
Y_LIM = {ylim}
Y_TICKS = {ticks}
LEGEND_COLUMNS = 4
'''.format(xlim=common.literal((-.6, len(data['xlabels']) - .4)),
           ylim=common.literal(limits), ticks=common.literal(_ticks(limits)))
    drawing = '''def draw():
    """只创建当前图；保存图片及更新组合图由文件末尾入口负责。"""
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE, sharey=True)
    for index, (scene, ax) in enumerate(zip(SCENES, axes)):
        draw_bars(ax, DATA["xlabels"], DATA["scenes"][scene])
        ax.set_xlim(X_LIM)
        ax.set_ylim(Y_LIM)
        ax.set_yticks(Y_TICKS)
        ax.set_xlabel(DATA["xlabel"] + "\\n\\n({}) {}".format(
            "abc"[index], SCENE_LABELS[scene]))
    axes[0].set_ylabel(DATA["ylabel"])
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=LEGEND_COLUMNS, fontsize=8)
    finish(fig)
    return fig
'''
    data_code = ('# ===== 固定绘图数据：直接保留原实验统计值 =====\n'
                 '# estimate为柱高；run_sd为各轮样本标准差，不是置信区间。\n'
                 '# RTT中心按成功请求数加权，不能改为两轮RTT的简单平均。\n'
                 '# None代表无可用估计，不等于0；每个points按xlabels顺序排列。\n'
                 'DATA = ' + common.literal(data))
    return common.make_script(identifier, parameters, drawing, data_code,
        related=tuple('C-{}-{}-five-metrics'.format(scene, scan) for scene in SCENES),
        description='三场景固定统计值对比；修改此文件数据后，相关三份五指标组合图同步重画。')


def _combined_script(common, identifier, scene, scan, datasets, sources):
    limits = [common.nice_limits(_extent(data['scenes'][scene]), percent=(index == 0))
              for index, data in enumerate(datasets)]
    parameters = '''# ===== 可修改的组合排版参数 =====
# 这里只保存排版与坐标范围；柱高和误差线每次都从对应单图.py读取。
FIGSIZE = (11.5, 10.7)
SCENE = {scene}
SOURCES = {sources}
X_LIM = {xlim}
# 五组范围依次对应满足率、成功RTT、网络负载、控制负载、额外Data提交。
Y_LIMS = {ylims}
Y_TICKS = {ticks}
PANEL_LABELS = {panels}
'''.format(scene=common.literal(scene), sources=common.literal(sources),
           xlim=common.literal((-.6, len(datasets[0]['xlabels']) - .4)),
           ylims=common.literal(limits), ticks=common.literal([_ticks(value) for value in limits]),
           panels=common.literal(SHORT_LABELS))
    drawing = '''def draw():
    """读同文件夹内单图的数据常量；导入单图不会执行其保存或刷新入口。"""
    datasets = [load_plot(filename)["DATA"] for filename in SOURCES]
    fig, axes = plt.subplots(3, 2, figsize=FIGSIZE)
    for index, data in enumerate(datasets):
        ax = axes.flat[index]
        draw_bars(ax, data["xlabels"], data["scenes"][SCENE])
        ax.set_xlim(X_LIM)
        ax.set_ylim(Y_LIMS[index])
        ax.set_yticks(Y_TICKS[index])
        ax.set_ylabel(data["ylabel"])
        ax.set_xlabel(data["xlabel"] + "\\n\\n({}) {}".format(
            "abcde"[index], PANEL_LABELS[index]))
    axes.flat[5].axis("off")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    axes.flat[5].legend(handles, labels, loc="center")
    fig.suptitle(SCENE_LABELS[SCENE] + ": " + datasets[0]["xlabel"])
    finish(fig)
    return fig
'''
    return common.make_script(identifier, parameters, drawing,
        '# 本图不重复保存统计数值；请修改SOURCES列出的单图.py末尾DATA。',
        description='五指标组合图：自动引用对应单图数据，不读取原始实验文件。')


def generate(source):
    """返回24份脚本文本；只读封存统计表，不改变源表或既有图片。"""
    source = Path(source)
    result = json.loads((source / 'source-tables/aggregate.json').read_text(encoding='utf-8'))
    common = _common()
    conditions = {item['id']: item for item in result['conditions']}
    points = {}
    for point in result['points']:
        key = point['scene'], point['condition_id'], str(point['strategy']), point['metric']
        if key in points:
            raise ValueError('Duplicate frozen point: ' + repr(key))
        points[key] = point
    scripts = {}
    for scan_index, scan in enumerate(SCANS):
        ids = result['scans'][scan]
        variable = dict(interest='requests', speed='speed_kmh', vehicles='vehicles')[scan]
        xlabels = [conditions[item][variable] for item in ids]
        datasets, sources = [], []
        for metric_index, metric in enumerate(METRICS):
            data = dict(scenes={}, xlabels=xlabels, xlabel=X_LABELS[scan], ylabel=Y_LABELS[metric])
            for scene in SCENES:
                data['scenes'][scene] = []
                for strategy in range(4):
                    selected = [points[scene, item, str(strategy), metric] for item in ids]
                    data['scenes'][scene].append(dict(strategy=strategy,
                        points=[{key: item[key] for key in ('estimate', 'run_sd')} for item in selected]))
            identifier = 'F{:02d}-{}-{}'.format(5 * scan_index + metric_index + 1, scan, metric)
            scripts[identifier] = _main_script(common, identifier, data, scan)
            datasets.append(data)
            sources.append(identifier + '.py')
        for scene in SCENES:
            identifier = 'C-{}-{}-five-metrics'.format(scene, scan)
            scripts[identifier] = _combined_script(common, identifier, scene, scan, datasets, sources)
    return scripts
