#!/usr/bin/env python3
"""Re-render the completed follow-up from sealed tables; never run experiments."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

import paper_figure_style as style

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DEFAULT_ROOT = PROJECT / 'data/experiments/paper-figures-followup-20261026'
PURPLES = ('#8E5AA9', '#C7ACD8', '#654178', '#E4D7EB', '#A67CBE', '#4C285E')
PATTERNS = ('xx', '///', '\\\\', '..', '++', 'oo')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def load_module(name):
    spec = importlib.util.spec_from_file_location('paper_redraw_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_path(root, name):
    path = (root / name).resolve()
    if root.resolve() not in path.parents:
        raise ValueError('Source path escapes its sealed directory: ' + name)
    return path


def verify_sources(root):
    """Check the saved tables and original figures, without visiting raw runs."""
    root = Path(root).resolve()
    report = read_json(root / 'analysis/summary.json')
    index = read_json(root / 'figures/figure-index.json')
    if report.get('status') != 'complete' or index.get('status') != 'complete':
        raise ValueError('The source analysis and figure collection must be complete')
    expected = report['artifact_hashes']['figures/figure-index.json']
    if digest(root / 'figures/figure-index.json') != expected:
        raise ValueError('Source figure index checksum mismatch')
    checks = {root / 'figures/figure-index.json': expected}
    for name, sha in index['artifact_hashes'].items():
        checks[checked_path(root / 'figures', name)] = sha
    for name, sha in index['identity']['analysis_input_hashes'].items():
        checks[checked_path(root, name)] = sha
    for path, sha in checks.items():
        if digest(path) != sha:
            raise ValueError('Source checksum mismatch: ' + str(path))
    return index, checks


def safe_output(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or output in root.parents:
        raise ValueError('Output must not replace a campaign directory')
    for name in ('figures', 'analysis', 'runs', 'plan', 'workflow'):
        protected = root / name
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError('Output overlaps preserved source data: ' + str(output))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output already contains files; use a new output directory')
    return output


def clean_caption(text):
    text = style.display_name(text).replace('proposed scheme', 'TKAN-PDF')
    return (text.replace('faint symbols show individual run estimates and bars show',
                         'bar heights retain the original estimates and whiskers show')
            .replace('points are runs and bars are sample SD',
                     'bar heights are run means and whiskers are sample SD')
            .replace('the displayed per-run RTTs', 'the per-run RTTs in the saved table')
            .replace('淡点为各次运行，误差线为', '柱高沿用原估计值，误差线为')
            .replace('淡点为各run，误差线为', '柱高为各run均值，误差线为')
            .replace('淡点为各运行，误差线为', '柱高沿用原估计值，误差线为')
            .replace('淡点均值', '数表中各run均值'))


def collect_runs(ax, xvalues, groups, label, color):
    """Collect original run means/SD, then lay out all series at save time."""
    points = []
    for values in groups:
        defined = [float(value) for value in values if value is not None]
        if any(not np.isfinite(value) for value in defined):
            raise ValueError('Nonfinite per-run metric')
        points.append({'estimate': float(np.mean(defined)) if defined else None,
                       'run_sd': float(np.std(defined, ddof=1)) if len(defined) > 1 else None})
    if not hasattr(ax, '_paper_pending'):
        ax._paper_pending = []
    ordinal = PURPLES.index(color) if color in PURPLES else len(ax._paper_pending)
    hatch = PATTERNS[ordinal % len(PATTERNS)]
    ax._paper_pending.append((list(xvalues), dict(label=label, color=color, hatch=hatch, points=points)))
    # Legends are created by the historical caller before the final bar layout.
    proxy = Rectangle((0, 0), 0, 0, facecolor=color, hatch=hatch,
                      edgecolor='black', linewidth=.55, label=label)
    proxy._paper_legend_proxy = True
    ax.add_patch(proxy)


def prepare_figure(fig, identifier):
    for ax in fig.axes:
        pending = getattr(ax, '_paper_pending', [])
        if pending:
            for proxy in list(ax.patches):
                if getattr(proxy, '_paper_legend_proxy', False):
                    proxy.remove()
            labels = ['Circle', 'Grid', 'Spider'] if identifier == 'S13-inference-cpu-cost' else pending[0][0]
            style.grouped_bars(ax, labels, [record for _, record in pending])
        # The historical traffic plot already has one bar per scheme.
        for patch in ax.patches:
            if isinstance(patch, Rectangle):
                patch.set_edgecolor('black')
                patch.set_linewidth(.55)
        if identifier == 'F27-baseline-total-traffic':
            for index, patch in enumerate(ax.patches):
                patch.set_hatch(style.HATCHES[index % 4])
    # Legacy callers set bottom=0 before the deferred bars exist, which freezes
    # an empty-axis range. Recompute after ALL shared axes contain bars and SD.
    for ax in fig.axes:
        if getattr(ax, '_paper_pending', []):
            if identifier in ('S01-period-prediction-accuracy', 'S02-period-evaluation-coverage',
                              'S03-period-isr_percent'):
                ax.set_ylim(0, 100)
            else:
                ax.set_autoscaley_on(True)
                ax.autoscale_view(scalex=False, scaley=True)
                ax.set_ylim(bottom=0)
    style.style_figure(fig)
    is_3d = any(ax.name == '3d' for ax in fig.axes)
    if is_3d:
        fig.subplots_adjust(left=.02, right=.91, bottom=.14, top=.92, wspace=.2)
        return
    # Put subfigure descriptions under the axes, as in the reference document.
    # Keeping them inside xlabel's layout box avoids clipping in PDF/SVG exports.
    active = [ax for ax in fig.axes if ax.axison]
    for index, ax in enumerate(active):
        title = ax.get_title()
        ax.set_title('')
        if title:
            title = re.sub(r'^\([a-z]\)\s*', '', title)
            if identifier.startswith('C-'):
                short = ('Interest satisfaction rate', 'Average successful RTT',
                         'Network overhead', 'Control overhead', 'Extra Data submissions')
                title = short[index] if index < len(short) else title
            caption = '({}) {}'.format(chr(97 + index), title)
            ax.set_xlabel((ax.get_xlabel() + '\n\n' if ax.get_xlabel() else '') + caption)
        ax.tick_params(labelsize=10)
        ax.yaxis.label.set_size(11)
        ax.xaxis.label.set_size(11)
    width, height = fig.get_size_inches()
    fig.set_size_inches(width, max(height, 4.35 if len(active) <= 3 else height + .5))
    top = .91 if fig.legends else .99 if fig._suptitle else .98
    fig.tight_layout(rect=(0, 0, 1, top), pad=1.25, w_pad=2.0, h_pad=2.0)


class Exporter:
    def __init__(self, output, original_index, progress):
        self.output = output
        self.original = {row['id']: row for row in original_index['figures']}
        self.progress = progress
        self.finished = []

    def save(self, fig, output, identifier, table, caption_zh, caption_en):
        if identifier not in self.original:
            raise ValueError('Unexpected figure: ' + identifier)
        self.progress('rendering', len(self.finished), identifier)
        prepare_figure(fig, identifier)
        files, hashes = {}, {}
        for extension in ('png', 'svg', 'pdf'):
            path = self.output / (identifier + '.' + extension)
            fig.savefig(path, dpi=300, bbox_inches='tight')
            files[extension], hashes[extension] = path.name, digest(path)
        plt.close(fig)
        if table and not (self.output / table).is_file():
            table = 'source-tables/' + table
        if table and not (self.output / table).is_file():
            raise ValueError('Missing saved source table: ' + str(table))
        artifact = dict(self.original[identifier], files=files, sha256=hashes,
                        source_table=table, caption_zh=clean_caption(caption_zh),
                        caption_en=clean_caption(caption_en))
        self.finished.append(artifact)
        return artifact

    def primary(self, fig, output, identifier, kind, result, caption_en, caption_zh, metadata=None):
        import_text = ('Exploratory paired comparison: n=2 runs per condition; descriptive results, '
                       'no significance claim. ')
        return self.save(fig, output, identifier, (metadata or {}).get('source_table'),
                         '探索比较：每条件2个配对运行，仅作描述，不作显著性结论。' + caption_zh,
                         import_text + caption_en)


def write_gallery(output, figures, source_root):
    items = []
    for row in figures:
        links = ' · '.join('<a href="{}">{}</a>'.format(html.escape(name), ext.upper())
                           for ext, name in row['files'].items())
        items.append('<section id="{id}"><h2>{id}</h2><p>{links} · <a href="{table}">源数据</a></p>'
                     '<img loading="lazy" src="{png}" alt="{id}"><p>{zh}</p><p>{en}</p></section>'.format(
                         id=html.escape(row['id']), links=links,
                         table=html.escape(row.get('source_table') or 'figure-index.json'),
                         png=html.escape(row['files']['png']), zh=html.escape(row['caption_zh']),
                         en=html.escape(row['caption_en'])))
    legend = ' '.join('<span style="border-left:16px solid {};padding-left:5px;margin-right:20px">{}</span>'.format(c, n)
                      for c, n in zip(style.COLORS, style.ALGORITHMS))
    document = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>论文图：分组柱状图</title>'
                '<style>body{max-width:1450px;margin:32px auto;padding:0 24px;font-family:serif;line-height:1.6}'
                'img{width:100%;height:auto}section{border-top:1px solid #ccc;padding:20px 0}h2{font-size:20px}'
                'a{color:#593376}p{overflow-wrap:anywhere}</style>'
                '<h1>实验结果：论文分组柱状图版</h1><p>' + legend + '</p>'
                '<p>TKAN-PDF = Proactive Data Forward。全部使用已保存数据，共52张；没有重新仿真或训练。'
                '主体图每条件2个配对运行，补充在线/准确率图每条件3个运行；CPU图每模型5个独立进程。'
                '误差线为原样本标准差，不是置信区间；RTT仅含成功请求。单神经方案补图以紫色色阶和纹理区分统计子项。</p>'
                '<p>参考文档样式：衬线字体、分组柱、黑色柱边、纹理、图下子标题。三维、箱线与ECDF保留原统计形式。'
                '<a href="重画说明.md">重画说明与复现命令</a> · <a href="figure-index.json">图表与数据校验索引</a></p>'
                '<p>数据来源：' + html.escape(str(source_root)) + '</p>' + ''.join(items) + '</html>')
    (output / 'index.html').write_text(document, encoding='utf-8')


def redraw(root, output, progress=None):
    root, output = Path(root).resolve(), safe_output(root, output)
    index, checks = verify_sources(root)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    def report(status, completed, current=None):
        value = dict(status=status, completed=completed, total=52, current=current,
                     elapsed_seconds=round(time.monotonic() - started, 1))
        write_json(output / 'progress.json', value)
        if progress:
            progress(value)
    report('copying-saved-tables', 0)
    for name, sha in index['artifact_hashes'].items():
        if name.endswith('.csv') or name == 'source-tables/aggregate.json':
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(root / 'figures' / name), str(target))
    analysis_source = output / 'analysis-source'
    analysis_source.mkdir()
    shutil.copyfile(str(root / 'analysis/run-analysis.json'), str(analysis_source / 'run-analysis.json'))
    original_index_sha = digest(root / 'figures/figure-index.json')
    result = read_json(output / 'source-tables/aggregate.json')
    records = read_json(analysis_source / 'run-analysis.json')
    with (output / 'inference-processes.csv').open() as stream:
        benchmarks = list(csv.DictReader(stream))
    for row in benchmarks:
        for key in ('median_us', 'p95_us', 'mean_us'):
            row[key] = float(row[key])
    plot = load_module('plot_campaign')
    primary = load_module('followup_primary_figures')
    supplements = load_module('followup_figures')
    diagnostics = load_module('paper_saved_diagnostics')
    primary.plot = plot
    plot.ALGORITHMS, plot.COLORS = style.ALGORITHMS, style.COLORS
    plot._draw_points = style.draw_points
    exporter = Exporter(output, index, report)
    plot.save_figure = exporter.primary
    supplements.save, supplements.draw_runs, supplements.COLORS = exporter.save, collect_runs, PURPLES
    with style.paper_style():
        points = plot.lookup_points(result)
        plot.scan_figures(result, output, points)
        plot.legacy_figures(result, output / 'source-tables', output)
        plot.traffic_figure(result, output, points)
        primary.combined_metric_figures(result, output, points)
        primary.combined_3d(result, output)
        diagnostics.render_diagnostics(output, output, exporter.save)
        supplements.render_supplements(output, records['accuracy'], records['online'], records['states'],
                                       records['payloads'], records['packets'], benchmarks)
    actual = {row['id']: row for row in exporter.finished}
    expected = [row['id'] for row in index['figures']]
    if set(actual) != set(expected) or len(exporter.finished) != 52:
        raise ValueError('Redrawn collection differs from original 52-figure set')
    figures = [actual[key] for key in expected]
    # Re-created small derived tables must match the already saved versions byte for byte.
    for name, sha in index['artifact_hashes'].items():
        if name.endswith('.csv') or name == 'source-tables/aggregate.json':
            if digest(output / name) != sha:
                raise ValueError('Numerical table changed during restyling: ' + name)
    for path, sha in checks.items():
        if digest(path) != sha:
            raise ValueError('An original source artifact changed during rendering: ' + str(path))
    code = output / 'plot-code'; code.mkdir()
    for name in ('replot_paper_figures.py', 'paper_figure_style.py', 'paper_saved_diagnostics.py',
                 'plot_campaign.py', 'followup_primary_figures.py', 'followup_figures.py'):
        shutil.copyfile(str(HERE / name), str(code / name))
    command = ('cd ' + str(PROJECT) + '\npython3.8 tools/experiments/replot_paper_figures.py \\\n'
               '  --root ' + str(root) + ' \\\n  --output ' + str(output) + '-rerun')
    (output / '重画说明.md').write_text(
        '# 论文图重画记录\n\n日期：2026-10-26。\n\n只改绘图表现，原99轮补充数据、264轮主体数据、模型、统计口径不变。'
        '全部52张保留，输出PNG（300dpi）、SVG和PDF。原图集仍在`../figures/`。\n\n'
        '四策略：Naive NDN 灰 #808080；VTDF 橙黄 #E69F00；RTVTDF 绿 #009E73；TKAN-PDF 紫 #8E5AA9。'
        'TKAN-PDF为展示名称（Proactive Data Forward），现有模型架构与文件不改名。单神经方案多统计量用紫色色阶和纹理。\n\n'
        '采用' + style.font_metadata()['selected_family'] + '（Times New Roman不可用时的兼容衬线字体）。'
        '原柱高、SD、缺失值与成功RTT加权定义不变；主体n=2、补充n=3、CPU每模型5进程，不把包数当独立重复。'
        '三维、箱线、ECDF保留相应统计形式。三个场景的五指标组合保留3×2版式（五图＋图例），不删指标凑2×2。\n\n'
        '源CSV和aggregate.json与原图集逐文件SHA-256相同。CPU耗时直接读取原测量值，不再计时。'
        '图像名称F/C/D/S与原图集对应，准确率和CPU数据仅描述神经方案，不能据此宣称四方案差异。\n\n'
        '## 再次重画\n\n使用原项目已安装的Python3.8环境，选择尚不存在的新目录：\n\n```bash\n' + command + '\n```\n\n'
        '`plot-code/`保存本次绘图实现快照（在原项目中运行上述命令；快照不是独立安装包）。'
        '`figure-index.json`保存所有图及源数据哈希，`progress.json`记录绘图进度。\n', encoding='utf-8')
    write_gallery(output, figures, root)
    source_tables = {str(p.relative_to(output)): digest(p) for p in output.rglob('*.csv')}
    source_tables['source-tables/aggregate.json'] = digest(output / 'source-tables/aggregate.json')
    metadata = dict(schema_version=1, status='complete', figure_count=len(figures), figures=figures,
                    source_root=str(root), original_figure_index_sha256=original_index_sha,
                    source_tables=source_tables, font=style.font_metadata(),
                    algorithms=list(style.ALGORITHMS), colors=list(style.COLORS),
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    verification='original source artifacts unchanged; all CSV and aggregate copies byte-identical',
                    artifact_hashes={str(p.relative_to(output)): digest(p) for p in output.rglob('*')
                                     if p.is_file() and p.name not in ('progress.json', 'figure-index.json')})
    write_json(output / 'figure-index.json', metadata)
    report('complete', 52)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.root / 'figures-paper-20261026'
    def show(row):
        print('重画 {}/{} | 已用 {:.1f} 分钟 | {}'.format(row['completed'], row['total'],
              row['elapsed_seconds'] / 60, row.get('current') or row['status']), flush=True)
    redraw(args.root, output, show)
    print('图集：' + str(output.resolve() / 'index.html'))


if __name__ == '__main__':
    main()
