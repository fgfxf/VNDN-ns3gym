"""Generate readable standalone programs; no runtime project dependency."""
import math
import numbers


def literal(value, level=0):
    """Keep complete floating-point values, with compact numeric array lines."""
    if hasattr(value, 'item'):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return repr(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Nonfinite frozen value: use explicit None for missing data')
        return repr(value)
    pad, child = '    ' * level, '    ' * (level + 1)
    if isinstance(value, dict):
        if not value:
            return '{}'
        return '{\n' + ',\n'.join(child + repr(k) + ': ' + literal(v, level + 1)
                                  for k, v in value.items()) + '\n' + pad + '}'
    if isinstance(value, (list, tuple)):
        opening, closing = ('[', ']') if isinstance(value, list) else ('(', ')')
        if not value:
            return opening + closing
        simple = all(v is None or isinstance(v, (numbers.Number, str)) for v in value)
        if simple:
            chunks = [', '.join(literal(v) for v in value[i:i + 8])
                      for i in range(0, len(value), 8)]
            if len(chunks) == 1 and len(chunks[0]) < 100:
                suffix = ',' if isinstance(value, tuple) and len(value) == 1 else ''
                return opening + chunks[0] + suffix + closing
            return opening + '\n' + ',\n'.join(child + s for s in chunks) + ',\n' + pad + closing
        return opening + '\n' + ',\n'.join(child + literal(v, level + 1) for v in value) + ',\n' + pad + closing
    raise TypeError('Unsupported frozen value: ' + repr(type(value)))


def nice_limits(values, percent=False):
    """Select explicit bounds once during export, including errorbar endpoints."""
    values = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    low, high = min(values + [0.]), max(values + [0.])
    if percent:
        return (min(0, math.floor(low / 5) * 5), max(100, math.ceil(high / 5) * 5))
    scale = max(abs(low), abs(high), 1e-12)
    step = 10 ** math.floor(math.log10(scale)) / 5
    bottom = math.floor(low * 1.06 / step) * step if low < 0 else 0
    top = math.ceil(high * 1.06 / step) * step if high > 0 else step
    return (float('{:.12g}'.format(bottom)), float('{:.12g}'.format(top)))


IMPORTS = '''from pathlib import Path
import runpy
import re
import math
import matplotlib
matplotlib.use("Agg")  # 直接保存图片，无须弹出绘图窗口
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import numpy as np

# ========= 常用外观参数：可直接修改 =========
FONT_FAMILY = "Liberation Serif"  # 与原图相同的衬线字体；也可换 Times New Roman
FONT_SIZE = 11
DPI = 300
ALGORITHMS = ("Naive NDN", "VTDF", "RTVTDF", "TKAN-PDF")
COLORS = ("#808080", "#E69F00", "#009E73", "#8E5AA9")
HATCHES = ("", "///", "\\\\\\\\\\\\", "xx")
GROUP_WIDTH = 0.8
SCENES = ("circle", "grid", "spidermap")
SCENE_LABELS = {"circle": "Circle", "grid": "Grid", "spidermap": "Spider"}
'''

HELPERS = '''
def setup_style():
    """统一字体、黑边与向内刻度；导入单图读取数据时不会调用。"""
    plt.rcParams.update({
        "font.family": "serif", "font.serif": [FONT_FAMILY], "font.size": FONT_SIZE,
        "axes.labelsize": FONT_SIZE, "axes.titlesize": FONT_SIZE + 1,
        "axes.linewidth": .7, "axes.grid": False,
        "xtick.labelsize": FONT_SIZE - 1, "ytick.labelsize": FONT_SIZE - 1,
        "xtick.direction": "in", "ytick.direction": "in",
        "xtick.top": True, "ytick.right": True,
        "xtick.major.width": .7, "ytick.major.width": .7, "lines.linewidth": 1,
        "legend.fontsize": FONT_SIZE - 2, "legend.frameon": True,
        "legend.fancybox": False, "legend.edgecolor": "black", "legend.framealpha": 1,
        "hatch.linewidth": .35, "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "path", "savefig.facecolor": "white"})


def draw_bars(ax, xlabels, series):
    """绘制固定均值及SD；None留空并标N/A，不当作0。"""
    algorithm_series = all("strategy" in item for item in series)
    slots = 4 if algorithm_series else len(series)
    width = GROUP_WIDTH / slots
    for order, item in enumerate(series):
        slot = int(item["strategy"]) if algorithm_series else order
        color = COLORS[slot] if algorithm_series else item.get("color", COLORS[slot % 4])
        hatch = HATCHES[slot] if algorithm_series else item.get("hatch", HATCHES[slot % 4])
        label = ALGORITHMS[slot] if algorithm_series else item["label"]
        positions = np.arange(len(xlabels)) + (slot - (slots - 1) / 2) * width
        points = item["points"]
        valid = [i for i, point in enumerate(points) if point["estimate"] is not None]
        ax.bar(positions[valid], [points[i]["estimate"] for i in valid],
               width=width * .94, color=color, edgecolor="black", linewidth=.55,
               hatch=hatch, label=label, zorder=2)
        errors = [i for i in valid if points[i].get("run_sd") is not None]
        if errors:
            ax.errorbar(positions[errors], [points[i]["estimate"] for i in errors],
                        yerr=[points[i]["run_sd"] for i in errors], fmt="none",
                        ecolor="black", elinewidth=.65, capsize=2, capthick=.65, zorder=3)
        for i in set(range(len(points))) - set(valid):
            ax.text(positions[i], .012, "N/A", transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", rotation=90, fontsize=6.5)
    ax.set_xticks(np.arange(len(xlabels)))
    ax.set_xticklabels(["{:g}".format(x) if isinstance(x, (int, float)) else str(x)
                        for x in xlabels])


def finish(fig, three_d=False):
    """保留原图的布局风格；坐标上下界由上方参数明确指定。"""
    if three_d:
        fig.subplots_adjust(left=.02, right=.91, bottom=.14, top=.92, wspace=.2)
        return fig
    active = [ax for ax in fig.axes if ax.axison]
    for index, ax in enumerate(active):
        title = ax.get_title()
        if title:
            title = re.sub(r"^\\([a-z]\\)\\s*", "", title)
            ax.set_title("")
            prefix = ax.get_xlabel() + "\\n\\n" if ax.get_xlabel() else ""
            ax.set_xlabel(prefix + "(" + chr(97 + index) + ") " + title)
        ax.grid(False)
        ax.tick_params(direction="in", top=True, right=True, width=.7)
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color("black")
            spine.set_linewidth(.7)
    top = .91 if fig.legends else .99 if fig._suptitle else .98
    fig.tight_layout(rect=(0, 0, 1, top), pad=1.25, w_pad=2.0, h_pad=2.0)
    return fig


def load_plot(filename):
    """仅载入同文件夹脚本的参数和函数，不执行其主入口或生成图片。"""
    return runpy.run_path(str(Path(__file__).resolve().with_name(filename)))


def save(fig):
    """图片始终保存在本脚本旁边；重新运行会覆盖同名三种格式。"""
    folder = Path(__file__).resolve().parent
    temporary = []
    try:
        for extension in ("png", "svg", "pdf"):
            target = folder / (FIGURE_ID + "." + extension)
            pending = folder / ("." + FIGURE_ID + ".pending." + extension)
            temporary.append((pending, target))
            fig.savefig(pending, format=extension, dpi=DPI, bbox_inches="tight")
        for pending, target in temporary:
            pending.replace(target)
    finally:
        plt.close(fig)
        for pending, _ in temporary:
            if pending.exists():
                pending.unlink()
    print("已更新：" + FIGURE_ID + "（PNG / SVG / PDF）", flush=True)


def main():
    setup_style()
    save(draw())
    for identifier in RELATED_FIGURES:
        print("正在联动更新：" + identifier, flush=True)
        combined = load_plot(identifier + ".py")
        combined["setup_style"]()
        combined["save"](combined["draw"]())
    print("完成。刷新同文件夹的 index.html 即可查看。", flush=True)
'''


def make_script(identifier, parameter_code, draw_code, data_code, related=(), description=''):
    header = '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n'
    header += '"""' + identifier + '\n' + description + '\n'
    header += '数值来自已有实验的保存结果；此脚本只画图，不启动仿真或训练。\n'
    header += '修改参数或末尾DATA后运行；双击执行方式由操作系统的.py关联决定。\n"""\n\n'
    identity = 'FIGURE_ID = ' + repr(identifier) + '\nRELATED_FIGURES = ' + repr(tuple(related)) + '\n\n'
    return (header + IMPORTS + '\n' + identity + parameter_code.strip() + '\n' + HELPERS +
            '\n# ========= 本图绘制步骤 =========\n' + draw_code.strip() +
            '\n\n# ========= 完整绘图数值：只在此处修改数据 =========\n' + data_code.strip() +
            '\n\nif __name__ == "__main__":\n    main()\n')
