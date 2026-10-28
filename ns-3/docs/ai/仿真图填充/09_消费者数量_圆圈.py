#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09_消费者数量_圆圈：单场景四指标图，只使用本文件内嵌数值。

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
FIGURE_ID = '09_消费者数量_圆圈'
SCENE = 'circle'
SCENE_LABEL = 'Circle'
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
DATA = {'scene': 'circle',
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
                         'points': [{'estimate': 98.0, 'run_sd': 45.254833995939045},
                                    {'estimate': 939.5, 'run_sd': 10.606601717798213},
                                    {'estimate': 1674.5, 'run_sd': 415.0716805565034},
                                    {'estimate': 1626.5, 'run_sd': 91.21677477306463}]},
                        {'strategy': 2,
                         'points': [{'estimate': 32.0, 'run_sd': 4.242640687119285},
                                    {'estimate': 69.0, 'run_sd': 2.8284271247461903},
                                    {'estimate': 111.0, 'run_sd': 4.242640687119285},
                                    {'estimate': 144.5, 'run_sd': 3.5355339059327378}]},
                        {'strategy': 3,
                         'points': [{'estimate': 56.5, 'run_sd': 2.1213203435596424},
                                    {'estimate': 107.0, 'run_sd': 16.97056274847714},
                                    {'estimate': 108.5, 'run_sd': 10.606601717798213},
                                    {'estimate': 128.0, 'run_sd': 25.45584412271571}]}]},
            {'metric': 'mean_success_rtt_ms',
             'title': 'Average successful RTT',
             'ylabel': 'Mean successful RTT (ms)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 180.00426319033605, 'run_sd': 1.8192010374688525},
                                    {'estimate': 184.45841150294262, 'run_sd': 1.2267046003615982},
                                    {'estimate': 196.82977874949358, 'run_sd': 0.8538826510061895},
                                    {'estimate': 219.11077863487503,
                                     'run_sd': 0.6226509280688309}]},
                        {'strategy': 1,
                         'points': [{'estimate': 197.4048879935942, 'run_sd': 1.7119764839650662},
                                    {'estimate': 222.80356390122262, 'run_sd': 0.918591133756543},
                                    {'estimate': 339.22874054798604, 'run_sd': 7.422108141562665},
                                    {'estimate': 592.6687904800693, 'run_sd': 0.5161411590839879}]},
                        {'strategy': 2,
                         'points': [{'estimate': 187.40726887965135, 'run_sd': 1.043426887194398},
                                    {'estimate': 423.0756051189195, 'run_sd': 10.033880033929238},
                                    {'estimate': 656.8858641576423, 'run_sd': 1.6438952184964426},
                                    {'estimate': 657.3753881051655, 'run_sd': 1.7396946275422995}]},
                        {'strategy': 3,
                         'points': [{'estimate': 187.62393862122752, 'run_sd': 2.249267413914343},
                                    {'estimate': 353.5198827994037, 'run_sd': 0.6472091483970368},
                                    {'estimate': 646.6600824420785, 'run_sd': 2.4300415707894665},
                                    {'estimate': 658.930923938897,
                                     'run_sd': 1.9443904037343305}]}]},
            {'metric': 'isr_percent',
             'title': 'Interest satisfaction ratio',
             'ylabel': 'Interest satisfaction ratio (%)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 67.95, 'run_sd': 11.71440234165714},
                                    {'estimate': 33.983333333333334, 'run_sd': 3.064129385141705},
                                    {'estimate': 24.683333333333334, 'run_sd': 1.2335084960698681},
                                    {'estimate': 14.504166666666666,
                                     'run_sd': 0.2533799299251802}]},
                        {'strategy': 1,
                         'points': [{'estimate': 96.26666666666667, 'run_sd': 0.42426406871192446},
                                    {'estimate': 68.84166666666667, 'run_sd': 0.6481812160876619},
                                    {'estimate': 44.68888888888888, 'run_sd': 0.3614101326064588},
                                    {'estimate': 26.445833333333333,
                                     'run_sd': 0.39480128616248916}]},
                        {'strategy': 2,
                         'points': [{'estimate': 99.43333333333334, 'run_sd': 0.188561808316412},
                                    {'estimate': 83.6, 'run_sd': 0.30641293851416324},
                                    {'estimate': 35.91111111111111, 'run_sd': 0.7071067811865476},
                                    {'estimate': 15.729166666666666,
                                     'run_sd': 0.18266925180652444}]},
                        {'strategy': 3,
                         'points': [{'estimate': 98.3, 'run_sd': 0.04714045207910049},
                                    {'estimate': 89.44166666666666, 'run_sd': 0.38890872965259915},
                                    {'estimate': 48.00555555555555, 'run_sd': 0.4164073266987445},
                                    {'estimate': 23.116666666666667,
                                     'run_sd': 1.7441967269268186}]}]},
            {'metric': 'network_mbit',
             'title': 'Network overhead',
             'ylabel': 'NDN L3 outgoing traffic (Mbit)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 818.93426, 'run_sd': 1.0832706182150325},
                                    {'estimate': 1614.9243040000001, 'run_sd': 1.8592722273061661},
                                    {'estimate': 2301.651368, 'run_sd': 4.472297655940112},
                                    {'estimate': 2645.124584, 'run_sd': 5.760318113715477}]},
                        {'strategy': 1,
                         'points': [{'estimate': 1078.033724, 'run_sd': 6.085898360045055},
                                    {'estimate': 2103.546708, 'run_sd': 1.9172493265093038},
                                    {'estimate': 2897.674292, 'run_sd': 40.30865600266463},
                                    {'estimate': 3666.0349239999996,
                                     'run_sd': 15.224082538051567}]},
                        {'strategy': 2,
                         'points': [{'estimate': 1073.119768, 'run_sd': 0.29989247118269524},
                                    {'estimate': 2075.43976, 'run_sd': 4.41432621359137},
                                    {'estimate': 3035.113416, 'run_sd': 7.12729694310527},
                                    {'estimate': 3987.888132, 'run_sd': 4.084899306372364}]},
                        {'strategy': 3,
                         'points': [{'estimate': 784.9164559999999, 'run_sd': 1.3100708756399237},
                                    {'estimate': 1546.6123360000001, 'run_sd': 1.2909846494021717},
                                    {'estimate': 2269.826376, 'run_sd': 0.4164576098476593},
                                    {'estimate': 2996.519356, 'run_sd': 13.801632595891427}]}]}]}


if __name__ == "__main__":
    main()
