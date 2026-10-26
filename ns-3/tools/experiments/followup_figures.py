"""Publication layouts and honest per-run summaries for the supplementary batch."""
from collections import defaultdict
import html
import importlib.util
import json
from pathlib import Path
import shutil
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('followup_figure_analysis', HERE / 'followup_analysis.py')
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)
SCENES = a.SCENES
LABELS = dict(circle='Circle', grid='Grid', spidermap='Spider')
PERIODS = (20, 40, 80, 160)
COLORS = ('#009E73', '#0072B2', '#D55E00', '#CC79A7', '#777777', '#E69F00')
METRIC_LABELS = dict(isr_percent='Interest satisfaction rate (%)',
    mean_success_rtt_ms='Mean RTT of satisfied Interests (ms)',
    network_mbit='NDN L3 outgoing traffic (Mbit)',
    control_mbit='Custom control L3 outgoing traffic (Mbit)',
    extra_data_app_attempts='Extra Data application submissions')


def save(fig, output, identifier, table, caption_zh, caption_en):
    fig.text(.5, .012, 'SUPPLEMENTARY EXPLORATION — descriptive variation; see figure caption',
             ha='center', va='bottom', fontsize=7, color='#555555')
    fig.tight_layout(rect=(0, .055, 1, .94))
    files = {}
    for extension in ('svg', 'pdf', 'png'):
        path = output / (identifier + '.' + extension)
        fig.savefig(path, dpi=180, bbox_inches='tight')
        files[extension] = path.name
    plt.close(fig)
    return dict(id=identifier, files=files, kind='supplement', source_table=table,
        caption_zh=caption_zh, caption_en=caption_en,
        sha256={kind: a.data.sha256_file(output / name) for kind, name in files.items()})


def draw_runs(ax, xvalues, groups, label, color):
    centers, errors = [], []
    for x, values in zip(xvalues, groups):
        stats = a.repeat_statistics(values)
        centers.append(stats['mean'] if stats['mean'] is not None else np.nan)
        errors.append(stats['sd'] if stats['sd'] is not None else 0.)
        defined = [v for v in values if v is not None]
        ax.scatter([x] * len(defined), defined, s=12, color=color, alpha=.4, zorder=2)
    if all(not np.isfinite(value) for value in centers):
        ax.plot(xvalues, centers, label=label, color=color, marker='o', linewidth=1.2)
    else:
        ax.errorbar(xvalues, centers, yerr=errors, label=label, color=color,
                    marker='o', markersize=4, capsize=3, linewidth=1.2)
    ax.grid(axis='y', alpha=.2)


def period_figure(rows, fields, labels, output, identifier, table, caption_zh, caption_en,
                  percent=False):
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 3.8), sharey=True)
    for scene, ax in zip(SCENES, axes):
        for index, (field, label) in enumerate(zip(fields, labels)):
            groups = [[row.get(field) for row in rows
                       if row['scenario'] == scene and row['hello_interval_ms'] == period]
                      for period in PERIODS]
            if any(len(group) != 3 for group in groups):
                raise ValueError('period figure requires all three runs for every point')
            draw_runs(ax, PERIODS, groups, label, COLORS[index])
        ax.set(title=LABELS[scene], xlabel='Hello interval (ms)', xticks=PERIODS)
        ax.set_ylim(0, 100) if percent else ax.set_ylim(bottom=0)
    axes[0].set_ylabel(labels[0] if len(fields) == 1 else 'Prediction accuracy (%)')
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, loc='upper center', ncol=len(fields), frameon=False)
    return save(fig, output, identifier, table, caption_zh, caption_en)


