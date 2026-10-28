#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立重画本文件对应的图片；修改外观参数或 DATA 后直接运行。

所有绘图数据已内嵌，不读取实验目录、其他脚本或外部数表。
运行只覆盖本脚本同目录、同名的 PNG/SVG/PDF，不启动仿真或训练。
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# 常用外观参数。图中文字保持英文。
FONT_FAMILY = "Liberation Serif"
FONT_SIZE = 11
DPI = 300
COLORS = ("#8E5AA9", "#C7ACD8")
HATCHES = ("xx", "///")
GROUP_WIDTH = 0.76
# None 自动保留均值及完整误差线；需要时可改为每个子图的 (下限, 上限)。
Y_LIMITS = None

FIGURE_ID = '03_注册与更新报文大小'
LAYOUT = (1, 1)
FIGSIZE = (8.7, 4.7)

# 来源仅供人工追溯；脚本不会访问这些路径。
PROVENANCE = {'source_table': 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026/hello-size-points.csv',
 'source_sha256': '606d96a8cf19b1bf3ae9cc4a41babc2311794646c671f801a8c410b1e5d0ef42',
 'campaign': 'paper-figures-followup-20261026',
 'definition': 'Complete NDN-encoded hello Data before application put; not MAC or successful '
               'delivery bytes. 20 ms beacons, 10 vehicles. Startup registration [0,20) s; steady '
               'cache delta [20,140) s. Three per-run mean packet sizes, then equal-run mean and '
               'sample SD.',
 'error_bars': 'One sample standard deviation; complete runs/processes are the repeat unit.'}

# 可编辑数据区：estimate 为柱高，run_sd 为误差线。
DATA = {'panels': [{'scene': 'all',
             'metric': 'hello_wire_bytes',
             'xlabels': ['Circle', 'Grid', 'Spider'],
             'xlabel': 'Scenario',
             'ylabel': 'Encoded hello Data size (bytes)',
             'subtitle': 'Registration and cache-update messages (20 ms beacons)',
             'series': [{'label': 'Registration (startup)',
                         'field': 'registration',
                         'phase': 'startup',
                         'points': [{'estimate': 111.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 108.06666666666666,
                                     'run_sd': 0.2309401076758536,
                                     'repetitions': 3},
                                    {'estimate': 109.57407407407408,
                                     'run_sd': 0.39414438247764094,
                                     'repetitions': 3}]},
                        {'label': 'Cache update (steady state)',
                         'field': 'delta',
                         'phase': 'measurement',
                         'points': [{'estimate': 185.46444650962033,
                                     'run_sd': 0.05135711077396312,
                                     'repetitions': 3},
                                    {'estimate': 186.79445364932502,
                                     'run_sd': 0.024305052523659477,
                                     'repetitions': 3},
                                    {'estimate': 185.74562068843807,
                                     'run_sd': 1.2503256110898147,
                                     'repetitions': 3}]}]}]}


def setup_style():
    plt.rcParams.update({
        "font.family": "serif", "font.serif": [FONT_FAMILY],
        "font.size": FONT_SIZE, "axes.labelsize": FONT_SIZE,
        "axes.linewidth": .7, "axes.grid": False,
        "xtick.labelsize": FONT_SIZE - 1, "ytick.labelsize": FONT_SIZE - 1,
        "xtick.direction": "in", "ytick.direction": "in",
        "xtick.top": True, "ytick.right": True,
        "legend.fontsize": FONT_SIZE - 1, "legend.frameon": True,
        "legend.fancybox": False, "legend.edgecolor": "black",
        "legend.framealpha": 1, "hatch.linewidth": .4,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "path",
        "savefig.facecolor": "white"})


def draw():
    """返回完整Figure，便于检查/调样式；此函数不读写文件。"""
    setup_style()
    fig, axes = plt.subplots(*LAYOUT, figsize=FIGSIZE, squeeze=False)
    panels = DATA["panels"]
    for index, (ax, panel) in enumerate(zip(axes.flat, panels)):
        series = panel["series"]
        positions = np.arange(len(panel["xlabels"]))
        width = GROUP_WIDTH / len(series)
        for order, item in enumerate(series):
            points = item["points"]
            centers = [point["estimate"] for point in points]
            errors = [point["run_sd"] for point in points]
            x = positions + (order - (len(series) - 1) / 2) * width
            ax.bar(x, centers, width=width * .94, color=COLORS[order],
                   hatch=HATCHES[order], edgecolor="black", linewidth=.65,
                   label=item["label"], zorder=2)
            ax.errorbar(x, centers, yerr=errors, fmt="none", ecolor="black",
                        elinewidth=.75, capsize=2.5, capthick=.75, zorder=3)
        ax.set_xticks(positions)
        ax.set_xticklabels(panel["xlabels"])
        ax.set_xlim(-.6, len(positions) - .4)
        ax.set_xlabel(panel["xlabel"], labelpad=7)
        ax.set_ylabel(panel["ylabel"])
        ax.grid(axis="y", alpha=.2, zorder=0)
        if Y_LIMITS is not None:
            ax.set_ylim(*Y_LIMITS[index])
        else:
            # 同一行统一纵轴；上限覆盖所有均值+SD，并留6%空白。
            row_start = (index // LAYOUT[1]) * LAYOUT[1]
            row = panels[row_start:row_start + LAYOUT[1]]
            upper = max(point["estimate"] + point["run_sd"]
                        for other in row for item in other["series"]
                        for point in item["points"])
            if panel.get("percent"):
                upper = max(upper, 100.)
                ax.set_yticks(np.arange(0, 101, 20))
            ax.set_ylim(0, max(upper * 1.06, 1.))
        ax.text(.5, -.30 if LAYOUT[0] == 1 else -.31, panel["subtitle"],
                transform=ax.transAxes, ha="center", va="top", fontsize=FONT_SIZE)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .99),
               ncol=2, borderpad=.55, columnspacing=2.)
    fig.subplots_adjust(left=.085 if LAYOUT[1] == 1 else .075,
                        right=.985, top=.85 if LAYOUT[0] == 1 else .90,
                        bottom=.25 if LAYOUT[0] == 1 else .15,
                        wspace=.29, hspace=.72)
    return fig


def main():
    fig = draw()
    output = Path(__file__).resolve().parent
    paths = []
    for extension in ("png", "svg", "pdf"):
        path = output / (FIGURE_ID + "." + extension)
        fig.savefig(str(path), dpi=DPI, bbox_inches="tight", pad_inches=.12)
        paths.append(path)
    plt.close(fig)
    return paths


if __name__ == "__main__":
    main()
