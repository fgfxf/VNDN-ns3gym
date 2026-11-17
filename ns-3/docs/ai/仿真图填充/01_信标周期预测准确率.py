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
PROVENANCE = {'source_table': 'docs/ai/仿真图填充/周期候选覆盖率逐轮数据.csv',
 'source_sha256': '8f8830bcc680a2c187f2644268c02e1278d7a3c80fc7d90b935a8988583c62a4',
 'source_metadata': 'docs/ai/仿真图填充/周期候选覆盖率来源.json',
 'definition': 'EVALUABLE records with label != source_rsu_id. Grid: unconditionally top two '
               'candidates. Circle/Spider: deployed float32 gap<=0.10 OR second>=0.10 '
               'one/two-candidate selection. These are distinct coverage metrics and conditions, '
               'not the same Top-1 accuracy or online ISR.',
 'error_bars': 'Grid: sample SD over three paired seeds. Circle/Spider: one seed per period, no '
               'error bar. Different definitions/conditions are stated per panel and in the '
               'documents.'}

DATA = {'panels': [{'scene': 'circle',
             'metric': 'adaptive_candidate_coverage',
             'speed_kmh': 60,
             'seeds': [85001],
             'xlabels': [20, 40, 80, 160],
             'xlabel': 'Beacon interval (ms)',
             'ylabel': 'Candidate coverage (%)',
             'subtitle': '(a) Circle\n60 km/h; 1 seed',
             'percent': True,
             'series': [{'label': '1/2 candidate rule',
                         'field': 'coverage_percent',
                         'points': [{'estimate': 96.1038961038961,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 77,
                                     'correct_count_total': 74},
                                    {'estimate': 92.7710843373494,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 83,
                                     'correct_count_total': 77},
                                    {'estimate': 87.3015873015873,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 63,
                                     'correct_count_total': 55},
                                    {'estimate': 71.42857142857143,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 35,
                                     'correct_count_total': 25}]}]},
            {'scene': 'grid',
             'metric': 'top2_candidate_coverage',
             'speed_kmh': 30,
             'seeds': [84001, 84002, 84003],
             'xlabels': [20, 40, 80, 160],
             'xlabel': 'Beacon interval (ms)',
             'ylabel': '',
             'subtitle': '(b) Grid\n30 km/h; 3 seeds',
             'percent': True,
             'series': [{'label': 'Top-2 candidates',
                         'field': 'coverage_percent',
                         'points': [{'estimate': 91.69210784244761,
                                     'run_sd': 2.712166743816326,
                                     'repetitions': 3,
                                     'defined_runs': 3,
                                     'sample_count_total': 268,
                                     'correct_count_total': 246},
                                    {'estimate': 86.42176231808956,
                                     'run_sd': 5.663025667646583,
                                     'repetitions': 3,
                                     'defined_runs': 3,
                                     'sample_count_total': 256,
                                     'correct_count_total': 222},
                                    {'estimate': 82.87789363236934,
                                     'run_sd': 6.545086628331549,
                                     'repetitions': 3,
                                     'defined_runs': 3,
                                     'sample_count_total': 255,
                                     'correct_count_total': 212},
                                    {'estimate': 82.80105642143162,
                                     'run_sd': 6.493631168809181,
                                     'repetitions': 3,
                                     'defined_runs': 3,
                                     'sample_count_total': 284,
                                     'correct_count_total': 236}]}]},
            {'scene': 'spidermap',
             'metric': 'adaptive_candidate_coverage',
             'speed_kmh': 60,
             'seeds': [85001],
             'xlabels': [20, 40, 80, 160],
             'xlabel': 'Beacon interval (ms)',
             'ylabel': '',
             'subtitle': '(c) Spider\n60 km/h; 1 seed',
             'percent': True,
             'series': [{'label': '1/2 candidate rule',
                         'field': 'coverage_percent',
                         'points': [{'estimate': 36.05898123324397,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 746,
                                     'correct_count_total': 269},
                                    {'estimate': 30.495552731893266,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 787,
                                     'correct_count_total': 240},
                                    {'estimate': 26.180836707152498,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 741,
                                     'correct_count_total': 194},
                                    {'estimate': 24.573378839590443,
                                     'run_sd': None,
                                     'repetitions': 1,
                                     'defined_runs': 1,
                                     'sample_count_total': 293,
                                     'correct_count_total': 72}]}]}]}

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
            defined = [j for j, error in enumerate(errors) if error is not None]
            if defined:
                ax.errorbar(x[defined], [centers[j] for j in defined],
                            yerr=[errors[j] for j in defined], fmt="none", ecolor="black",
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
            upper = max(point["estimate"] + (point["run_sd"] or 0.)
                        for other in row for item in other["series"]
                        for point in item["points"])
            if panel.get("percent"):
                upper = max(upper, 100.)
                ax.set_yticks(np.arange(0, 101, 20))
            ax.set_ylim(0, max(upper * 1.06, 1.))
        ax.text(.5, -.30 if LAYOUT[0] == 1 else -.31, panel["subtitle"],
                transform=ax.transAxes, ha="center", va="top", fontsize=FONT_SIZE)
    for axis in axes.flat:
        axis.legend(loc="upper right", fontsize=FONT_SIZE - 2, borderpad=.4)
    fig.subplots_adjust(left=.085 if LAYOUT[1] == 1 else .075,
                        right=.985, top=.94 if LAYOUT[0] == 1 else .90,
                        bottom=.28 if LAYOUT[0] == 1 else .15,
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
