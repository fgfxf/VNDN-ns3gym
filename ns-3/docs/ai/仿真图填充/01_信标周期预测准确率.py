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

FIGURE_ID = '01_信标周期预测准确率'
LAYOUT = (1, 3)
FIGSIZE = (12.6, 4.5)

# 来源仅供人工追溯；脚本不会访问这些路径。
PROVENANCE = {'source_table': 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026/accuracy-summary.csv',
 'source_sha256': 'a555c61750bbb5342aa38403e2cc76100f5c2ebece882a1baeb0e8eec9d456e2',
 'campaign': 'paper-figures-followup-20261026',
 'definition': 'Fixed-model top-1 on NoForward samples; three paired seed runs per period. Overall '
               'evaluable observations and handover subset; not online ISR.',
 'error_bars': 'One sample standard deviation; complete runs/processes are the repeat unit.'}

# 可编辑数据区：estimate 为柱高，run_sd 为误差线。
DATA = {'panels': [{'scene': 'circle',
             'metric': 'prediction_accuracy',
             'xlabels': [20, 40, 80, 160],
             'xlabel': 'Beacon interval (ms)',
             'ylabel': 'Prediction accuracy (%)',
             'subtitle': '(a) Circle',
             'percent': True,
             'series': [{'label': 'All evaluable',
                         'field': 'accuracy_percent',
                         'points': [{'estimate': 99.56458248614427,
                                     'run_sd': 0.07585908420425386,
                                     'repetitions': 3},
                                    {'estimate': 99.44336632810568,
                                     'run_sd': 0.10865108005549877,
                                     'repetitions': 3},
                                    {'estimate': 99.51578218329705,
                                     'run_sd': 0.1929065139438351,
                                     'repetitions': 3},
                                    {'estimate': 99.4814777152008,
                                     'run_sd': 0.04347496651540513,
                                     'repetitions': 3}]},
                        {'label': 'Handover subset',
                         'field': 'handover_accuracy_percent',
                         'points': [{'estimate': 96.14240173381677,
                                     'run_sd': 0.6873095058889488,
                                     'repetitions': 3},
                                    {'estimate': 95.02590147751438,
                                     'run_sd': 0.783454290053831,
                                     'repetitions': 3},
                                    {'estimate': 95.72806119282568,
                                     'run_sd': 1.5456342456692211,
                                     'repetitions': 3},
                                    {'estimate': 95.33048753380145,
                                     'run_sd': 0.39569737859700016,
                                     'repetitions': 3}]}]},
            {'scene': 'grid',
             'metric': 'prediction_accuracy',
             'xlabels': [20, 40, 80, 160],
             'xlabel': 'Beacon interval (ms)',
             'ylabel': '',
             'subtitle': '(b) Grid',
             'percent': True,
             'series': [{'label': 'All evaluable',
                         'field': 'accuracy_percent',
                         'points': [{'estimate': 97.89416430628074,
                                     'run_sd': 0.3692708382593232,
                                     'repetitions': 3},
                                    {'estimate': 97.59429940444335,
                                     'run_sd': 0.36597330106274906,
                                     'repetitions': 3},
                                    {'estimate': 97.70750954602242,
                                     'run_sd': 0.2433093609597028,
                                     'repetitions': 3},
                                    {'estimate': 97.01474201709692,
                                     'run_sd': 0.7327284179043659,
                                     'repetitions': 3}]},
                        {'label': 'Handover subset',
                         'field': 'handover_accuracy_percent',
                         'points': [{'estimate': 89.54455367498845,
                                     'run_sd': 1.0978307378631904,
                                     'repetitions': 3},
                                    {'estimate': 89.09266126373173,
                                     'run_sd': 0.7908026036152627,
                                     'repetitions': 3},
                                    {'estimate': 89.25230862059881,
                                     'run_sd': 1.1701342918877518,
                                     'repetitions': 3},
                                    {'estimate': 86.33416077913232,
                                     'run_sd': 0.285061401633669,
                                     'repetitions': 3}]}]},
            {'scene': 'spidermap',
             'metric': 'prediction_accuracy',
             'xlabels': [20, 40, 80, 160],
             'xlabel': 'Beacon interval (ms)',
             'ylabel': '',
             'subtitle': '(c) Spider',
             'percent': True,
             'series': [{'label': 'All evaluable',
                         'field': 'accuracy_percent',
                         'points': [{'estimate': 98.97697983815617,
                                     'run_sd': 0.1365017129841737,
                                     'repetitions': 3},
                                    {'estimate': 99.17590273166486,
                                     'run_sd': 0.06640127340070921,
                                     'repetitions': 3},
                                    {'estimate': 99.0384606359002,
                                     'run_sd': 0.11173501908184484,
                                     'repetitions': 3},
                                    {'estimate': 98.83427880225042,
                                     'run_sd': 0.17058246586735187,
                                     'repetitions': 3}]},
                        {'label': 'Handover subset',
                         'field': 'handover_accuracy_percent',
                         'points': [{'estimate': 90.93423460300926,
                                     'run_sd': 2.933623913107933,
                                     'repetitions': 3},
                                    {'estimate': 92.61071421978549,
                                     'run_sd': 0.8175898422804235,
                                     'repetitions': 3},
                                    {'estimate': 91.47588820490579,
                                     'run_sd': 0.7971095241386824,
                                     'repetitions': 3},
                                    {'estimate': 89.79324902237107,
                                     'run_sd': 0.9422147517254305,
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
