"""把已保存的补充图数表导出为可独立编辑的绘图脚本。

本模块只在导出时读取原表、求运行间均值和样本 SD；导出的脚本仅绘制
字面量，不再分析实验、读取模型或测量 CPU 时间。
"""
import csv
import json
from pathlib import Path
import statistics

import numpy as np

SCENES = ('circle', 'grid', 'spidermap')
LABELS = dict(circle='Circle', grid='Grid', spidermap='Spider')
PERIODS = (20, 40, 80, 160)
PURPLES = ('#8E5AA9', '#C7ACD8', '#654178', '#E4D7EB', '#A67CBE', '#4C285E')
PATTERNS = ('xx', '///', '\\\\', '..', '++', 'oo')
METRICS = (
    ('isr_percent', 'Interest satisfaction rate (%)'),
    ('mean_success_rtt_ms', 'Mean RTT of satisfied Interests (ms)'),
    ('network_mbit', 'NDN L3 outgoing traffic (Mbit)'),
    ('control_mbit', 'Custom control L3 outgoing traffic (Mbit)'),
    ('extra_data_app_attempts', 'Extra Data application submissions'))
CONTROL = ('find', 'hello', 'neural_pit', 'neural_route', 'p2p_handshake', 'search')


def point(values, diagnostic=False):
    """保留缺失值语义；误差是运行间样本 SD，不是置信区间。"""
    values = [float(value) for value in values if value is not None]
    if not all(np.isfinite(value) for value in values):
        raise ValueError('Saved plot values must be finite')
    if not values:
        return dict(estimate=None, run_sd=None)
    mean = statistics.mean(values) if diagnostic else float(np.mean(values))
    sd = (statistics.stdev(values) if diagnostic else float(np.std(values, ddof=1))) if len(values) > 1 else None
    return dict(estimate=mean, run_sd=sd)


def series(label, points, color=0, strategy=None):
    if strategy is not None:
        return dict(strategy=int(strategy), points=points)
    return dict(label=label, points=points, color=PURPLES[color], hatch=PATTERNS[color])


def panel(title, xlabels, values, xlabel='', ylabel='', percent=False, legend=False,
          reference=None):
    return dict(title=title, xlabels=list(xlabels), series=values, xlabel=xlabel,
                ylabel=ylabel, percent=percent, legend=legend, reference=reference)


def figure(panels, shape=(1, 3), figsize=(12.6, 4.35), columns=2, shared_y=False, shared_x=False):
    return dict(panels=panels, shape=shape, figsize=figsize, columns=columns,
                shared_y=shared_y, shared_x=shared_x)


def read_csv(source, name):
    with (source / name).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def groups(rows, scene, field, settings=PERIODS, variable='hello_interval_ms', scale=1.,
           expected=3, diagnostic=False):
    points = []
    for setting in settings:
        selected = [row for row in rows if row.get('scenario', row.get('scene')) == scene
                    and float(row[variable]) == setting]
        if len(selected) != expected:
            raise ValueError('Expected {} complete runs for {}/{}/{}'.format(expected, scene, field, setting))
        values = [float(row[field]) * scale if row.get(field) is not None else None for row in selected]
        points.append(point(values, diagnostic=diagnostic))
    return points