def render_supplements(output, accuracy, online, states, payloads, packets, benchmarks):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    figures = []
    online_period = [row for row in online if row['stage'] == 'online']
    figures.append(period_figure(accuracy,
        ['accuracy_percent', 'handover_accuracy_percent'], ['All evaluable', 'Handover subset'],
        output, 'S01-period-prediction-accuracy', 'accuracy-runs.csv',
        '固定旧模型在NoForward新采样上的top-1预测准确率。每周期3次独立运行；淡点为各run，误差线为样本SD。'
        '交接按请求生成至3秒截止期内的关联变化定义，标签为Data首次回源RSU时的实际服务站。',
        'Fixed-model top-1 accuracy on new NoForward samples. Three runs per period; points are runs and bars are sample SD, '
        'not confidence intervals. Handover is defined in the request lifetime; target is serving RSU at source return.', True))
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 7), sharex=True)
    coverage_rows = []
    for scene, upper, lower in zip(SCENES, axes[0], axes[1]):
        for field, name, color in [('evaluable_request_percent', 'Requests with a valid target', COLORS[0]),
                                   ('evaluable_observation_percent', 'Evaluable observations', COLORS[1])]:
            draw_runs(upper, PERIODS, [[r[field] for r in accuracy if r['scenario'] == scene and
                       r['hello_interval_ms'] == period] for period in PERIODS], name, color)
        for field, name, color in [('short_history_count', 'Short nonempty history', COLORS[2]),
                                   ('empty_history_count', 'Empty history', COLORS[4])]:
            groups = []
            for period in PERIODS:
                values = []
                for row in accuracy:
                    if row['scenario'] == scene and row['hello_interval_ms'] == period:
                        value = row[field] / row['sample_count'] * 100 if row['sample_count'] else None
                        values.append(value)
                        coverage_rows.append(dict(scenario=scene, hello_interval_ms=period,
                            seed_family=row['seed_family'], metric=field + '_percent', value=value,
                            denominator='evaluable observations', count=row[field], total=row['sample_count']))
                groups.append(values)
            draw_runs(lower, PERIODS, groups, name, color)
        upper.set(title=LABELS[scene], ylim=(0, 100))
        lower.set(xlabel='Hello interval (ms)', xticks=PERIODS, ylim=(0, 100))
    axes[0, 0].set_ylabel('Evaluable coverage (%)')
    axes[1, 0].set_ylabel('Padded-history share (%)')
    axes[0, 0].legend(fontsize=7)
    axes[1, 0].legend(fontsize=7)
    a.write_csv(output / 'history-coverage-points.csv', coverage_rows)
    figures.append(save(fig, output, 'S02-period-evaluation-coverage', 'accuracy-runs.csv',
        '可评价覆盖与有效样本中的空/短历史比例；短历史按在线相同规则填充并保留。不可评价原因和数量见accuracy-runs.csv，'
        '它们不从在线ISR分母删除。',
        'Evaluable coverage and padded-history fractions. Online-equivalent padded histories are retained; '
        'exclusions are reported separately and never removed from online ISR denominators.'))
    for index, field in enumerate(a.METRICS, 3):
        figures.append(period_figure(online_period, [field], [METRIC_LABELS[field]], output,
            'S{:02d}-period-{}'.format(index, field), 'online-runs.csv',
            '神经策略实际在线运行，固定模型与2T失联规则，每周期3seed；均值和SD按完整run计算。'
            'RTT仅含成功请求；L3负载包含排空时间，不等同MAC成本。',
            'Online proposed scheme with a fixed model and expiry 2T; three complete runs per point, mean and sample SD. '
            'RTT is conditional on success; L3 cost includes drain and excludes LP/MAC.', field == 'isr_percent'))
    state_fields = [('present_vehicles', 'Present vehicle entries'),
                    ('cache_vehicle_entries', 'Vehicle-to-cache keys'),
                    ('cache_name_entries', 'Cache-name keys'),
                    ('cache_edges', 'Vehicle/name associations'),
                    ('history_vehicles', 'Vehicles with stored history'),
                    ('history_records', 'Stored history records')]
    for index, scene in enumerate(SCENES, 8):
        fig, axes = plt.subplots(2, 3, figsize=(12.6, 7))
        rows = [row for row in states if row['scenario'] == scene and
                row['hello_interval_ms'] == 20 and row['rsu_id'] == 'network']
        for ax, (field, label) in zip(axes.flat, state_fields):
            for suffix, name, color in [('_mean', 'Time-weighted mean', COLORS[0]),
                                       ('_peak', 'Peak simultaneous total', COLORS[1])]:
                groups = [[row[field + suffix] for row in rows if row['vehicles'] == n]
                          for n in (5, 10, 15, 20)]
                if any(len(group) != 3 for group in groups):
                    raise ValueError('state figure requires three runs per vehicle count')
                draw_runs(ax, (5, 10, 15, 20), groups, name, color)
            ax.set(title=label, xlabel='Number of vehicles', ylabel='Entries', xticks=(5, 10, 15, 20), ylim=(0, None))
        handles, names = axes[0, 0].get_legend_handles_labels()
        fig.legend(handles, names, loc='upper center', ncol=2, frameon=False)
        figures.append(save(fig, output, 'S{:02d}-{}-state-scale'.format(index, scene), 'state-runs.csv',
            '{}：20ms周期下全网真实表条目数，先按每run测量窗口积分及求同时峰值，再汇总3seed。'
            '每车5Hz，业务量随车数增长；10车来自周期实验共用轮。条目数不是堆内存字节。'.format(LABELS[scene]),
            '{}: actual network-wide entries at 20 ms. Per-run time-weighted means and simultaneous peaks are '
            'summarized over three seeds; 5 Hz per vehicle. Entry counts are not heap memory bytes.'.format(LABELS[scene])))
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 7), sharex=True)
    payload_points = []
    for scene, upper, lower in zip(SCENES, axes[0], axes[1]):
        for phase, category, name, ax, color in [
                ('startup', 'registration', 'Startup registration', upper, COLORS[0]),
                ('measurement', 'delta', 'Steady cache delta', lower, COLORS[1]),
                ('measurement', 'unchanged', 'Steady unchanged', lower, COLORS[2])]:
            groups = []
            for period in PERIODS:
                values = []
                for run in online_period:
                    if run['scenario'] != scene or run['hello_interval_ms'] != period:
                        continue
                    found = [row for row in payloads if row['task_id'] == run['task_id'] and
                             row['phase'] == phase and row['category'] == category]
                    if len(found) > 1:
                        raise ValueError('duplicate payload run/category')
                    value = found[0]['wire_bytes_mean'] if found else None
                    values.append(value)
                    payload_points.append(dict(task_id=run['task_id'], scenario=scene,
                        hello_interval_ms=period, seed_family=run['seed_family'], phase=phase,
                        category=category, wire_bytes_mean=value, count=found[0]['count'] if found else 0))
                groups.append(values)
            draw_runs(ax, PERIODS, groups, name, color)
        upper.set(title=LABELS[scene], ylabel='Encoded Data bytes', ylim=(0, None))
        lower.set(xlabel='Hello interval (ms)', ylabel='Encoded Data bytes', xticks=PERIODS, ylim=(0, None))
    axes[0, 0].legend(fontsize=7)
    axes[1, 0].legend(fontsize=7)
    a.write_csv(output / 'hello-size-points.csv', payload_points)
    figures.append(save(fig, output, 'S11-period-hello-size', 'hello-size-points.csv',
        '每run先求hello Data应用编码尺寸均值，再汇总3seed；启动注册与稳态增量/无变化分开。'
        '不存在的类别记NA，不记0字节。包含NDN编码，不代表实际网络发送或MAC成本。',
        'Per-run mean encoded hello Data sizes; startup registration and steady-state categories are separate. '
        'An absent category is NA, not a zero-byte packet. Application encoding is not network/MAC delivery.'))
    class_points = []
    for run in online_period:
        for category in sorted(a.CONTROL_CLASSES):
            total = sum(row['total'] for row in packets if row['task_id'] == run['task_id'] and
                        row['semantic_class'] == category)
            class_points.append(dict(task_id=run['task_id'], scenario=run['scenario'],
                hello_interval_ms=run['hello_interval_ms'], seed_family=run['seed_family'],
                semantic_class=category, outgoing_mbit=total * 8 / 1e6))
    a.write_csv(output / 'control-category-points.csv', class_points)
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4), sharey=True)
    for scene, ax in zip(SCENES, axes):
        for index, category in enumerate(sorted(a.CONTROL_CLASSES)):
            draw_runs(ax, PERIODS, [[row['outgoing_mbit'] for row in class_points
                if row['scenario'] == scene and row['hello_interval_ms'] == period and
                row['semantic_class'] == category] for period in PERIODS], category, COLORS[index])
        ax.set(title=LABELS[scene], xlabel='Hello interval (ms)', xticks=PERIODS, ylim=(0, None))
    axes[0].set_ylabel('Control L3 outgoing traffic (Mbit)')
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, loc='upper center', ncol=6, fontsize=7, frameon=False)
    figures.append(save(fig, output, 'S12-period-control-categories', 'control-category-points.csv',
        '纯控制类别的真实网络Face L3出站字节，测量窗口加排空期。每类别缺失包计0，类别之和与控制总负载对账。',
        'Actual network Face outgoing L3 bytes by pure-control category, measurement plus drain. '
        'Absent packet categories contribute zero; category sums reconcile with total control cost.'))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, field, title in zip(axes, ('median_us', 'p95_us'), ('Within-process median', 'Within-process p95')):
        for index, operation in enumerate(('forward', 'controller_compute')):
            positions = np.arange(3) + (index - .5) * .3
            groups = [[row[field] for row in benchmarks if row['scenario'] == scene and
                       row['operation'] == operation] for scene in SCENES]
            if any(len(group) != 5 for group in groups):
                raise ValueError('inference plot requires five independent processes per model')
            draw_runs(ax, positions, groups, operation.replace('_', ' '), COLORS[index])
        ax.set(title=title, xticks=np.arange(3), xticklabels=[LABELS[s] for s in SCENES], ylim=(0, None))
    axes[0].set_ylabel('CPU wall-clock compute time (microseconds)')
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, loc='upper center', ncol=2, frameon=False)
    figures.append(save(fig, output, 'S13-inference-cpu-cost', 'inference-processes.csv',
        '每模型5个独立进程，单线程CPU、batch=1、100次预热和1000次计时。展示每进程中位数/P95及进程间SD；'
        '纯forward与含归一化/softmax/候选映射的控制器计算分开，不包含Gym等待或模型加载，不加到仿真RTT。',
        'Five independent CPU processes per model, one thread, batch one, 100 warmups and 1000 timings. '
        'Within-process median/p95 and across-process SD; excludes model load, Gym, logging and I/O. Not simulation RTT.'))
    return figures


