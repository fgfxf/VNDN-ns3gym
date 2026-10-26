"""Re-layout existing audited comparison data for the supplementary study."""
import importlib.util
from pathlib import Path
import shutil

_SPEC = importlib.util.spec_from_file_location('followup_primary_plot', Path(__file__).with_name('plot_campaign.py'))
plot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(plot)


def combined_metric_figures(result, output, points):
    figures = []
    conditions = {row['id']: row for row in result['conditions']}
    for scene in plot.SCENARIOS:
        for scan in ('interest', 'speed', 'vehicles'):
            condition_ids = result['scans'][scan]
            variable = {'interest': 'requests', 'speed': 'speed_kmh', 'vehicles': 'vehicles'}[scan]
            x = [conditions[c][variable] for c in condition_ids]
            fig, axes = plot.plt.subplots(3, 2, figsize=(11.5, 10.2))
            for index, metric in enumerate(plot.analysis_tools.MAIN_METRICS):
                ax = axes.flat[index]
                for strategy in plot.STRATEGIES:
                    records = [points[scene, condition, strategy, metric] for condition in condition_ids]
                    plot._draw_points(ax, x, records, strategy, descriptive=True)
                ax.set_title('({}) {}'.format('abcde'[index], plot.METRIC_LABELS[metric]), fontsize=10)
                ax.set_xlabel(plot.AXIS_LABELS[scan])
                ax.set_ylabel(plot.METRIC_LABELS[metric])
                ax.set_xticks(x)
                ax.set_ylim(0, 100 if metric == 'isr_percent' else None)
                ax.grid(axis='y', alpha=.2)
            axes.flat[5].axis('off')
            handles, labels = axes.flat[0].get_legend_handles_labels()
            axes.flat[5].legend(handles, labels, loc='center', frameon=False)
            fig.suptitle(plot.SCENE_LABELS[scene] + ': ' + plot.AXIS_LABELS[scan])
            figures.append(plot.save_figure(
                fig, output, 'C-{}-{}-five-metrics'.format(scene, scan), 'combined_metrics', result,
                'Five original metrics in one layout; all schemes and both paired runs are retained. '
                'Thin vertical lines show one sample standard deviation, not confidence intervals. '
                'Mean RTT includes successful requests only and must be read alongside satisfaction. '
                'Outgoing traffic is NDN L3; extra Data counts explicit application submissions.',
                '同一场景的五项原指标组合排版，保留四策略及两个配对运行；淡点为各运行，误差线为一个样本标准差，'
                '不是置信区间。成功RTT需与满足率一起解释；流量为NDN L3，额外Data为应用显式提交次数。',
                {'scene': scene, 'scan': scan, 'source_table': 'source-tables/plot-summary.csv'}))
    return figures


def combined_3d(result, output):
    rows = list(plot.csv_records(output / 'time-bin-rtt.csv'))
    fig = plot.plt.figure(figsize=(16.5, 5.2))
    for index, scene in enumerate(plot.SCENARIOS):
        ax = fig.add_subplot(1, 3, index + 1, projection='3d')
        for strategy in plot.STRATEGIES:
            selected = [row for row in rows if row['scene'] == scene and row['strategy'] == strategy]
            x = [(float(r['bin_start_s']) + float(r['bin_end_s'])) / 2 for r in selected]
            z = [float(r['mean_success_rtt_ms']) if r['mean_success_rtt_ms'] else plot.np.nan for r in selected]
            ax.plot(x, [int(strategy)] * len(x), z, color=plot.COLORS[int(strategy)],
                    linestyle=plot.LINES[int(strategy)], marker=plot.MARKERS[int(strategy)], markersize=3)
        ax.set(xlabel='Interest generation time (s)', ylabel='Scheme',
               title='({}) {}'.format('abc'[index], plot.SCENE_LABELS[scene]))
        ax.set_yticks(range(4), ('Naive', 'VTDF', 'RTVTDF', 'Proposed'), fontsize=7)
        ax.set_zlabel('Mean successful RTT (ms)', fontsize=8)
    return plot.save_figure(
        fig, output, 'C-all-scenes-rtt-3d', 'combined_3d', result,
        'Three baseline scenes with their prespecified representative seed, using the original '
        '{} s send-time bins. Empty-success bins remain gaps; successes and failures are in '
        'time-bin-rtt.csv. These one-run illustrations are not replicate confidence estimates.'
        .format(result['time_bin_seconds']),
        '三个场景各用原先指定的代表种子，按发送时刻固定{}秒分箱；无成功的箱留空，成功/失败数见配套表。'
        '单轮机制示意不能代表重复实验置信区间。'.format(result['time_bin_seconds']),
        {'source_table': 'time-bin-rtt.csv',
         'representative_seeds_by_scene': result['representative_seeds_by_scene']})


