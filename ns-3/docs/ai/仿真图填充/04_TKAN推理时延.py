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

FIGURE_ID = '04_TKAN推理时延'
LAYOUT = (1, 2)
FIGSIZE = (10.5, 4.7)

# 来源仅供人工追溯；脚本不会访问这些路径。
PROVENANCE = {'source_table': 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026/inference-processes.csv',
 'source_sha256': '1cd19d7eedf34684a46c14c1ade5590111458e31c5868591adedb58025445683',
 'campaign': 'paper-figures-followup-20261026',
 'definition': 'Saved Intel Core i7-14700 CPU measurements; one thread, batch=1, eval/no_grad; 100 '
               'warmups and 1000 timings in each of five fresh processes per model. Mean/sample SD '
               'across process medians or P95s. Controller compute includes normalization, softmax '
               'and candidate mapping; both exclude loading/Gym/I-O and are not simulation RTT.',
 'error_bars': 'One sample standard deviation; complete runs/processes are the repeat unit.'}

# 可编辑数据区：estimate 为柱高，run_sd 为误差线。
DATA = {'panels': [{'scene': 'all',
             'metric': 'median_us',
             'xlabels': ['Circle', 'Grid', 'Spider'],
             'xlabel': 'Scenario',
             'ylabel': 'CPU compute time (microseconds)',
             'subtitle': '(a) Within-process median',
             'series': [{'label': 'Forward pass',
                         'field': 'forward',
                         'statistic': 'median_us',
                         'points': [{'estimate': 1398.355,
                                     'run_sd': 8.346614373505046,
                                     'repetitions': 5},
                                    {'estimate': 1413.039,
                                     'run_sd': 10.790435469664699,
                                     'repetitions': 5},
                                    {'estimate': 1409.1001999999999,
                                     'run_sd': 7.223148357883822,
                                     'repetitions': 5}]},
                        {'label': 'Controller compute',
                         'field': 'controller_compute',
                         'statistic': 'median_us',
                         'points': [{'estimate': 1480.18,
                                     'run_sd': 8.516984846469958,
                                     'repetitions': 5},
                                    {'estimate': 1501.7294,
                                     'run_sd': 10.47904120971951,
                                     'repetitions': 5},
                                    {'estimate': 1504.0606,
                                     'run_sd': 9.136998237933518,
                                     'repetitions': 5}]}]},
            {'scene': 'all',
             'metric': 'p95_us',
             'xlabels': ['Circle', 'Grid', 'Spider'],
             'xlabel': 'Scenario',
             'ylabel': '',
             'subtitle': '(b) Within-process P95',
             'series': [{'label': 'Forward pass',
                         'field': 'forward',
                         'statistic': 'p95_us',
                         'points': [{'estimate': 1686.5500299999999,
                                     'run_sd': 21.306983445387047,
                                     'repetitions': 5},
                                    {'estimate': 1721.8780599999998,
                                     'run_sd': 42.84151753857467,
                                     'repetitions': 5},
                                    {'estimate': 1701.93193,
                                     'run_sd': 40.06441648094043,
                                     'repetitions': 5}]},
                        {'label': 'Controller compute',
                         'field': 'controller_compute',
                         'statistic': 'p95_us',
                         'points': [{'estimate': 1774.44668,
                                     'run_sd': 13.179633726397745,
                                     'repetitions': 5},
                                    {'estimate': 1813.0648199999998,
                                     'run_sd': 32.37866717162314,
                                     'repetitions': 5},
                                    {'estimate': 1791.08405,
                                     'run_sd': 40.24868817643311,
                                     'repetitions': 5}]}]}]}


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