def old_descriptive_tables_and_figures(old_analysis, output, progress):
    """Existing actual speeds and packet sizes; no new simulation or re-aggregation."""
    result = a.data.read_json(old_analysis / 'aggregate.json')
    rows = a.data.read_json(old_analysis / 'run-details.json')['runs']
    baseline = [row for row in rows if row['condition_id'] == result['baseline_condition_id']]
    packet_rows = []
    for index, run in enumerate(baseline):
        progress('historical-packet-sizes', index, len(baseline),
                 '{} strategy {}'.format(run['scene'], run['strategy']))
        run_path = Path(run['run_path'])
        statistics = a.packet_statistics(a.csv_rows(run_path / 'raw/packet-l3.csv'),
            run['measurement_start_ns'], run['drain_end_ns'])
        if sum(row['total'] for row in statistics) != run['control_l3_bytes']:
            raise ValueError('historical packet size totals differ from frozen control metric')
        packet_rows.extend(dict(row, scenario=run['scene'], strategy=run['strategy'],
            seed_family=run['seed_family'], run_path=str(run_path),
            manifest_sha256=run['manifest_sha256']) for row in statistics)
    a.write_csv(output / 'historical-control-packet-sizes.csv', packet_rows)
    condition_lookup = {row['id']: row for row in result['conditions']}
    speed_rows = [dict(row, speed_setting_kmh=condition_lookup[row['condition_id']]['speed_kmh'])
                  for row in rows if row['condition_id'] in result['scans']['speed']]
    a.write_csv(output / 'historical-actual-speed.csv', speed_rows)
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 7), sharex=True)
    speed_points = [condition_lookup[cid]['speed_kmh'] for cid in result['scans']['speed']]
    for scene, upper, lower in zip(SCENES, axes[0], axes[1]):
        for strategy, name, color in zip(('0', '1', '2', '3'),
                ('Naive NDN', 'VTDF', 'RTVTDF', 'Proposed (TKAN-LSTM)'),
                ('#666666', '#D55E00', '#0072B2', '#009E73')):
            selected = [row for row in speed_rows if row['scene'] == scene and row['strategy'] == strategy]
            draw_runs(upper, speed_points, [[row['vehicle_time_weighted_speed_kmh'] for row in selected
                if row['speed_setting_kmh'] == point] for point in speed_points], name, color)
            draw_runs(lower, speed_points, [[100 * row['stopped_vehicle_time_fraction'] for row in selected
                if row['speed_setting_kmh'] == point] for point in speed_points], name, color)
        upper.plot(speed_points, speed_points, ':', color='#bbbbbb', label='Setting')
        upper.set(title=LABELS[scene], ylabel='Actual time-weighted speed (km/h)', ylim=(0, None))
        lower.set(xlabel='Speed setting (km/h)', xticks=speed_points, ylabel='Stopped vehicle time (%)', ylim=(0, 100))
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=5, fontsize=7, frameon=False)
    artifact = save(fig, output, 'S14-historical-actual-speed', 'historical-actual-speed.csv',
        '原264批的实际时间加权速度及停驶比例，每条件2seed。道路、路口与跟驰可能使高速度设置对应相同实际移动；'
        '此图只解释原速度扫描，不改变或新增实验数据。',
        'Actual time-weighted speeds and stopped-time fractions from the original 264 runs, n=2. '
        'Settings can saturate under road limits and interactions; these are reused descriptive data.')
    return [artifact]


