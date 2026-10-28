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

FIGURE_ID = '02_状态表规模'
LAYOUT = (2, 3)
FIGSIZE = (13.2, 8.2)

# 来源仅供人工追溯；脚本不会访问这些路径。
PROVENANCE = {'source_table': 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026/state-summary.csv',
 'source_sha256': 'abcee7d2c9fa41a3eabf202626359f4839109105c85c2d88be3f540d1bf252eb',
 'campaign': 'paper-figures-followup-20261026',
 'definition': 'Network-wide real map key counts: m_vehicleToCs and m_csToVehicles; not memory '
               'bytes. 20 ms beacons, 5 Hz per vehicle, measurement [20,140) s; three seeds per '
               'vehicle count. Per-run time-weighted means and simultaneous network peaks, then '
               'mean/sample SD across runs.',
 'error_bars': 'One sample standard deviation; complete runs/processes are the repeat unit.'}

# 可编辑数据区：estimate 为柱高，run_sd 为误差线。
DATA = {'panels': [{'scene': 'circle',
             'metric': 'cache_vehicle_entries',
             'xlabels': [5, 10, 15, 20],
             'xlabel': 'Number of vehicles',
             'ylabel': 'Vehicle keys (entries)',
             'subtitle': '(a) Circle: Vehicle-cache index',
             'series': [{'label': 'Time-weighted mean',
                         'field': 'cache_vehicle_entries_mean',
                         'points': [{'estimate': 4.541919845813889,
                                     'run_sd': 0.03925194207157206,
                                     'repetitions': 3},
                                    {'estimate': 4.237220900955555,
                                     'run_sd': 0.07053223871046284,
                                     'repetitions': 3},
                                    {'estimate': 2.8605119095694445,
                                     'run_sd': 0.0758879147292613,
                                     'repetitions': 3},
                                    {'estimate': 1.888393983163889,
                                     'run_sd': 0.0065062618312925185,
                                     'repetitions': 3}]},
                        {'label': 'Simultaneous network peak',
                         'field': 'cache_vehicle_entries_peak',
                         'points': [{'estimate': 5.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 10.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 11.333333333333334,
                                     'run_sd': 0.5773502691896257,
                                     'repetitions': 3},
                                    {'estimate': 9.333333333333334,
                                     'run_sd': 0.5773502691896257,
                                     'repetitions': 3}]}]},
            {'scene': 'grid',
             'metric': 'cache_vehicle_entries',
             'xlabels': [5, 10, 15, 20],
             'xlabel': 'Number of vehicles',
             'ylabel': '',
             'subtitle': '(b) Grid: Vehicle-cache index',
             'series': [{'label': 'Time-weighted mean',
                         'field': 'cache_vehicle_entries_mean',
                         'points': [{'estimate': 4.120100661269444,
                                     'run_sd': 0.07908572536574714,
                                     'repetitions': 3},
                                    {'estimate': 7.774793780433334,
                                     'run_sd': 0.202369567644289,
                                     'repetitions': 3},
                                    {'estimate': 10.812005701152778,
                                     'run_sd': 0.5493061080244359,
                                     'repetitions': 3},
                                    {'estimate': 12.374784262991668,
                                     'run_sd': 0.5011389918733369,
                                     'repetitions': 3}]},
                        {'label': 'Simultaneous network peak',
                         'field': 'cache_vehicle_entries_peak',
                         'points': [{'estimate': 5.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 10.333333333333334,
                                     'run_sd': 0.5773502691896257,
                                     'repetitions': 3},
                                    {'estimate': 15.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 20.0, 'run_sd': 0.0, 'repetitions': 3}]}]},
            {'scene': 'spidermap',
             'metric': 'cache_vehicle_entries',
             'xlabels': [5, 10, 15, 20],
             'xlabel': 'Number of vehicles',
             'ylabel': '',
             'subtitle': '(c) Spider: Vehicle-cache index',
             'series': [{'label': 'Time-weighted mean',
                         'field': 'cache_vehicle_entries_mean',
                         'points': [{'estimate': 2.6858019744555555,
                                     'run_sd': 0.29487693402666637,
                                     'repetitions': 3},
                                    {'estimate': 5.352303120425,
                                     'run_sd': 0.5184870969980212,
                                     'repetitions': 3},
                                    {'estimate': 8.027842800727777,
                                     'run_sd': 0.23651695987452687,
                                     'repetitions': 3},
                                    {'estimate': 9.712456627794445,
                                     'run_sd': 0.7031193868444553,
                                     'repetitions': 3}]},
                        {'label': 'Simultaneous network peak',
                         'field': 'cache_vehicle_entries_peak',
                         'points': [{'estimate': 4.666666666666667,
                                     'run_sd': 0.5773502691896258,
                                     'repetitions': 3},
                                    {'estimate': 8.0, 'run_sd': 1.0, 'repetitions': 3},
                                    {'estimate': 12.0, 'run_sd': 1.0, 'repetitions': 3},
                                    {'estimate': 13.666666666666666,
                                     'run_sd': 0.5773502691896257,
                                     'repetitions': 3}]}]},
            {'scene': 'circle',
             'metric': 'cache_name_entries',
             'xlabels': [5, 10, 15, 20],
             'xlabel': 'Number of vehicles',
             'ylabel': 'Content-name keys (entries)',
             'subtitle': '(d) Circle: Content-vehicle index',
             'series': [{'label': 'Time-weighted mean',
                         'field': 'cache_name_entries_mean',
                         'points': [{'estimate': 30.929351539294444,
                                     'run_sd': 2.954354958323999,
                                     'repetitions': 3},
                                    {'estimate': 6.021396975291666,
                                     'run_sd': 0.1743157564637656,
                                     'repetitions': 3},
                                    {'estimate': 3.109802327388889,
                                     'run_sd': 0.11162801716515977,
                                     'repetitions': 3},
                                    {'estimate': 1.939145820936111,
                                     'run_sd': 0.01299656976437422,
                                     'repetitions': 3}]},
                        {'label': 'Simultaneous network peak',
                         'field': 'cache_name_entries_peak',
                         'points': [{'estimate': 50.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 26.333333333333332,
                                     'run_sd': 3.5118845842842465,
                                     'repetitions': 3},
                                    {'estimate': 14.333333333333334,
                                     'run_sd': 0.5773502691896257,
                                     'repetitions': 3},
                                    {'estimate': 10.333333333333334,
                                     'run_sd': 0.5773502691896257,
                                     'repetitions': 3}]}]},
            {'scene': 'grid',
             'metric': 'cache_name_entries',
             'xlabels': [5, 10, 15, 20],
             'xlabel': 'Number of vehicles',
             'ylabel': '',
             'subtitle': '(e) Grid: Content-vehicle index',
             'series': [{'label': 'Time-weighted mean',
                         'field': 'cache_name_entries_mean',
                         'points': [{'estimate': 34.98046380073889,
                                     'run_sd': 1.0639036208625927,
                                     'repetitions': 3},
                                    {'estimate': 56.39273862256667,
                                     'run_sd': 2.55698766087421,
                                     'repetitions': 3},
                                    {'estimate': 66.682535588075,
                                     'run_sd': 6.06112398160702,
                                     'repetitions': 3},
                                    {'estimate': 62.03614455180556,
                                     'run_sd': 3.458719254542382,
                                     'repetitions': 3}]},
                        {'label': 'Simultaneous network peak',
                         'field': 'cache_name_entries_peak',
                         'points': [{'estimate': 50.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 100.0, 'run_sd': 0.0, 'repetitions': 3},
                                    {'estimate': 139.33333333333334,
                                     'run_sd': 2.886751345948129,
                                     'repetitions': 3},
                                    {'estimate': 143.66666666666666,
                                     'run_sd': 2.886751345948129,
                                     'repetitions': 3}]}]},
            {'scene': 'spidermap',
             'metric': 'cache_name_entries',
             'xlabels': [5, 10, 15, 20],
             'xlabel': 'Number of vehicles',
             'ylabel': '',
             'subtitle': '(f) Spider: Content-vehicle index',
             'series': [{'label': 'Time-weighted mean',
                         'field': 'cache_name_entries_mean',
                         'points': [{'estimate': 25.164175549413887,
                                     'run_sd': 2.886768612895762,
                                     'repetitions': 3},
                                    {'estimate': 47.42747261923889,
                                     'run_sd': 3.0333973838717165,
                                     'repetitions': 3},
                                    {'estimate': 69.76242138528056,
                                     'run_sd': 2.0718961816531243,
                                     'repetitions': 3},
                                    {'estimate': 81.4150640955611,
                                     'run_sd': 6.694806530935399,
                                     'repetitions': 3}]},
                        {'label': 'Simultaneous network peak',
                         'field': 'cache_name_entries_peak',
                         'points': [{'estimate': 46.666666666666664,
                                     'run_sd': 5.773502691896258,
                                     'repetitions': 3},
                                    {'estimate': 80.0, 'run_sd': 10.0, 'repetitions': 3},
                                    {'estimate': 116.66666666666667,
                                     'run_sd': 15.275252316519467,
                                     'repetitions': 3},
                                    {'estimate': 136.66666666666666,
                                     'run_sd': 5.773502691896257,
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
