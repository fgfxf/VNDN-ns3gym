#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""07_车速_方阵：单场景四指标图，只使用本文件内嵌数值。

来源：paper-figures-followup-20261026/figures-paper-20261026/source-tables/aggregate.json。
数值已与 paper-editable-20261028 的对应单图逐项核对。
只需要 numpy / matplotlib，不读取其他脚本、原始数据或模型，不启动仿真或训练。
"""

from pathlib import Path
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np

# ========= 可编辑的外观参数 =========
FONT_FAMILY = "Liberation Serif"
FONT_SIZE = 11
FIGSIZE = (10.8, 7.7)
DPI = 300
ALGORITHMS = ("Naive NDN", "VTDF", "RTVTDF", "TKAN-PDF")
COLORS = ("#808080", "#E69F00", "#009E73", "#8E5AA9")
HATCHES = ("", "///", "\\\\\\", "xx")
GROUP_WIDTH = 0.8
LEGEND_COLUMNS = 4
# 内部X位置为0、1、2……，刻度标签取自末尾DATA["xlabels"]。
X_LIM = None
# 指标依次为额外Data应用提交、成功RTT、兴趣满足率、NDN L3网络负载。
# None自动覆盖完整柱高与SD端点；也可将某项改为(lower, upper)及刻度列表。
Y_LIMS = (None, None, None, None)
Y_TICKS = (None, None, None, None)
FIGURE_ID = '07_车速_方阵'
SCENE = 'grid'
SCENE_LABEL = 'Grid'
SCAN = 'speed'
SOURCE_SCAN = 'speed'
METRICS = ('extra_data_app_attempts', 'mean_success_rtt_ms', 'isr_percent', 'network_mbit')
RELATED_FIGURES = ()
MEASUREMENT_SECONDS = 120


def setup_style():
    """衬线字体、固定四算法颜色、黑边纹理及向内刻度。"""
    plt.rcParams.update({
        "font.family": "serif", "font.serif": [FONT_FAMILY], "font.size": FONT_SIZE,
        "axes.labelsize": FONT_SIZE, "axes.titlesize": FONT_SIZE + 1,
        "axes.linewidth": .7, "axes.grid": False,
        "xtick.labelsize": FONT_SIZE - 1, "ytick.labelsize": FONT_SIZE - 1,
        "xtick.direction": "in", "ytick.direction": "in",
        "xtick.top": True, "ytick.right": True,
        "xtick.major.width": .7, "ytick.major.width": .7,
        "legend.fontsize": FONT_SIZE - 1, "legend.frameon": True,
        "legend.fancybox": False, "legend.edgecolor": "black", "legend.framealpha": 1,
        "hatch.linewidth": .35, "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "path", "savefig.facecolor": "white"})


def automatic_y_limits(series, percent=False):
    """覆盖完整均值±SD；保留负误差端点，百分比至少展示0～100。"""
    endpoints = [0.0]
    for item in series:
        for point in item["points"]:
            mean, sd = point["estimate"], point["run_sd"]
            if mean is None:
                continue
            error = sd if sd is not None else 0.0
            endpoints.extend((mean - error, mean + error))
    lower, upper = min(endpoints), max(endpoints)
    if percent and lower >= 0 and upper <= 100:
        return (0.0, 100.0)
    upper = max(100.0, upper) if percent else upper
    span = upper - lower
    if span <= 0:
        return (0.0, 1.0)
    lower = lower - span * .06 if lower < 0 else 0.0
    upper += span * .08
    target = (upper - lower) / 5.0
    magnitude = 10.0 ** math.floor(math.log10(target))
    step = next(value * magnitude for value in (1, 2, 2.5, 5, 10)
                if value * magnitude >= target)
    return (math.floor(lower / step) * step, math.ceil(upper / step) * step)


def validate_data():
    """手工编辑后，错误维度、非有限值或负SD明确报错，None保持缺失语义。"""
    if len(DATA["panels"]) != 4 or tuple(p["metric"] for p in DATA["panels"]) != METRICS:
        raise ValueError("DATA must contain the four metrics in METRICS order")
    count = len(DATA["xlabels"])
    if not count:
        raise ValueError("DATA must include at least one x label")
    for panel in DATA["panels"]:
        if [item["strategy"] for item in panel["series"]] != list(range(4)):
            raise ValueError("Each panel must retain all four strategies in order")
        for item in panel["series"]:
            if len(item["points"]) != count:
                raise ValueError("Point count must match xlabels")
            for point in item["points"]:
                for key in ("estimate", "run_sd"):
                    value = point[key]
                    if value is not None and not math.isfinite(value):
                        raise ValueError(key + " must be finite or None")
                if point["run_sd"] is not None and point["run_sd"] < 0:
                    raise ValueError("run_sd must not be negative")


def draw_bars(ax, panel):
    positions = np.arange(len(DATA["xlabels"]), dtype=float)
    width = GROUP_WIDTH / len(ALGORITHMS)
    for item in panel["series"]:
        strategy = item["strategy"]
        x = positions + (strategy - 1.5) * width
        points = item["points"]
        present = [i for i, point in enumerate(points) if point["estimate"] is not None]
        ax.bar(x[present], [points[i]["estimate"] for i in present],
               width=width * .94, color=COLORS[strategy], edgecolor="black",
               linewidth=.55, hatch=HATCHES[strategy], label=ALGORITHMS[strategy], zorder=2)
        with_sd = [i for i in present if points[i]["run_sd"] is not None]
        if with_sd:
            ax.errorbar(x[with_sd], [points[i]["estimate"] for i in with_sd],
                        yerr=[points[i]["run_sd"] for i in with_sd], fmt="none",
                        ecolor="black", elinewidth=.65, capsize=2, capthick=.65, zorder=3)
        for i, point in enumerate(points):
            if point["estimate"] is None:
                ax.text(x[i], .015, "N/A", transform=ax.get_xaxis_transform(),
                        ha="center", va="bottom", rotation=90, fontsize=7)
    ax.set_xticks(positions)
    ax.set_xticklabels(["{:g}".format(value) for value in DATA["xlabels"]])


def draw():
    """创建2×2图；不保存、不更新其他图片。"""
    validate_data()
    setup_style()
    fig, axes = plt.subplots(2, 2, figsize=FIGSIZE)
    for index, (ax, panel) in enumerate(zip(axes.flat, DATA["panels"])):
        draw_bars(ax, panel)
        ax.set_xlim(X_LIM if X_LIM is not None else (-.6, len(DATA["xlabels"]) - .4))
        limits = Y_LIMS[index]
        if limits is None:
            limits = automatic_y_limits(panel["series"], panel["metric"] == "isr_percent")
        ax.set_ylim(limits)
        if Y_TICKS[index] is None:
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=3))
        else:
            ax.set_yticks(Y_TICKS[index])
        ax.set_ylabel(panel["ylabel"])
        ax.set_xlabel(DATA["xlabel"] + "\n\n({}) {}".format("abcd"[index], panel["title"]))
        ax.tick_params(direction="in", top=True, right=True, width=.7)
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_color("black")
            spine.set_linewidth(.7)
    handles = [Patch(facecolor=COLORS[i], edgecolor="black", linewidth=.55,
                     hatch=HATCHES[i], label=name) for i, name in enumerate(ALGORITHMS)]
    fig.legend(handles=handles, loc="upper center", ncol=LEGEND_COLUMNS,
               bbox_to_anchor=(.5, .995))
    fig.suptitle(SCENE_LABEL, y=.94, fontsize=FONT_SIZE + 1)
    fig.tight_layout(rect=(0, 0, 1, .925), pad=1.25, w_pad=2.4, h_pad=2.0)
    return fig


def save(fig):
    """仅覆盖本脚本旁同名PNG/SVG/PDF，三个格式渲染成功后替换。"""
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
    save(draw())


# ========= 完整绘图数值：可直接编辑 =========
# estimate保留26图集的原中心值；run_sd是样本标准差，不是置信区间。
# 成功RTT仍按成功请求数加权，不重算为每轮均值的简单平均。
# None不可评价，0为真实零；每个points依次对应xlabels。
# 请求速率图仅把横轴由请求总数K换成全网K/120，不改变任何纵轴值。
DATA = {'scene': 'grid',
 'source_scan': 'speed',
 'source_xlabels': [15, 30, 50, 60],
 'xlabels': [15, 30, 50, 60],
 'xlabel': 'Vehicle speed setting (km/h)',
 'panels': [{'metric': 'extra_data_app_attempts',
             'title': 'Extra Data submissions',
             'ylabel': 'Extra Data application submissions',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0}]},
                        {'strategy': 1,
                         'points': [{'estimate': 453.0, 'run_sd': 156.97770542341354},
                                    {'estimate': 572.5, 'run_sd': 137.88582233137677},
                                    {'estimate': 730.0, 'run_sd': 280.0142853498728},
                                    {'estimate': 671.0, 'run_sd': 196.5756851698602}]},
                        {'strategy': 2,
                         'points': [{'estimate': 272.5, 'run_sd': 24.748737341529164},
                                    {'estimate': 378.5, 'run_sd': 64.34671708797582},
                                    {'estimate': 434.0, 'run_sd': 97.58073580374356},
                                    {'estimate': 432.5, 'run_sd': 119.50104602052653}]},
                        {'strategy': 3,
                         'points': [{'estimate': 313.5, 'run_sd': 30.405591591021544},
                                    {'estimate': 286.5, 'run_sd': 36.062445840513924},
                                    {'estimate': 283.5, 'run_sd': 54.44722215136416},
                                    {'estimate': 279.0, 'run_sd': 62.22539674441618}]}]},
            {'metric': 'mean_success_rtt_ms',
             'title': 'Average successful RTT',
             'ylabel': 'Mean successful RTT (ms)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 300.3555712234771, 'run_sd': 0.25526208160489205},
                                    {'estimate': 300.23827930879105, 'run_sd': 0.16960697218770898},
                                    {'estimate': 300.036676052659, 'run_sd': 0.4395768425935877},
                                    {'estimate': 300.06914310412344,
                                     'run_sd': 0.47238875849107465}]},
                        {'strategy': 1,
                         'points': [{'estimate': 320.57494833457724, 'run_sd': 0.9291722766977324},
                                    {'estimate': 373.893470490491, 'run_sd': 5.236908709543978},
                                    {'estimate': 382.99453212606966, 'run_sd': 25.117671457814954},
                                    {'estimate': 382.5466519237972, 'run_sd': 27.13089284726596}]},
                        {'strategy': 2,
                         'points': [{'estimate': 342.9961278291208, 'run_sd': 7.488909935141725},
                                    {'estimate': 346.97406868482705, 'run_sd': 4.90679455512209},
                                    {'estimate': 355.4217320482151, 'run_sd': 10.032426484801844},
                                    {'estimate': 357.95742802037415, 'run_sd': 14.9996561330118}]},
                        {'strategy': 3,
                         'points': [{'estimate': 310.23806602572375, 'run_sd': 3.041810027878493},
                                    {'estimate': 312.33557095327274, 'run_sd': 8.183542974660808},
                                    {'estimate': 313.7947533073139, 'run_sd': 10.325643386497303},
                                    {'estimate': 314.2055647671525,
                                     'run_sd': 12.270275737254043}]}]},
            {'metric': 'isr_percent',
             'title': 'Interest satisfaction ratio',
             'ylabel': 'Interest satisfaction ratio (%)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 69.35833333333333, 'run_sd': 0.27105759945483787},
                                    {'estimate': 64.17500000000001, 'run_sd': 1.7324116139070433},
                                    {'estimate': 64.09166666666667, 'run_sd': 4.325136478257721},
                                    {'estimate': 64.26666666666667, 'run_sd': 3.6769552621700443}]},
                        {'strategy': 1,
                         'points': [{'estimate': 84.85833333333333, 'run_sd': 0.9545941546018352},
                                    {'estimate': 85.88333333333333, 'run_sd': 2.309882151876055},
                                    {'estimate': 83.75, 'run_sd': 3.7240957142491595},
                                    {'estimate': 83.65833333333333, 'run_sd': 3.7123106012293743}]},
                        {'strategy': 2,
                         'points': [{'estimate': 92.31666666666666, 'run_sd': 1.4613540144521955},
                                    {'estimate': 91.775, 'run_sd': 0.7424621202458729},
                                    {'estimate': 89.875, 'run_sd': 1.4259986753928802},
                                    {'estimate': 89.98333333333333, 'run_sd': 1.5320646925708463}]},
                        {'strategy': 3,
                         'points': [{'estimate': 90.38333333333333, 'run_sd': 0.4949747468305853},
                                    {'estimate': 89.88333333333333, 'run_sd': 1.6499158227686075},
                                    {'estimate': 89.78333333333333, 'run_sd': 1.3906433363335449},
                                    {'estimate': 89.75833333333333,
                                     'run_sd': 1.7324116139070433}]}]},
            {'metric': 'network_mbit',
             'title': 'Network overhead',
             'ylabel': 'NDN L3 outgoing traffic (Mbit)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 1532.0270879999998, 'run_sd': 19.32640495551227},
                                    {'estimate': 1528.942432, 'run_sd': 6.605078786209231},
                                    {'estimate': 1519.56798, 'run_sd': 4.505610870615513},
                                    {'estimate': 1518.987788, 'run_sd': 3.6832852820751962}]},
                        {'strategy': 1,
                         'points': [{'estimate': 2036.9587080000001, 'run_sd': 42.666127383723676},
                                    {'estimate': 2053.3075360000003, 'run_sd': 12.167655902779646},
                                    {'estimate': 2058.041088, 'run_sd': 27.71825772496625},
                                    {'estimate': 2053.00404, 'run_sd': 17.877198092751897}]},
                        {'strategy': 2,
                         'points': [{'estimate': 2041.169508, 'run_sd': 29.100832501521907},
                                    {'estimate': 2050.0813200000002, 'run_sd': 18.00766777916206},
                                    {'estimate': 2038.875928, 'run_sd': 21.26881031286874},
                                    {'estimate': 2038.390956, 'run_sd': 26.51235782033051}]},
                        {'strategy': 3,
                         'points': [{'estimate': 1511.992176, 'run_sd': 23.980027417565545},
                                    {'estimate': 1505.6086639999999, 'run_sd': 13.690356615949407},
                                    {'estimate': 1500.161808, 'run_sd': 17.037019472200242},
                                    {'estimate': 1499.754848, 'run_sd': 17.30456605078417}]}]}]}


if __name__ == "__main__":
    main()