def default_accuracy_table(root, output):
    plan = a.data.read_json(root / 'plan/followup-manifest.json')
    source = Path(plan['model_source_root'])
    rows = []
    for scene in SCENES:
        path = source / 'workflow/evaluate' / scene / 'attempt-001/evaluation/evaluation.json'
        evaluation = a.data.read_json(path)
        if evaluation['model_sha256'] != plan['models'][scene]['sha256']:
            raise ValueError('old independent evaluation model differs from reused model')
        rows.append(dict(scenario=scene, accuracy_percent=100 * evaluation['accuracy'],
            handover_accuracy_percent=100 * evaluation['subsets']['handover']['accuracy'],
            sample_count=evaluation['sample_count'], handover_count=evaluation['subsets']['handover']['sample_count'],
            source_path=str(path), source_sha256=a.data.sha256_file(path),
            model_sha256=evaluation['model_sha256'],
            scope='historical default-period NoForward offline evaluation; four runs at different conditions, not n=4 per condition'))
    a.write_csv(output / 'historical-default-prediction.csv', rows)



def figure_identity(root):
    root = Path(root)
    inputs = sorted(path for path in (root / 'analysis').glob('*.csv')
                    if path.name != 'source-index.csv')
    inputs.append(root / 'analysis/run-analysis.json')
    return dict(followup_manifest_sha256=a.data.sha256_file(root / 'plan/followup-manifest.json'),
        plot_code_sha256=a.data.sha256_file(__file__),
        primary_code_sha256=a.data.sha256_file(HERE / 'followup_primary_figures.py'),
        analysis_code_sha256=a.data.sha256_file(HERE / 'followup_analysis.py'),
        analysis_input_hashes={str(path.relative_to(root)): a.data.sha256_file(path) for path in inputs})