def collect(source):
    """读取已封存的小表，形成 17 张图的面板和绘图数值。"""
    source = Path(source)
    records = json.loads((source / 'analysis-source/run-analysis.json').read_text(encoding='utf-8'))
    accuracy = records['accuracy']
    online = [row for row in records['online'] if row['stage'] == 'online']
    figures = {}
    panels = []
    for scene in SCENES:
        values = [series(label, groups(accuracy, scene, field), index) for index, (field, label) in enumerate(
            [('accuracy_percent', 'All evaluable'), ('handover_accuracy_percent', 'Handover subset')])]
        panels.append(panel(LABELS[scene], PERIODS, values, 'Hello interval (ms)',
                            'Prediction accuracy (%)' if scene == 'circle' else '', percent=True))
    figures['S01-period-prediction-accuracy'] = figure(panels, shared_y=True)

    panels = []
    for lower in (False, True):
        for scene in SCENES:
            if lower:
                fields = [('short_history_count', 'Short nonempty history', 2), ('empty_history_count', 'Empty history', 4)]
                rows = [dict(row, **{field: row[field] / row['sample_count'] * 100 if row['sample_count'] else None
                                    for field, _, _ in fields}) for row in accuracy]
            else:
                fields = [('evaluable_request_percent', 'Requests with a valid target', 0),
                          ('evaluable_observation_percent', 'Evaluable observations', 1)]
                rows = accuracy
            values = [series(label, groups(rows, scene, field), color) for field, label, color in fields]
            ylabel = ('Padded-history share (%)' if lower else 'Evaluable coverage (%)') if scene == 'circle' else ''
            panels.append(panel('' if lower else LABELS[scene], PERIODS, values,
                                'Hello interval (ms)' if lower else '', ylabel, True, scene == 'circle'))
    figures['S02-period-evaluation-coverage'] = figure(panels, (2, 3), (12.6, 7.5), columns=0, shared_x=True)

    for index, (field, label) in enumerate(METRICS, 3):
        panels = [panel(LABELS[scene], PERIODS, [series(label, groups(online, scene, field))],
                        'Hello interval (ms)', label if scene == 'circle' else '', field == 'isr_percent') for scene in SCENES]
        figures['S{:02d}-period-{}'.format(index, field)] = figure(panels, columns=1, shared_y=True)

    fields = [('present_vehicles', 'Present vehicle entries'), ('cache_vehicle_entries', 'Vehicle-to-cache keys'),
              ('cache_name_entries', 'Cache-name keys'), ('cache_edges', 'Vehicle/name associations'),
              ('history_vehicles', 'Vehicles with stored history'), ('history_records', 'Stored history records')]
    states = [row for row in records['states'] if row['hello_interval_ms'] == 20 and row['rsu_id'] == 'network']
    for index, scene in enumerate(SCENES, 8):
        panels = []
        for field, label in fields:
            values = [series(name, groups(states, scene, field + suffix, (5, 10, 15, 20), 'vehicles'), color)
                      for color, (suffix, name) in enumerate([('_mean', 'Time-weighted mean'), ('_peak', 'Peak simultaneous total')])]
            panels.append(panel(label, (5, 10, 15, 20), values, 'Number of vehicles', 'Entries'))
        figures['S{:02d}-{}-state-scale'.format(index, scene)] = figure(panels, (2, 3), (12.6, 7.5))

    payload_lookup = {}
    for row in records['payloads']:
        key = row['task_id'], row['phase'], row['category']
        if key in payload_lookup:
            raise ValueError('Duplicate payload category')
        payload_lookup[key] = row['wire_bytes_mean']
    panels = []
    for lower in (False, True):
        for scene in SCENES:
            values = []
            categories = [('measurement', 'delta', 'Steady cache delta', 1),
                          ('measurement', 'unchanged', 'Steady unchanged', 2)] if lower else [
                          ('startup', 'registration', 'Startup registration', 0)]
            for phase, category, label, color in categories:
                rows = [dict(row, payload=payload_lookup.get((row['task_id'], phase, category))) for row in online]
                values.append(series(label, groups(rows, scene, 'payload'), color))
            panels.append(panel('' if lower else LABELS[scene], PERIODS, values,
                'Hello interval (ms)' if lower else '', 'Encoded Data bytes', legend=scene == 'circle'))
    figures['S11-period-hello-size'] = figure(panels, (2, 3), (12.6, 7.5), columns=0, shared_x=True)

    totals = {}
    for row in records['packets']:
        key = row['task_id'], row['semantic_class']
        totals[key] = totals.get(key, 0) + row['total']
    panels = []
    for scene in SCENES:
        values = []
        for color, category in enumerate(CONTROL):
            rows = [dict(row, traffic=totals.get((row['task_id'], category), 0) * 8 / 1e6) for row in online]
            values.append(series(category, groups(rows, scene, 'traffic'), color))
        panels.append(panel(LABELS[scene], PERIODS, values, 'Hello interval (ms)',
                            'Control L3 outgoing traffic (Mbit)' if scene == 'circle' else ''))
    figures['S12-period-control-categories'] = figure(panels, columns=6, shared_y=True)

    benchmarks = read_csv(source, 'inference-processes.csv')
    panels = []
    for field, label in [('median_us', 'Within-process median'), ('p95_us', 'Within-process p95')]:
        values = []
        for color, operation in enumerate(('forward', 'controller_compute')):
            points = []
            for scene in SCENES:
                selected = [row for row in benchmarks if row['scenario'] == scene and row['operation'] == operation]
                if len(selected) != 5:
                    raise ValueError('Inference figure requires five saved processes per model')
                points.append(point([row[field] for row in selected]))
            values.append(series(operation.replace('_', ' '), points, color))
        panels.append(panel(label, ['Circle', 'Grid', 'Spider'], values,
                            ylabel='CPU wall-clock compute time (microseconds)' if field == 'median_us' else ''))
    figures['S13-inference-cpu-cost'] = figure(panels, (1, 2), (10, 4.35), shared_y=True)

    _diagnostics(source, figures)
    return figures


