#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""14_请求速率_蜘蛛网：单场景四指标图，只使用本文件内嵌数值。

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
FIGURE_ID = '14_请求速率_蜘蛛网'
SCENE = 'spidermap'
SCENE_LABEL = 'Spider'
SCAN = 'rate'
SOURCE_SCAN = 'interest'
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
DATA = {'scene': 'spidermap',
 'source_scan': 'interest',
 'source_xlabels': [1500, 3000, 6000, 9000, 12000],
 'xlabels': [12.5, 25.0, 50.0, 75.0, 100.0],
 'xlabel': 'Network request rate (requests/s)',
 'panels': [{'metric': 'extra_data_app_attempts',
             'title': 'Extra Data submissions',
             'ylabel': 'Extra Data application submissions',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0}]},
                        {'strategy': 1,
                         'points': [{'estimate': 19.5, 'run_sd': 9.192388155425117},
                                    {'estimate': 59.5, 'run_sd': 7.7781745930520225},
                                    {'estimate': 127.0, 'run_sd': 11.313708498984761},
                                    {'estimate': 219.0, 'run_sd': 49.49747468305833},
                                    {'estimate': 294.0, 'run_sd': 4.242640687119285}]},
                        {'strategy': 2,
                         'points': [{'estimate': 32.0, 'run_sd': 2.8284271247461903},
                                    {'estimate': 55.0, 'run_sd': 2.8284271247461903},
                                    {'estimate': 101.5, 'run_sd': 12.020815280171307},
                                    {'estimate': 140.5, 'run_sd': 3.5355339059327378},
                                    {'estimate': 190.5, 'run_sd': 6.363961030678928}]},
                        {'strategy': 3,
                         'points': [{'estimate': 12.0, 'run_sd': 0.0},
                                    {'estimate': 29.5, 'run_sd': 4.949747468305833},
                                    {'estimate': 57.0, 'run_sd': 5.656854249492381},
                                    {'estimate': 106.0, 'run_sd': 12.727922061357855},
                                    {'estimate': 140.5, 'run_sd': 20.506096654409877}]}]},
            {'metric': 'mean_success_rtt_ms',
             'title': 'Average successful RTT',
             'ylabel': 'Mean successful RTT (ms)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 299.21260107813487, 'run_sd': 0.5012390662451159},
                                    {'estimate': 299.14854537300346, 'run_sd': 0.24064638150387715},
                                    {'estimate': 299.54242747696946, 'run_sd': 0.1471544820258444},
                                    {'estimate': 300.85759133458276, 'run_sd': 0.4950340945198619},
                                    {'estimate': 302.3435213949766, 'run_sd': 1.544339926195319}]},
                        {'strategy': 1,
                         'points': [{'estimate': 320.2421576604116, 'run_sd': 12.906828801425105},
                                    {'estimate': 335.0237465217391, 'run_sd': 10.380689306214737},
                                    {'estimate': 337.8673325388889, 'run_sd': 12.043755018088932},
                                    {'estimate': 339.9470511375799, 'run_sd': 15.616339382518953},
                                    {'estimate': 333.68820489609607, 'run_sd': 4.696049196682399}]},
                        {'strategy': 2,
                         'points': [{'estimate': 324.7936166572104, 'run_sd': 7.277314687084304},
                                    {'estimate': 317.99694547741365, 'run_sd': 1.8516786998495744},
                                    {'estimate': 317.51167665711756, 'run_sd': 0.5415087866242794},
                                    {'estimate': 319.3461335303105, 'run_sd': 5.5285689692256685},
                                    {'estimate': 327.74237215380623,
                                     'run_sd': 10.051658717709007}]},
                        {'strategy': 3,
                         'points': [{'estimate': 299.6901398846154, 'run_sd': 0.11697734713170287},
                                    {'estimate': 300.2313729403561, 'run_sd': 0.023725751287907222},
                                    {'estimate': 301.3764063094037, 'run_sd': 0.6615637815583532},
                                    {'estimate': 305.59962336714256, 'run_sd': 3.2671997136736515},
                                    {'estimate': 312.37580452504653,
                                     'run_sd': 6.953309415483406}]}]},
            {'metric': 'isr_percent',
             'title': 'Interest satisfaction ratio',
             'ylabel': 'Interest satisfaction ratio (%)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 52.900000000000006, 'run_sd': 4.855466564147627},
                                    {'estimate': 53.21666666666667, 'run_sd': 5.2090199547409},
                                    {'estimate': 52.46666666666667, 'run_sd': 3.9362277486051167},
                                    {'estimate': 50.394444444444446, 'run_sd': 4.281924397185206},
                                    {'estimate': 48.9375, 'run_sd': 3.729988270759042}]},
                        {'strategy': 1,
                         'points': [{'estimate': 55.06666666666666, 'run_sd': 5.374011537017762},
                                    {'estimate': 55.583333333333336, 'run_sd': 5.821845831769242},
                                    {'estimate': 55.5, 'run_sd': 5.986837414046104},
                                    {'estimate': 55.644444444444446, 'run_sd': 5.421151989096863},
                                    {'estimate': 55.17916666666666, 'run_sd': 4.943854911795945}]},
                        {'strategy': 2,
                         'points': [{'estimate': 56.400000000000006, 'run_sd': 5.751135153650586},
                                    {'estimate': 56.45, 'run_sd': 5.633284023452825},
                                    {'estimate': 56.43333333333334, 'run_sd': 5.633284023452825},
                                    {'estimate': 56.361111111111114, 'run_sd': 5.460435699162783},
                                    {'estimate': 56.266666666666666, 'run_sd': 5.409366876077088}]},
                        {'strategy': 3,
                         'points': [{'estimate': 56.333333333333336, 'run_sd': 5.656854249492381},
                                    {'estimate': 56.16666666666667, 'run_sd': 5.751135153650586},
                                    {'estimate': 56.18333333333334, 'run_sd': 5.703994701571486},
                                    {'estimate': 56.03333333333333, 'run_sd': 5.484005925202333},
                                    {'estimate': 55.97916666666667, 'run_sd': 5.43882965862653}]}]},
            {'metric': 'network_mbit',
             'title': 'Network overhead',
             'ylabel': 'NDN L3 outgoing traffic (Mbit)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 302.363632, 'run_sd': 29.741816313386114},
                                    {'estimate': 513.735356, 'run_sd': 50.51991149067437},
                                    {'estimate': 936.225508, 'run_sd': 93.7404615025364},
                                    {'estimate': 1360.9093520000001, 'run_sd': 134.83237685829437},
                                    {'estimate': 1782.24152, 'run_sd': 174.5150057717304}]},
                        {'strategy': 1,
                         'points': [{'estimate': 373.380944, 'run_sd': 35.245200107089765},
                                    {'estimate': 661.028196, 'run_sd': 64.2930957665449},
                                    {'estimate': 1233.60126, 'run_sd': 122.75677494471661},
                                    {'estimate': 1811.5708439999999, 'run_sd': 169.59122892128383},
                                    {'estimate': 2380.782496, 'run_sd': 227.4120914668147}]},
                        {'strategy': 2,
                         'points': [{'estimate': 376.687068, 'run_sd': 37.386517430421364},
                                    {'estimate': 662.808728, 'run_sd': 64.07893292151337},
                                    {'estimate': 1234.377796, 'run_sd': 119.12446357628352},
                                    {'estimate': 1804.895228, 'run_sd': 174.62046650550366},
                                    {'estimate': 2374.225844, 'run_sd': 227.86243929047072}]},
                        {'strategy': 3,
                         'points': [{'estimate': 250.319068, 'run_sd': 23.84188137993879},
                                    {'estimate': 466.05140800000004, 'run_sd': 43.71865865594689},
                                    {'estimate': 897.456764, 'run_sd': 86.97938930354312},
                                    {'estimate': 1332.9248400000001, 'run_sd': 127.58022182819408},
                                    {'estimate': 1764.662568, 'run_sd': 167.98457483419742}]}]}]}


if __name__ == "__main__":
    main()