def render_all(root, old_root, accuracy, online, states, payloads, packets, benchmarks, progress):
    root, old_root = Path(root), Path(old_root)
    output = root / 'figures'
    identity = figure_identity(root)
    if (output / 'figure-index.json').exists():
        saved = a.data.read_json(output / 'figure-index.json')
        if saved.get('identity') != identity:
            raise ValueError('completed figure output belongs to another analysis identity')
        for name, digest in saved['artifact_hashes'].items():
            a.data.verify_hash(output / name, digest)
        return saved
    if output.exists():
        output.rename(output.with_name('figures-interrupted-' + str(time.time_ns())))
    output.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location('followup_primary', HERE / 'followup_primary_figures.py')
    primary_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(primary_module)
    primary = primary_module.render_primary(old_root, output,
        progress=lambda message: progress('primary-figures', 0, 1, message))
    figures = list(primary['figures'])
    for source in (root / 'analysis').glob('*.csv'):
        shutil.copy2(source, output / source.name)
    with plt.rc_context({'font.size': 9, 'svg.fonttype': 'none', 'pdf.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False}):
        progress('supplement-figures', 0, 14, 'period, state and inference figures')
        figures.extend(render_supplements(output, accuracy, online, states, payloads, packets, benchmarks))
        figures.extend(old_descriptive_tables_and_figures(Path(primary['old_analysis_path']), output, progress))
    default_accuracy_table(root, output)
    if len({item['id'] for item in figures}) != len(figures):
        raise ValueError('duplicate figure identifiers')
    fragments = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>补充实验与论文图</title><style>body{max-width:1280px;margin:2rem auto;padding:0 1rem;'
        'font-family:sans-serif;line-height:1.6}img{max-width:100%}article{border-top:1px solid #ddd;'
        'padding:1rem 0}.note{color:#666}a{margin-right:1rem}</style>',
        '<h1>补充实验与论文图</h1>',
        '<p>主体比较复用原264轮，每条件2个配对运行。新增补充实验99轮：每条件3个新种子；'
        'CPU推理每模型5个独立进程。淡点是完整运行/进程，误差线为样本标准差，不是置信区间。'
        '全部结果为描述性探索，不预设方案占优。</p>',
        '<p><a href="../analysis/方法与数据来源.md">方法与数据来源</a>'
        '<a href="figure-index.json">逐图索引</a><a href="../analysis/source-index.csv">原始文件索引</a></p>']
    for item in figures:
        files = {key: html.escape(value, quote=True) for key, value in item['files'].items()}
        identifier = html.escape(item['id'])
        fragments.extend(['<article><h2>' + identifier + '</h2>',
            '<a href="{png}"><img loading="lazy" src="{png}" alt="{name}"></a>'.format(name=identifier, **files),
            '<p><a href="{pdf}">PDF</a><a href="{svg}">SVG</a><a href="{png}">PNG</a></p>'.format(**files),
            '<p>' + html.escape(item['caption_zh']) + '</p>',
            '<p class="note">' + html.escape(item['caption_en']) + '</p></article>'])
    fragments.append('</html>')
    (output / 'index.html').write_text('\n'.join(fragments), encoding='utf-8')
    methods = '''# 补充实验方法与数据来源

日期：2026-10-26。主体图复用历史264轮；补充实验99轮，三场景各采用固定旧模型，无重新训练。

- NoForward周期采样36轮，真实10×6 hello历史；目标按业务Data首次回原请求RSU时的服务RSU标记。
  不用3秒超时时的关联作标签。未知、失联、过期与同时间歧义等排除原因逐行保留；
  空/短历史按在线相同规则填充并参与可评价样本推理，另列数量。
  每个源RSU/请求仅取第一次合格观测；报告样本覆盖与不同请求覆盖，不能把分类准确率称ISR。
  交接子集沿用请求生成至3秒截止期内的关联变化，目标时刻仍是实际回源时刻。
- NN在线周期36轮与车辆规模27轮：20/40/80/160ms，RSU失联2T，车辆邻居失效2000ms。
  模型的权重、归一化、类别及选路阈值保持原值，因此测的是旧模型部署敏感性，不是各周期重新训练后的上限。
- 状态表从START/CHANGE/STOP的事件后计数积分，测量窗[20,140)；逐RSU及全网分别报告。
  全网峰值来自同时占用，不能把不同RSU的峰值相加。cache_edges与reverse_cache_edges是同一关联的两个索引，不能相加当两份缓存。
  历史/MAC等按实现实际保留；条目数不等于C++真实堆内存。
- hello-payloads记录OBU编码后、应用put前的Data内容和完整NDN编码字节；不是网络实际发送成功或MAC成本。
  启动[0,20)、稳态[20,140)、排空[140,143.5)分开；registration/delta/unchanged/cache_disabled按真实编码对象分类。
  纯控制网络成本另外从network Face的L3 OUT Interest/Data累计[20,143.5)，包含hello、handshake、search/find、neural-route/pit。
- NN沿用此前批准的VNH1/CBOR紧凑hello、空缓存增量省略；其他旧主体策略使用各自原实现。
  这一实现差异仅在方法文档解释，不能把全部效果归因于神经网络分类本身。
- CPU微基准：每模型5个新进程，单线程、batch=1、eval/no_grad，100次预热后1000次独立计时。
  forward排除输入转换；controller_compute包含归一化、softmax、候选映射；均排除加载、Gym等待、打印和写盘。
  完整每次计时CSV及硬件/版本/模型和输入SHA在analysis/benchmark；不能加到仿真RTT。
- 主体264轮为原训练种子复用的n=2探索比较；新补充3seed不能合并成主体n=5。
  旧VTDF源站等待队列过期清理缺口本轮未修复，保留旧结果及局限。
  成功RTT依赖交付成功样本，必须结合ISR解释。原车辆规模实验每车5Hz，业务量与车数同时增长。
  Grid/Spider实际速度可能受道路和跟驰限速；速度设置不等于实际速度。

## 文件索引

- `accuracy-runs.csv`：36次离线预测、交接子集、覆盖、排除原因和短历史。
- `evaluation/<task>/`：逐run真实特征/标签、每行排除证据、模型概率及推理基准输入。
- `online-runs.csv`：63次神经在线实验的原五指标和运行身份。
- `state-runs.csv`：每RSU与全网状态条目时间均值和峰值。
- `hello-payload-runs.csv`、`control-packet-runs.csv`：应用编码尺寸与实际网络L3包尺寸分开。
- `inference-processes.csv`、`benchmark/`：CPU每进程汇总、逐次计时和硬件/版本。
- `source-index.csv`：本次原始run/模型/manifest绝对路径及SHA256。
- `../figures/figure-index.json`：每张SVG/PDF/PNG及来源表摘要；`../figures/index.html`可浏览全部图。
- `../figures/historical-default-prediction.csv`：旧独立评估表，不把四个不同条件当作同条件n=4。

原始数据保留在各run的raw目录，图或排版错误可重画；请新建输出目录，不覆盖历史批次。
'''
    (root / 'analysis/方法与数据来源.md').write_text(methods, encoding='utf-8')
    if figure_identity(root) != identity:
        raise ValueError('analysis input identity changed while rendering')
    report = dict(schema_version=1, status='complete', identity=identity, figure_count=len(figures),
        figures=figures, primary_source=primary,
        source_tables={path.name: a.data.sha256_file(path) for path in output.glob('*.csv')},
        artifact_hashes={str(path.relative_to(output)): a.data.sha256_file(path)
            for path in output.rglob('*') if path.is_file() and path != output / 'figure-index.json'})
    a.write_json(output / 'figure-index.json', report)
    progress('figures-complete', len(figures), len(figures), None)
    return report