def _diagnostics(source, figures):
    decomposition = read_csv(source, 'baseline-decomposition.csv')
    for kind, identifier, xlabel, ylabel in [
        ('extra', 'D04-extra-submission-decomposition', 'Submission category', 'Extra Data application submissions'),
        ('control', 'D05-control-traffic-decomposition', 'Control packet category', 'Control L3 outgoing traffic (Mbit)')]:
        categories = sorted({row['category'] for row in decomposition if row['kind'] == kind})
        indexed = {(row['scene'], row['strategy'], row['kind'], row['category']): row for row in decomposition}
        if len(indexed) != len(decomposition):
            raise ValueError('Duplicate decomposition row')
        panels = []
        for scene in SCENES:
            values = []
            for strategy in range(4):
                points = []
                for category in categories:
                    row = indexed[scene, str(strategy), kind, category]
                    if row['repetitions'] != '2':
                        raise ValueError('Decomposition needs the original two runs')
                    points.append(dict(estimate=float(row['mean']), run_sd=None))
                values.append(series('', points, strategy=strategy))
            panels.append(panel(LABELS[scene], [v.replace('_', '\n') for v in categories], values,
                                xlabel, ylabel if scene == 'circle' else ''))
        figures[identifier] = figure(panels, figsize=(15.3, 4.8), columns=4)

    mobility = read_csv(source, 'mobility-coverage.csv')
    panels = []
    for scan, field, xlabel, ylabel in [
        ('speed', 'actual_mean_speed_kmh', 'Vehicle speed setting (km/h)', 'Actual mean speed (km/h)'),
        ('vehicles', 'handover_count', 'Number of vehicles', 'Observed handovers per run')]:
        selected = [row for row in mobility if row['scan'] == scan]
        settings = sorted({float(row['setting']) for row in selected})
        for scene in SCENES:
            values = [dict(label='Naive NDN mobility reference', color='#808080', hatch='',
                           points=groups(selected, scene, field, settings, 'setting', expected=2, diagnostic=True))]
            panels.append(panel(LABELS[scene], settings, values, xlabel, ylabel if scene == 'circle' else '',
                                reference=settings if scan == 'speed' else None))
    figures['D06-mobility-coverage'] = figure(panels, (2, 3), (13.7, 8.7), columns=2)

    speeds = read_csv(source, 'historical-actual-speed.csv')
    settings = sorted({float(row['speed_setting_kmh']) for row in speeds})
    panels = []
    for lower in (False, True):
        field = 'stopped_vehicle_time_fraction' if lower else 'vehicle_time_weighted_speed_kmh'
        for scene in SCENES:
            values = []
            for strategy in range(4):
                selected = [row for row in speeds if row['strategy'] == str(strategy)]
                values.append(series('', groups(selected, scene, field, settings, 'speed_setting_kmh',
                                               100. if lower else 1., expected=2, diagnostic=True), strategy=strategy))
            ylabel = ('Stopped vehicle time (%)' if lower else 'Actual mean speed (km/h)') if scene == 'circle' else ''
            panels.append(panel(LABELS[scene], settings, values, 'Vehicle speed setting (km/h)', ylabel,
                                lower, reference=None if lower else settings))
    figures['S14-historical-actual-speed'] = figure(panels, (2, 3), (14.7, 8.9), columns=5)


