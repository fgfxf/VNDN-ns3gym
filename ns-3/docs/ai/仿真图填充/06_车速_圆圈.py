#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""06_车速_圆圈：单场景四指标图，只使用本文件内嵌数值。

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
FIGURE_ID = '06_车速_圆圈'
SCENE = 'circle'
SCENE_LABEL = 'Circle'
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
DATA = {'scene': 'circle',
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
                         'points': [{'estimate': 586.5, 'run_sd': 61.518289963229634},
                                    {'estimate': 939.5, 'run_sd': 10.606601717798213},
                                    {'estimate': 1127.0, 'run_sd': 56.568542494923804},
                                    {'estimate': 1231.0, 'run_sd': 164.04877323527901}]},
                        {'strategy': 2,
                         'points': [{'estimate': 29.5, 'run_sd': 4.949747468305833},
                                    {'estimate': 69.0, 'run_sd': 2.8284271247461903},
                                    {'estimate': 115.0, 'run_sd': 5.656854249492381},
                                    {'estimate': 137.5, 'run_sd': 3.5355339059327378}]},
                        {'strategy': 3,
                         'points': [{'estimate': 58.0, 'run_sd': 0.0},
                                    {'estimate': 107.0, 'run_sd': 16.97056274847714},
                                    {'estimate': 99.0, 'run_sd': 5.656854249492381},
                                    {'estimate': 121.0, 'run_sd': 1.4142135623730951}]}]},
            {'metric': 'mean_success_rtt_ms',
             'title': 'Average successful RTT',
             'ylabel': 'Mean successful RTT (ms)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 184.40855692327423, 'run_sd': 1.2290082606034083},
                                    {'estimate': 184.45841150294262, 'run_sd': 1.2267046003615982},
                                    {'estimate': 184.63169679033817, 'run_sd': 0.88823063530771},
                                    {'estimate': 184.2493542534462, 'run_sd': 0.6458441784341373}]},
                        {'strategy': 1,
                         'points': [{'estimate': 221.24137891056057, 'run_sd': 2.106765216765906},
                                    {'estimate': 222.80356390122262, 'run_sd': 0.918591133756543},
                                    {'estimate': 231.78058500209954, 'run_sd': 1.8903874698341154},
                                    {'estimate': 243.97068882329367, 'run_sd': 6.917089006217308}]},
                        {'strategy': 2,
                         'points': [{'estimate': 414.71304266189054, 'run_sd': 15.422961498819559},
                                    {'estimate': 423.0756051189195, 'run_sd': 10.033880033929238},
                                    {'estimate': 437.62621692351473, 'run_sd': 19.13588082791075},
                                    {'estimate': 438.33995957127087,
                                     'run_sd': 3.5162032047529346}]},
                        {'strategy': 3,
                         'points': [{'estimate': 332.57786146310457, 'run_sd': 0.8897707051249019},
                                    {'estimate': 353.5198827994037, 'run_sd': 0.6472091483970368},
                                    {'estimate': 346.0676201150014, 'run_sd': 4.262512385782687},
                                    {'estimate': 366.53989835725696,
                                     'run_sd': 1.0123726508206345}]}]},
            {'metric': 'isr_percent',
             'title': 'Interest satisfaction ratio',
             'ylabel': 'Interest satisfaction ratio (%)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 35.733333333333334, 'run_sd': 2.168460795638743},
                                    {'estimate': 33.983333333333334, 'run_sd': 3.064129385141705},
                                    {'estimate': 34.5, 'run_sd': 2.875567576825291},
                                    {'estimate': 34.458333333333336,
                                     'run_sd': 2.2980970388562794}]},
                        {'strategy': 1,
                         'points': [{'estimate': 71.65, 'run_sd': 0.30641293851416324},
                                    {'estimate': 68.84166666666667, 'run_sd': 0.6481812160876619},
                                    {'estimate': 67.475, 'run_sd': 0.9781643806413954},
                                    {'estimate': 66.54166666666666,
                                     'run_sd': 0.24748737341529767}]},
                        {'strategy': 2,
                         'points': [{'estimate': 83.75, 'run_sd': 0.18856180831642205},
                                    {'estimate': 83.6, 'run_sd': 0.30641293851416324},
                                    {'estimate': 83.45833333333333, 'run_sd': 1.2374368670764582},
                                    {'estimate': 83.01666666666668, 'run_sd': 1.2256517540566831}]},
                        {'strategy': 3,
                         'points': [{'estimate': 90.45833333333333, 'run_sd': 0.48318963381081015},
                                    {'estimate': 89.44166666666666, 'run_sd': 0.38890872965259915},
                                    {'estimate': 89.49166666666667, 'run_sd': 1.1667261889577973},
                                    {'estimate': 88.70833333333334,
                                     'run_sd': 0.9781643806413954}]}]},
            {'metric': 'network_mbit',
             'title': 'Network overhead',
             'ylabel': 'NDN L3 outgoing traffic (Mbit)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 1612.899788, 'run_sd': 1.9029148578409454},
                                    {'estimate': 1614.9243040000001, 'run_sd': 1.8592722273061661},
                                    {'estimate': 1613.984112, 'run_sd': 1.140919619871724},
                                    {'estimate': 1613.205292, 'run_sd': 0.24089713821464737}]},
                        {'strategy': 1,
                         'points': [{'estimate': 2060.561596, 'run_sd': 3.4373931415584784},
                                    {'estimate': 2103.546708, 'run_sd': 1.9172493265093038},
                                    {'estimate': 2131.7992679999998, 'run_sd': 1.5183166511263786},
                                    {'estimate': 2147.030972, 'run_sd': 32.82978556795323}]},
                        {'strategy': 2,
                         'points': [{'estimate': 2077.3487, 'run_sd': 0.3032809268782681},
                                    {'estimate': 2075.43976, 'run_sd': 4.41432621359137},
                                    {'estimate': 2086.655768, 'run_sd': 0.8025492260841801},
                                    {'estimate': 2086.314208, 'run_sd': 2.5773985605707175}]},
                        {'strategy': 3,
                         'points': [{'estimate': 1539.44594, 'run_sd': 2.231204737355942},
                                    {'estimate': 1546.6123360000001, 'run_sd': 1.2909846494021717},
                                    {'estimate': 1541.813676, 'run_sd': 0.6733410181713658},
                                    {'estimate': 1543.114352, 'run_sd': 0.36616817556962644}]}]}]}


if __name__ == "__main__":
    main()
