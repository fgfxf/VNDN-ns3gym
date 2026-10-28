#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11_消费者数量_蜘蛛网：单场景四指标图，只使用本文件内嵌数值。

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
FIGURE_ID = '11_消费者数量_蜘蛛网'
SCENE = 'spidermap'
SCENE_LABEL = 'Spider'
SCAN = 'vehicles'
SOURCE_SCAN = 'vehicles'
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
 'source_scan': 'vehicles',
 'source_xlabels': [5, 10, 15, 20],
 'xlabels': [5, 10, 15, 20],
 'xlabel': 'Number of consumers (vehicles)',
 'panels': [{'metric': 'extra_data_app_attempts',
             'title': 'Extra Data submissions',
             'ylabel': 'Extra Data application submissions',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0},
                                    {'estimate': 0.0, 'run_sd': 0.0}]},
                        {'strategy': 1,
                         'points': [{'estimate': 104.5, 'run_sd': 33.23401871576773},
                                    {'estimate': 127.0, 'run_sd': 11.313708498984761},
                                    {'estimate': 196.5, 'run_sd': 48.79036790187178},
                                    {'estimate': 223.0, 'run_sd': 25.45584412271571}]},
                        {'strategy': 2,
                         'points': [{'estimate': 70.5, 'run_sd': 23.33452377915607},
                                    {'estimate': 101.5, 'run_sd': 12.020815280171307},
                                    {'estimate': 111.0, 'run_sd': 12.727922061357855},
                                    {'estimate': 135.5, 'run_sd': 2.1213203435596424}]},
                        {'strategy': 3,
                         'points': [{'estimate': 22.5, 'run_sd': 6.363961030678928},
                                    {'estimate': 57.0, 'run_sd': 5.656854249492381},
                                    {'estimate': 94.0, 'run_sd': 5.656854249492381},
                                    {'estimate': 141.0, 'run_sd': 5.656854249492381}]}]},
            {'metric': 'mean_success_rtt_ms',
             'title': 'Average successful RTT',
             'ylabel': 'Mean successful RTT (ms)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 298.86374005289997,
                                     'run_sd': 0.0012144539962867919},
                                    {'estimate': 299.54242747696946, 'run_sd': 0.1471544820258444},
                                    {'estimate': 300.27095385113313, 'run_sd': 0.18585669019010742},
                                    {'estimate': 300.21169051926296,
                                     'run_sd': 0.11099819408263958}]},
                        {'strategy': 1,
                         'points': [{'estimate': 365.39060040954456, 'run_sd': 9.336459760172056},
                                    {'estimate': 337.8673325388889, 'run_sd': 12.043755018088932},
                                    {'estimate': 337.096076214133, 'run_sd': 1.717894568720236},
                                    {'estimate': 329.71994995013057,
                                     'run_sd': 1.8202358317063254}]},
                        {'strategy': 2,
                         'points': [{'estimate': 325.73031438534355, 'run_sd': 8.673028543185628},
                                    {'estimate': 317.51167665711756, 'run_sd': 0.5415087866242794},
                                    {'estimate': 313.2629317945372, 'run_sd': 1.1532382757312438},
                                    {'estimate': 312.96390880008335,
                                     'run_sd': 2.1495272426400547}]},
                        {'strategy': 3,
                         'points': [{'estimate': 299.82846748464374, 'run_sd': 0.18782658250346032},
                                    {'estimate': 301.3764063094037, 'run_sd': 0.6615637815583532},
                                    {'estimate': 303.78408523352624, 'run_sd': 0.7398566244627389},
                                    {'estimate': 305.01647441416094,
                                     'run_sd': 0.7871725751819509}]}]},
            {'metric': 'isr_percent',
             'title': 'Interest satisfaction ratio',
             'ylabel': 'Interest satisfaction ratio (%)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 52.3, 'run_sd': 7.401050976419193},
                                    {'estimate': 52.46666666666667, 'run_sd': 3.9362277486051167},
                                    {'estimate': 44.37222222222222, 'run_sd': 6.654660485166731},
                                    {'estimate': 42.287499999999994, 'run_sd': 3.706418044719487}]},
                        {'strategy': 1,
                         'points': [{'estimate': 53.43333333333334, 'run_sd': 5.279730632859551},
                                    {'estimate': 55.5, 'run_sd': 5.986837414046104},
                                    {'estimate': 49.37222222222222, 'run_sd': 7.97459314338162},
                                    {'estimate': 49.462500000000006, 'run_sd': 4.248533243629173}]},
                        {'strategy': 2,
                         'points': [{'estimate': 54.583333333333336, 'run_sd': 6.3875312567184785},
                                    {'estimate': 56.43333333333334, 'run_sd': 5.633284023452825},
                                    {'estimate': 50.23888888888889, 'run_sd': 8.383143728067179},
                                    {'estimate': 50.0, 'run_sd': 4.490128060534572}]},
                        {'strategy': 3,
                         'points': [{'estimate': 54.266666666666666, 'run_sd': 6.3168205785998275},
                                    {'estimate': 56.18333333333334, 'run_sd': 5.703994701571486},
                                    {'estimate': 49.91111111111111, 'run_sd': 8.375286986053998},
                                    {'estimate': 49.608333333333334,
                                     'run_sd': 4.478342947514798}]}]},
            {'metric': 'network_mbit',
             'title': 'Network overhead',
             'ylabel': 'NDN L3 outgoing traffic (Mbit)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 457.66733999999997, 'run_sd': 48.7929304568468},
                                    {'estimate': 936.225508, 'run_sd': 93.7404615025364},
                                    {'estimate': 1248.103464, 'run_sd': 205.47831793691785},
                                    {'estimate': 1654.335776, 'run_sd': 146.39953505507336}]},
                        {'strategy': 1,
                         'points': [{'estimate': 607.901748, 'run_sd': 68.83341143798089},
                                    {'estimate': 1233.60126, 'run_sd': 122.75677494471661},
                                    {'estimate': 1653.615812, 'run_sd': 275.5368908682539},
                                    {'estimate': 2189.157616, 'run_sd': 192.42848692763857}]},
                        {'strategy': 2,
                         'points': [{'estimate': 606.434348, 'run_sd': 70.59225187494158},
                                    {'estimate': 1234.377796, 'run_sd': 119.12446357628352},
                                    {'estimate': 1643.564644, 'run_sd': 269.57137602349206},
                                    {'estimate': 2175.078764, 'run_sd': 190.32886062012545}]},
                        {'strategy': 3,
                         'points': [{'estimate': 438.90631199999996, 'run_sd': 49.88030795124696},
                                    {'estimate': 897.456764, 'run_sd': 86.97938930354312},
                                    {'estimate': 1199.941488, 'run_sd': 196.071693397356},
                                    {'estimate': 1590.304676, 'run_sd': 139.84053134672618}]}]}]}


if __name__ == "__main__":
    main()