DRAW = '''def draw():
    # 每个面板用末尾 DATA 的固定均值和样本标准差绘制。
    fig, axes = plt.subplots(*LAYOUT, figsize=FIGSIZE, squeeze=False,
                            sharex=SHARE_X, sharey=SHARE_Y)
    for i, (ax, item) in enumerate(zip(axes.flat, DATA)):
        draw_bars(ax, item['xlabels'], item['series'])
        if item['reference'] is not None:
            # 灰色虚线是速度设置参考，不是重新计算的实验结果。
            ax.plot(range(len(item['xlabels'])), item['reference'], '--',
                    color='#444444', label='Speed setting', zorder=4)
        ax.set_title(item['title'])
        ax.set_xlabel(item['xlabel'])
        ax.set_ylabel(item['ylabel'])
        ax.set_xlim(*X_LIM[i])
        ax.set_ylim(*Y_LIM[i])
        ax.set_yticks(Y_TICKS[i])
        if item['legend']:
            ax.legend(fontsize=7)
    if LEGEND_COLUMNS:
        handles, labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='upper center', ncol=LEGEND_COLUMNS)
    finish(fig)
    return fig
'''


def generate(source):
    from editable_plot_common import literal, make_script, nice_limits
    scripts = {}
    for identifier, item in collect(source).items():
        ylimits = []
        for panel_data in item['panels']:
            values = list(panel_data['reference'] or [])
            for entry in panel_data['series']:
                for p in entry['points']:
                    if p['estimate'] is not None:
                        sd = p['run_sd'] or 0.
                        values.extend((p['estimate'] - sd, p['estimate'] + sd))
            ylimits.append(nice_limits(values, percent=panel_data['percent']))
        if item['shared_y']:
            common = min(v[0] for v in ylimits), max(v[1] for v in ylimits)
            ylimits = [common] * len(ylimits)
        xtents = [(-.6, len(p['xlabels']) - .4) for p in item['panels']]
        ticks = [[0, 20, 40, 60, 80, 100] if panel_data['percent'] else
                 [float(v) for v in np.linspace(lo, hi, 6)]
                 for panel_data, (lo, hi) in zip(item['panels'], ylimits)]
        parameters = ('# 可修改区：画布、各子图坐标范围和刻度。横轴使用等距类别位置。\n'
                      '# Y_LIM 已覆盖均值和误差线；缺失值显示 N/A，不改成零。\n'
                      'FIGSIZE = {}\nLAYOUT = {}\nLEGEND_COLUMNS = {}\n'
                      'SHARE_X = {}\nSHARE_Y = {}\n'
                      'X_LIM = {}\nY_LIM = {}\nY_TICKS = {}\n').format(
                          literal(item['figsize']), literal(item['shape']), item['columns'],
                          item['shared_x'], item['shared_y'],
                          literal(xtents), literal(ylimits), literal(ticks))
        data = '# 固定绘图数据：由封存实验表计算；按子图顺序排列，不读取原始 CSV。\nDATA = ' + literal(item['panels'])
        scripts[identifier] = make_script(identifier, parameters, DRAW, data,
            description='补充图的固定均值和样本标准差；保持原有分组、缺失值和参考线。')
    return scripts
