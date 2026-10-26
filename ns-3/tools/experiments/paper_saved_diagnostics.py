"""Redraw diagnostic panels using only the completed figure set's saved tables.

These descriptive summaries retain the original equal-run definitions.  No raw
simulation records, model files or timing benchmarks are opened by this module.
"""
from collections import defaultdict
import csv
import importlib.util
import math
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_SPEC = importlib.util.spec_from_file_location(
    "saved_diagnostic_style", Path(__file__).with_name("paper_figure_style.py"))
style = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(style)

SCENES = ("circle", "grid", "spidermap")
SCENE_LABELS = dict(circle="Circle", grid="Grid", spidermap="Spider")
STRATEGIES = ("0", "1", "2", "3")


def _read(path, required):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not set(required).issubset(reader.fieldnames or ()):
            raise ValueError("Missing columns in saved table: " + str(path))
        rows = list(reader)
    if not rows:
        raise ValueError("Saved diagnostic table is empty: " + str(path))
    if any(row["scene"] not in SCENES for row in rows):
        raise ValueError("Unknown scene in saved diagnostic table")
    return rows


def _number(value, name, maximum=None):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(name + " must be finite and nonnegative")
    if maximum is not None and number > maximum:
        raise ValueError(name + " exceeds its allowed range")
    return number


def _run_point(rows, field, scale=1.):
    if len(rows) != 2 or len({r["seed_family"] for r in rows}) != 2:
        raise ValueError("Every diagnostic point requires exactly two distinct seeds")
    values = [_number(row[field], field) * scale for row in rows]
    return dict(estimate=statistics.mean(values), run_sd=statistics.stdev(values))


def _legend(fig, axis, columns=4):
    handles, labels = axis.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=columns)


def _decomposition(rows, output, save):
    indexed = {}
    for row in rows:
        key = row["scene"], row["strategy"], row["kind"], row["category"]
        if row["strategy"] not in STRATEGIES or row["kind"] not in ("extra", "control"):
            raise ValueError("Unknown strategy or decomposition kind")
        if key in indexed:
            raise ValueError("Duplicate decomposition category row")
        if row["repetitions"] != "2":
            raise ValueError("Saved decomposition requires two original runs")
        indexed[key] = _number(row["mean"], "Decomposition mean")
    figures = []
    for kind, identifier, ylabel, xlabel in (
            ("extra", "D04-extra-submission-decomposition",
             "Extra Data application submissions", "Submission category"),
            ("control", "D05-control-traffic-decomposition",
             "Control L3 outgoing traffic (Mbit)", "Control packet category")):
        categories = sorted({row["category"] for row in rows if row["kind"] == kind})
        if not categories:
            raise ValueError("Missing decomposition categories")
        fig, axes = plt.subplots(1, 3, figsize=(15.3, 4.8))
        for panel, (scene, ax) in enumerate(zip(SCENES, axes)):
            series = []
            for strategy in STRATEGIES:
                keys = [(scene, strategy, kind, category) for category in categories]
                if any(key not in indexed for key in keys):
                    raise ValueError("Missing decomposition category row")
                series.append(dict(strategy=strategy,
                    points=[dict(estimate=indexed[key], run_sd=None) for key in keys]))
            labels = [category.replace("_", "\n") for category in categories]
            style.grouped_bars(ax, labels, series)
            ax.set(title="({}) {}".format("abc"[panel], SCENE_LABELS[scene]),
                   xlabel=xlabel, ylim=(0, None))
            if kind == "control":
                ax.tick_params(axis="x", labelsize=8)
        axes[0].set_ylabel(ylabel)
        _legend(fig, axes[0])
        figures.append(save(fig, output, identifier, "baseline-decomposition.csv",
            "原基准条件的分项均值改为分组柱状图，四算法配色固定；保留全部类别及零值。"
            "各柱来自两次完整运行的等权均值。封存分项表未含逐种子方差，故不虚构误差线；"
            "总量的不确定性仍见主体图。额外Data为应用显式提交，控制量为NDN L3字节。",
            "Baseline component means from two complete runs, redrawn as grouped bars. "
            "All categories, including zero values, are retained. The frozen component "
            "table has no per-seed dispersion, so no error bars are invented; total "
            "uncertainty remains in the main figures. Extra Data counts application "
            "submissions; control traffic is measured at NDN L3."))
    return figures