def render_primary(old_campaign_root, output_dir, progress=None):
    old = Path(old_campaign_root).resolve()
    directory = old / 'workflow/figures/all/attempt-001/analysis'
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Primary output already contains files; preserve prior attempts')
    if output == old or old in output.parents:
        raise ValueError('Re-layout must not modify the historical campaign')
    output.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda text: None)
    progress('核验旧264轮主体数据及模型来源')
    # This full provenance traversal is expensive. Perform it once, then check
    # the already validated plot tables again after rendering.
    result = plot.load_analysis(directory)
    if (result.get('design_profile') != plot.analysis_tools.FIXED_MODEL_PROFILE or
            not result.get('skip_training_figures')):
        raise ValueError('Expected the fixed-model main campaign without training curves')
    old_hashes = {str(directory / name): digest for name, digest in result['artifacts'].items()}
    aggregate_hash = plot.summary.sha256_file(directory / 'aggregate.json')
    old_hashes[str(directory / 'aggregate.json')] = aggregate_hash
    copies = output / 'source-tables'; copies.mkdir()
    for name in result['artifacts']:
        if name.endswith('.csv'):
            shutil.copyfile(str(directory / name), str(copies / name))
    shutil.copyfile(str(directory / 'aggregate.json'), str(copies / 'aggregate.json'))
    points = plot.lookup_points(result)
    save = plot.save_figure
    def save_with_progress(*args, **kwargs):
        progress('绘制主体图：' + str(args[2]))
        return save(*args, **kwargs)
    plot.save_figure = save_with_progress
    try:
        with plot.plt.rc_context({'font.size': 9, 'svg.fonttype': 'none', 'pdf.fonttype': 42,
                                  'axes.spines.top': False, 'axes.spines.right': False}):
            figures = plot.scan_figures(result, output, points)
            legacy, diagnostics = plot.legacy_figures(result, directory, output)
            figures.extend(legacy)
            figures.append(plot.traffic_figure(result, output, points))
            figures.extend(diagnostics)
            figures.extend(plot.supplementary_diagnostics(result, directory, output))
            figures.extend(combined_metric_figures(result, output, points))
            figures.append(combined_3d(result, output))
    finally:
        plot.save_figure = save
    if len(figures) != 38 or len({f['id'] for f in figures}) != 38:
        raise ValueError('Main figure set is incomplete')
    for item in figures:
        name = item.get('source_table')
        if name and not (output / name).is_file():
            if not (copies / name).is_file():
                raise ValueError('Figure source table is missing: ' + name)
            item['source_table'] = 'source-tables/' + name
    for path, digest in old_hashes.items():
        if plot.summary.sha256_file(path) != digest:
            raise ValueError('Historical analysis changed during rendering: ' + path)
    source_tables = {str(p.relative_to(output)): plot.summary.sha256_file(p)
                     for p in output.rglob('*.csv')}
    source_tables['source-tables/aggregate.json'] = aggregate_hash
    report = dict(schema_version=1, status='complete', figures=figures,
                  old_analysis_path=str(directory),
                  old_analysis_sha256=aggregate_hash, source_tables=source_tables,
                  validation_only=result['validation_only'],
                  comparison='historical paired n=2 exploratory results; definitions unchanged')
    plot.write_draft_index(output, result, figures)
    index = output / 'index.html'
    index.write_text(index.read_text().replace('figure-index.json', 'primary-figure-index.json'))
    plot.analysis_tools.write_json(output / 'primary-figure-index.json', report)
    progress('主体图完成：38张，已保存SVG/PDF/PNG及源表')
    return report
