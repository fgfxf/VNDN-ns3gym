"""Freeze saved plot numbers into a portable, manually editable plot folder."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import html
import importlib
import json
from pathlib import Path
import runpy
import sys
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DEFAULT_SOURCE = PROJECT / 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026'
DEFAULT_OUTPUT = PROJECT / 'data/experiments/paper-editable-20261028'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def verify_source(source):
    index_path = source / 'figure-index.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    if index['figure_count'] != 52 or len(index['figures']) != 52:
        raise ValueError('Expected the complete original collection of 52 figures')
    checked = {'figure-index.json': digest(index_path)}
    expected = dict(index['artifact_hashes'])
    for name, sha in index.get('source_tables', {}).items():
        if name in expected and expected[name] != sha:
            raise ValueError('Conflicting sealed source checksums: ' + name)
        expected[name] = sha
    for name, sha in expected.items():
        path = (source / name).resolve()
        if source not in path.parents:
            raise ValueError('Source path escapes the figure folder: ' + name)
        if digest(path) != sha:
            raise ValueError('Sealed source changed: ' + name)
        checked[name] = sha
    return index, checked


def collect_programs(source):
    old_path = list(sys.path)
    sys.path.insert(0, str(HERE))
    try:
        scripts = {}
        for name in ('editable_primary', 'editable_supplements', 'editable_distributions'):
            group = importlib.import_module(name).generate(source)
            if set(scripts) & set(group):
                raise ValueError('Duplicate figure script')
            scripts.update(group)
        return scripts
    finally:
        sys.path[:] = old_path


def gallery(figures):
    sections = []
    for row in figures:
        ident = html.escape(row['id'])
        links = ' · '.join('<a href="{0}.{1}">{2}</a>'.format(ident, ext, ext.upper())
                           for ext in ('png', 'svg', 'pdf'))
        sections.append('<section id="{0}"><h2>{0}</h2><p>{1} · '
                        '<a href="{0}.py">编辑绘图脚本</a></p>'
                        '<img loading="lazy" src="{0}.png" data-image="{0}.png" alt="{0}">'
                        '<p>{2}</p><p>{3}</p></section>'.format(
                            ident, links, html.escape(row.get('caption_zh', '')),
                            html.escape(row.get('caption_en', ''))))
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>可编辑论文绘图</title>
<style>body{max-width:1450px;margin:32px auto;padding:0 24px;font-family:serif;line-height:1.6}
img{width:100%;height:auto}section{border-top:1px solid #ccc;padding:20px 0}
h2{font-size:20px}a{color:#593376}p{overflow-wrap:anywhere}</style>
<h1>可编辑论文绘图：52张</h1>
<p>修改同名Python脚本并运行，再刷新此网页。单图运行后会自动更新相关组合图。</p>
<p>Naive NDN灰色 · VTDF橙黄色 · RTVTDF绿色 · TKAN-PDF紫色。</p>
<p>初始数值沿用已保存实验；误差线为原样本标准差。每张图均导出PNG、SVG和PDF。</p>
<p><a href="使用说明.md">中文使用说明</a> · <a href="初始来源记录.json">初始来源记录</a></p>
''' + ''.join(sections) + '''
<script>
// 每次刷新使用新的图片地址参数，避免浏览器继续显示旧缓存。
const version = Date.now();
document.querySelectorAll('img[data-image]').forEach(image => {
    image.src = image.dataset.image + '?v=' + version;
});
</script></html>
'''


README = '''# 可编辑论文绘图：使用说明

本文件夹有52份Python脚本，对应网页中的52张图；没有.cmd，也不要求读取原始实验数据。
每张图保存PNG、SVG、PDF三种格式。原实验目录和原图未修改。

## 最简单的操作

1. 用编辑器打开要改的.py，例如F09-speed-control_mbit.py。
2. 修改顶部的字体、尺寸、X_LIM、Y_LIM、刻度等参数，保存。
3. 双击该.py运行（你已选择自行配置系统的.py运行关联）。
4. 等待终端显示“完成”，刷新本文件夹的index.html。

如双击只打开编辑器，表示系统尚未把.py关联到Python运行；不必重跑实验。
也可在终端执行：

~~~bash
python3.8 F09-speed-control_mbit.py
~~~

Windows Python亦可执行这些脚本，需安装matplotlib和numpy；无需ns-3、SUMO、PyTorch或模型。
本机已有Python3.8 / matplotlib3.7.5 / numpy1.24.4。字体默认Liberation Serif，可在脚本顶部改为本机字体。
脚本使用自身位置保存图片，从其他工作目录执行也不会把图片写错地方。

## 常改的参数在哪里

- FIGSIZE：图的宽、高，单位英寸。
- FONT_FAMILY / FONT_SIZE / DPI：字体、字号与PNG分辨率。
- COLORS / HATCHES：四算法的颜色和纹理。
- X_LIM / Y_LIM（组合图可能为复数形式）：坐标上下界。
- X_TICKS / Y_TICKS：刻度；部分图使用None自动刻度。
- 三维图另有Z_LIM和观察角度参数。
- 文件末尾DATA：从原保存实验计算出的完整绘图数值；均值与SD分别保留。

F09三个场景的Y范围已设为0～160 Mbit，以完整显示Grid较高的柱子和误差线。
各图都写了明确范围。以后改了数据，若超出原范围，也需要手动修改对应轴界。
分类柱状图的实际X坐标是0、1、2、3，标签才是15、30、50、60；
例如X_LIM=(-0.6,3.6)不是限制车速到3.6，而是给四组柱子预留边距。
百分比通常覆盖0～100；若SD端点略越界，初始范围会包含误差端点。
箱线图保留“完整范围”和“局部放大”两个面板，局部面板有意不显示远端离群点。

## 单图与组合图如何联动

- F01–F05运行后，更新三个场景各自的Interest五指标组合图。
- F06–F10运行后，更新三个场景各自的Speed五指标组合图。
- F11–F15运行后，更新三个场景各自的Vehicles五指标组合图。
- F21–F23运行后，更新三场景合并的三维图。
- 其余图只更新自身。

组合图的数据从对应单图脚本读取；修改组合图数值应去对应单图的DATA。
组合图的排版、字体、坐标范围仍由组合脚本顶部参数控制，可以单独修改。
单图被组合图加载时不会反复生成图片，因此不会递归更新。
三个扫描中共有的基准点、箱线图与CDF等其他数据重叠，不自动跨图修改。

## 完整数据与原样重现

初始均值、SD、运行散点、三维时间桶、箱线统计/全部离群点和CDF完整阶梯均保留。
None表示不可评价或空时间桶，不是0；RTT中心沿用原成功数加权定义。
三份CDF及部分箱图的DATA较长，是为了保持全部数值；绘图逻辑和常用参数在前面。
所有脚本仅绘图，不会采样、训练或计算CPU耗时。
原配色、衬线字体、黑边纹理和图型保持；修复了部分原图坐标上界过小导致的裁切。
文件夹整体可以复制。组合脚本依赖同文件夹对应单图；单独复制组合脚本不足以运行。

## 来源与保存

初始来源：paper-figures-followup-20261026/figures-paper-20261026。
初始来源记录.json记录导出时的源文件和脚本摘要，是初始快照，手工修改后不会重新强制校验。
初次出图记录.json记录首次完整渲染结果，不表示之后手工编辑的当前状态。
原始数据仍需另行备份。本文件夹在data目录，遵循原项目忽略规则；不要只依赖Git备份你的手工编辑。
生成器与测试位于受Git管理的tools/experiments/export_editable_plots.py及editable_*.py。
重新导出必须用新的空目录，生成器会拒绝覆盖已经编辑过的文件夹。
'''


def render_all(output, figures):
    started = time.monotonic()
    records = []
    for number, row in enumerate(figures, 1):
        namespace = runpy.run_path(str(output / (row['id'] + '.py')))
        namespace['setup_style']()
        namespace['save'](namespace['draw']())
        records.append(dict(id=row['id'], files={
            ext: digest(output / (row['id'] + '.' + ext)) for ext in ('png', 'svg', 'pdf')}))
        write_json(output / '初次出图记录.json', dict(
            status='complete' if number == len(figures) else 'running',
            completed=number, total=len(figures), elapsed_seconds=round(time.monotonic() - started, 2),
            figures=records))
        print('初次出图：{}/{}'.format(number, len(figures)), flush=True)
    return records


def export_package(source, output, render=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Output exists; preserving your edits: ' + str(output))
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Output overlaps the original figure folder')
    index, source_hashes = verify_source(source)
    scripts = collect_programs(source)
    identifiers = {row['id'] for row in index['figures']}
    if len(identifiers) != 52 or set(scripts) != identifiers:
        raise ValueError('Generated scripts do not match all 52 original figure IDs')
    for ident, code in scripts.items():
        if Path(ident).name != ident:
            raise ValueError('Invalid figure ID')
        ast.parse(code, filename=ident + '.py')
    output.mkdir(parents=True)
    for ident, code in scripts.items():
        target = output / (ident + '.py')
        target.write_text(code, encoding='utf-8')
        target.chmod(0o755)
    (output / 'index.html').write_text(gallery(index['figures']), encoding='utf-8')
    (output / '使用说明.md').write_text(README, encoding='utf-8')
    manifest = dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                    source=str(source), source_hashes=source_hashes, figures=52,
                    scripts={ident + '.py': digest(output / (ident + '.py')) for ident in scripts},
                    note='Initial snapshot only; generated scripts are intended to be edited.')
    write_json(output / '初始来源记录.json', manifest)
    if render:
        render_all(output, index['figures'])
    for name, sha in source_hashes.items():
        if digest(source / name) != sha:
            raise ValueError('Original source changed during export: ' + name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--no-render', action='store_true')
    args = parser.parse_args()
    export_package(args.source, args.output, render=not args.no_render)
    print('完成：' + str(args.output.resolve() / 'index.html'))


if __name__ == '__main__':
    main()