def _mobility(rows, output, save):
    if any(row["scan"] not in ("speed", "vehicles") for row in rows):
        raise ValueError("Unknown saved mobility scan")
    groups = defaultdict(list)
    for row in rows:
        groups[row["scene"], row["scan"], _number(row["setting"], "Setting")].append(row)
    fig, axes = plt.subplots(2, 3, figsize=(13.7, 8.2))
    for row_index, scan, field, xlabel, ylabel in (
            (0, "speed", "actual_mean_speed_kmh", "Vehicle speed setting (km/h)",
             "Actual mean speed (km/h)"),
            (1, "vehicles", "handover_count", "Number of vehicles",
             "Observed handovers per run")):
        settings = sorted({key[2] for key in groups if key[1] == scan})
        if not settings:
            raise ValueError("Saved mobility scan is empty")
        for column, scene in enumerate(SCENES):
            ax = axes[row_index, column]
            points = [_run_point(groups[scene, scan, x], field) for x in settings]
            style.grouped_bars(ax, settings, [dict(
                label="Naive NDN mobility reference", color=style.COLORS[0],
                hatch=style.HATCHES[0], points=points)])
            if scan == "speed":
                ax.plot(range(len(settings)), settings, "--", color="#444444",
                        label="Speed setting", zorder=4)
            ax.set(title="({}) {}".format("abcdef"[row_index * 3 + column],
                                         SCENE_LABELS[scene]), xlabel=xlabel, ylim=(0, None))
        axes[row_index, 0].set_ylabel(ylabel)
    _legend(fig, axes[0, 0], columns=2)
    return save(fig, output, "D06-mobility-coverage", "mobility-coverage.csv",
        "复用原Naive NDN参考移动表。柱为两seed的等权运行均值，误差线为样本SD；"
        "设置速度参考线与分组位置对应。上排是实际时间加权车速，下排为每轮观察到的交接数。"
        "速度设置不等于车辆实际速度；不增减移动样本。",
        "Reused Naive NDN mobility reference. Bars are equal-run means over two "
        "seeds; error bars are sample SD, not confidence intervals. The speed-setting "
        "reference follows categorical group positions. Actual speeds and observed "
        "handover counts are unchanged; requested speed need not be achieved." )


def _actual_speed(rows, output, save):
    groups = defaultdict(list)
    for row in rows:
        if row["strategy"] not in STRATEGIES:
            raise ValueError("Unknown saved speed strategy")
        _number(row["stopped_vehicle_time_fraction"], "Stopped fraction", maximum=1)
        setting = _number(row["speed_setting_kmh"], "Speed setting")
        groups[row["scene"], row["strategy"], setting].append(row)
    settings = sorted({key[2] for key in groups})
    fig, axes = plt.subplots(2, 3, figsize=(14.7, 8.4))
    for column, scene in enumerate(SCENES):
        for row_index, field, scale, ylabel in (
                (0, "vehicle_time_weighted_speed_kmh", 1., "Actual mean speed (km/h)"),
                (1, "stopped_vehicle_time_fraction", 100., "Stopped vehicle time (%)")):
            ax = axes[row_index, column]
            series = [dict(strategy=strategy,
                points=[_run_point(groups[scene, strategy, x], field, scale)
                        for x in settings]) for strategy in STRATEGIES]
            style.grouped_bars(ax, settings, series)
            if row_index == 0:
                ax.plot(range(len(settings)), settings, "--", color="#444444",
                        label="Speed setting", zorder=4)
            ax.set(title="({}) {}".format("abcdef"[row_index * 3 + column],
                                         SCENE_LABELS[scene]),
                   xlabel="Vehicle speed setting (km/h)",
                   ylim=(0, 100 if row_index else None))
            if column == 0:
                ax.set_ylabel(ylabel)
    _legend(fig, axes[0, 0], columns=5)
    return save(fig, output, "S14-historical-actual-speed", "historical-actual-speed.csv",
        "原264轮的实际时间加权速度与停驶时间比例，四算法均保留。每条件2seed，柱为等权"
        "运行均值，误差线为样本SD，不是置信区间。道路、路口与跟驰可能使不同速度设置"
        "对应相近实际移动；本次仅改变排版，不重新采样或改变实验数据。",
        "Actual time-weighted speeds and stopped-time fractions from the original "
        "264 runs, retaining all four algorithms. Bars are equal-run means of two "
        "seeds; error bars show sample SD, not confidence intervals. Settings may "
        "saturate under road limits and interactions. No new mobility data are used.")


def render_diagnostics(source_dir, output, save_fn):
    """Return D04/D05/D06/S14 artifacts using a caller-supplied save hook."""
    source, output = Path(source_dir), Path(output)
    decomposition = _read(source / "baseline-decomposition.csv",
        ("scene", "strategy", "kind", "category", "mean", "repetitions"))
    mobility = _read(source / "mobility-coverage.csv",
        ("scene", "scan", "seed_family", "setting", "actual_mean_speed_kmh", "handover_count"))
    speeds = _read(source / "historical-actual-speed.csv",
        ("scene", "strategy", "seed_family", "speed_setting_kmh",
         "vehicle_time_weighted_speed_kmh", "stopped_vehicle_time_fraction"))
    figures = _decomposition(decomposition, output, save_fn)
    figures.append(_mobility(mobility, output, save_fn))
    figures.append(_actual_speed(speeds, output, save_fn))
    return figures
