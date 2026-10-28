#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10_消费者数量_方阵：单场景四指标图，只使用本文件内嵌数值。

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
FIGURE_ID = '10_消费者数量_方阵'
SCENE = 'grid'
SCENE_LABEL = 'Grid'
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
DATA = {'scene': 'grid',
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
                         'points': [{'estimate': 278.0, 'run_sd': 16.97056274847714},
                                    {'estimate': 572.5, 'run_sd': 137.88582233137677},
                                    {'estimate': 888.0, 'run_sd': 46.66904755831214},
                                    {'estimate': 1582.0, 'run_sd': 59.39696961966999}]},
                        {'strategy': 2,
                         'points': [{'estimate': 227.0, 'run_sd': 28.284271247461902},
                                    {'estimate': 378.5, 'run_sd': 64.34671708797582},
                                    {'estimate': 462.0, 'run_sd': 7.0710678118654755},
                                    {'estimate': 645.0, 'run_sd': 80.61017305526642}]},
                        {'strategy': 3,
                         'points': [{'estimate': 121.0, 'run_sd': 28.284271247461902},
                                    {'estimate': 286.5, 'run_sd': 36.062445840513924},
                                    {'estimate': 389.5, 'run_sd': 19.091883092036785},
                                    {'estimate': 551.5, 'run_sd': 13.435028842544403}]}]},
            {'metric': 'mean_success_rtt_ms',
             'title': 'Average successful RTT',
             'ylabel': 'Mean successful RTT (ms)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 299.1575225003493, 'run_sd': 0.06346314233930694},
                                    {'estimate': 300.23827930879105, 'run_sd': 0.16960697218770898},
                                    {'estimate': 301.50666705275734, 'run_sd': 0.2720796616112899},
                                    {'estimate': 303.70468314787325,
                                     'run_sd': 0.9740303474086045}]},
                        {'strategy': 1,
                         'points': [{'estimate': 378.9862796984556, 'run_sd': 7.828611226754645},
                                    {'estimate': 373.893470490491, 'run_sd': 5.236908709543978},
                                    {'estimate': 366.56834548542724, 'run_sd': 1.5207794814314304},
                                    {'estimate': 371.6530694944386, 'run_sd': 3.312581991954376}]},
                        {'strategy': 2,
                         'points': [{'estimate': 355.6421344255742, 'run_sd': 1.1529895531148955},
                                    {'estimate': 346.97406868482705, 'run_sd': 4.90679455512209},
                                    {'estimate': 347.83071778963034, 'run_sd': 1.6193382986539244},
                                    {'estimate': 370.82984786707146,
                                     'run_sd': 1.1553757995950502}]},
                        {'strategy': 3,
                         'points': [{'estimate': 302.73485390858076, 'run_sd': 2.2010672099488615},
                                    {'estimate': 312.33557095327274, 'run_sd': 8.183542974660808},
                                    {'estimate': 329.42024597891015, 'run_sd': 9.318681974907374},
                                    {'estimate': 366.45877627127607,
                                     'run_sd': 3.5297354685227837}]}]},
            {'metric': 'isr_percent',
             'title': 'Interest satisfaction ratio',
             'ylabel': 'Interest satisfaction ratio (%)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 71.58333333333334, 'run_sd': 7.51890210661696},
                                    {'estimate': 64.17500000000001, 'run_sd': 1.7324116139070433},
                                    {'estimate': 58.12777777777778, 'run_sd': 0.9820927516479855},
                                    {'estimate': 52.212500000000006,
                                     'run_sd': 2.4454109516034785}]},
                        {'strategy': 1,
                         'points': [{'estimate': 86.33333333333334, 'run_sd': 0.565685424949236},
                                    {'estimate': 85.88333333333333, 'run_sd': 2.309882151876055},
                                    {'estimate': 83.48888888888888, 'run_sd': 0.9899494936611605},
                                    {'estimate': 79.41666666666666,
                                     'run_sd': 0.011785113019775122}]},
                        {'strategy': 2,
                         'points': [{'estimate': 92.15, 'run_sd': 0.6363961030678867},
                                    {'estimate': 91.775, 'run_sd': 0.7424621202458729},
                                    {'estimate': 89.57777777777778, 'run_sd': 1.5870618866631467},
                                    {'estimate': 87.82916666666667, 'run_sd': 0.5480077554195784}]},
                        {'strategy': 3,
                         'points': [{'estimate': 92.06666666666666, 'run_sd': 0.5185449728701356},
                                    {'estimate': 89.88333333333333, 'run_sd': 1.6499158227686075},
                                    {'estimate': 87.98333333333333, 'run_sd': 1.1706545599644025},
                                    {'estimate': 85.875, 'run_sd': 0.7660323462854332}]}]},
            {'metric': 'network_mbit',
             'title': 'Network overhead',
             'ylabel': 'NDN L3 outgoing traffic (Mbit)',
             'series': [{'strategy': 0,
                         'points': [{'estimate': 772.4595400000001, 'run_sd': 0.28444360222718684},
                                    {'estimate': 1528.942432, 'run_sd': 6.605078786209231},
                                    {'estimate': 2276.7673999999997, 'run_sd': 2.518725668295202},
                                    {'estimate': 3042.474596, 'run_sd': 7.312440125837328}]},
                        {'strategy': 1,
                         'points': [{'estimate': 1030.415768, 'run_sd': 2.878478971145701},
                                    {'estimate': 2053.3075360000003, 'run_sd': 12.167655902779646},
                                    {'estimate': 3075.6671960000003, 'run_sd': 18.229252416968983},
                                    {'estimate': 4150.963484, 'run_sd': 16.63580708455506}]},
                        {'strategy': 2,
                         'points': [{'estimate': 1037.285216, 'run_sd': 1.7608316496566372},
                                    {'estimate': 2050.0813200000002, 'run_sd': 18.00766777916206},
                                    {'estimate': 3040.452984, 'run_sd': 0.988263751094958},
                                    {'estimate': 4050.6047719999997, 'run_sd': 8.61686546093596}]},
                        {'strategy': 3,
                         'points': [{'estimate': 756.5939960000001, 'run_sd': 5.791176253646606},
                                    {'estimate': 1505.6086639999999, 'run_sd': 13.690356615949407},
                                    {'estimate': 2239.988608, 'run_sd': 3.248493807604917},
                                    {'estimate': 2989.8468599999997,
                                     'run_sd': 8.259985840044022}]}]}]}


if __name__ == "__main__":
    main()
