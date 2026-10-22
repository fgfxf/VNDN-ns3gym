#!/usr/bin/env python3.8
"""Render the declared publication figures from a complete audited campaign.

PDF/SVG are the shareable artifacts; PNG previews and source tables are retained.
Validation-only fixtures receive a visible watermark in every output.
"""
import argparse
import csv
import html
import importlib.util
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


_SPEC = importlib.util.spec_from_file_location(
    "plot_campaign_aggregate", Path(__file__).with_name("aggregate_campaign.py"))
analysis_tools = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis_tools)
summary = analysis_tools.summary
SCENARIOS = analysis_tools.SCENARIOS
STRATEGIES = analysis_tools.STRATEGIES
ALGORITHMS = ("Naive NDN", "VTDF", "RTVTDF", "Proposed (TKAN-LSTM)")
COLORS = ("#666666", "#D55E00", "#0072B2", "#009E73")
MARKERS = ("o", "s", "^", "D")
LINES = ("-", "--", "-.", ":")
SCENE_LABELS = {"circle": "Circle", "grid": "Grid", "spidermap": "Spider"}
AXIS_LABELS = {
    "interest": "Number of generated Interest packets",
    "speed": "Vehicle speed setting (km/h)",
    "vehicles": "Number of vehicles",
    "vehicles_fixed_k": "Number of vehicles (fixed total requests)",
}
METRIC_LABELS = {
    "isr_percent": "Interest satisfaction rate (%)",
    "mean_success_rtt_ms": "Mean RTT of satisfied Interests (ms)",
    "network_mbit": "NDN L3 outgoing traffic (Mbit)",
    "control_mbit": "Custom control L3 outgoing traffic (Mbit)",
    "extra_data_app_attempts": "Extra Data application submissions",
}


def csv_records(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        yield from csv.DictReader(stream)


def load_analysis(directory):
    directory = Path(directory).resolve()
    result = summary.read_json(directory / "aggregate.json")
    if result.get("schema_version") != 1 or result.get("status") != "complete":
        raise ValueError("Analysis must be complete before figures can be published")
    if type(result.get("validation_only")) is not bool:
        raise ValueError("Analysis validation status is missing")
    for name, digest in result.get("artifacts", {}).items():
        path = (directory / name).resolve()
        if directory not in path.parents or summary.sha256_file(path) != digest:
            raise ValueError("Analysis artifact hash mismatch: " + name)
    required = {"plot-summary.csv", "paired-effects.csv", "run-metrics.csv", "run-details.json",
                "baseline-requests.csv", "baseline-associations.csv"}
    if not required.issubset(result.get("artifacts", {})):
        raise ValueError("Analysis lacks required source tables")
    for filename, digest in result.get("input_hashes", {}).items():
        if summary.sha256_file(filename) != digest:
            raise ValueError("Campaign/model/run provenance hash mismatch: " + filename)
    campaign = summary.read_json(result["campaign_path"])
    analysis_tools.validate_campaign(campaign)
    if summary.sha256_file(result["campaign_path"]) != result["campaign_sha256"]:
        raise ValueError("Campaign manifest hash mismatch")
    for key in ("validation_only", "source_sha256", "repetitions", "bootstrap",
                "baseline_condition_id", "conditions", "scans", "test_seeds_by_scene",
                "skip_training_figures", "external_models"):
        if result.get(key) != campaign.get(key):
            raise ValueError("Analysis disagrees with frozen campaign: " + key)
    if result.get("design_profile", "full") != campaign.get("design_profile", "full"):
        raise ValueError("Analysis design profile differs from frozen campaign")
    expected = analysis_tools.expected_figure_ids(
        campaign["scans"], include_training=analysis_tools.includes_training_figures(campaign))
    if result.get("figure_ids", expected) != expected:
        raise ValueError("Analysis figure declaration differs from frozen campaign")
    if result.get("design_profile") == analysis_tools.FIXED_MODEL_PROFILE:
        representatives = {scene: analysis_tools.seeds_for_scene(campaign, scene)[0]
                           for scene in SCENARIOS}
        if result.get("representative_seeds_by_scene") != representatives:
            raise ValueError("Analysis representative seeds differ from the frozen scene seeds")
    table = list(csv_records(directory / "plot-summary.csv"))
    points = result.get("points", [])
    if len(table) != len(points):
        raise ValueError("Point table and analysis JSON differ")
    for row, point in zip(table, points):
        if any(row.get(key) != ("" if value is None else str(value))
               for key, value in point.items()):
            raise ValueError("Point table and analysis JSON differ")
    return result


def time_bins(records, start_ns, end_ns, bin_seconds):
    bin_ns = summary.seconds_ns(bin_seconds)
    if bin_ns <= 0 or start_ns >= end_ns:
        raise ValueError("Invalid fixed time bins")
    count = (end_ns - start_ns + bin_ns - 1) // bin_ns
    output = [{"bin_start_s": (start_ns + index * bin_ns) / 1e9,
               "bin_end_s": min(start_ns + (index + 1) * bin_ns, end_ns) / 1e9,
               "successes": 0, "failures": 0, "sum_rtt_ms": 0.,
               "mean_success_rtt_ms": None} for index in range(count)]
    for row in records:
        send = int(row["send_ns"])
        if not start_ns <= send < end_ns:
            raise ValueError("Request outside declared time-bin cohort")
        target = output[(send - start_ns) // bin_ns]
        if row["terminal"] == "DATA":
            value = float(row["rtt_ms"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid successful RTT")
            target["successes"] += 1
            target["sum_rtt_ms"] += value
        elif row["terminal"] in summary.TERMINALS:
            target["failures"] += 1
        else:
            raise ValueError("Unrecognized request terminal")
    for row in output:
        if row["successes"]:
            row["mean_success_rtt_ms"] = row["sum_rtt_ms"] / row["successes"]
    return output


def _caption(result, english, chinese):
    label = " VALIDATION ONLY; synthetic small fixture." if result["validation_only"] else ""
    if result.get("design_profile") in (analysis_tools.QUICK_PROFILE, analysis_tools.FIXED_MODEL_PROFILE):
        count = analysis_tools.repetition_count(result)
        english = ("Exploratory draft: online comparison n={} paired runs per condition; "
                   "descriptive results, no significance claim. ".format(count)) + english
        chinese = "探索初稿：在线对比每条件n={}个配对运行，仅作描述，不作显著性结论。".format(count) + chinese
    if any(row["unique_physical_mobility"] == 1 and row["seed_families"] > 1
           for row in result.get("variation_audit", [])):
        english += (" Conditions with one observed mobility realization support only conditional "
                    "inference about that mobility; see the variation audit.")
        chinese += " 对仅观察到一种移动轨迹实现的条件，结论限于该移动条件，详见多样性审计。"
    return english + label, chinese + (" 仅验证夹具，不是论文实验结果。" if label else "")


def save_figure(fig, output, identifier, kind, result, caption_en, caption_zh, metadata=None):
    quick = result.get("design_profile") in (analysis_tools.QUICK_PROFILE, analysis_tools.FIXED_MODEL_PROFILE)
    if result["validation_only"]:
        fig.text(.5, .015, "VALIDATION ONLY — NOT EXPERIMENTAL RESULTS",
                 ha="center", va="bottom", color="#A00000", fontsize=8)
    if quick:
        fig.text(.5, .04 if result["validation_only"] else .015,
                 "EXPLORATORY DRAFT — online n={} paired runs/condition".format(analysis_tools.repetition_count(result)),
                 ha="center", va="bottom", color="#666666", fontsize=8)
    if any(getattr(axis, "name", "") == "3d" for axis in fig.axes):
        fig.subplots_adjust(left=.06, right=.90, bottom=.18, top=.90)
    else:
        bottom = .08 if quick and result["validation_only"] else .05 if quick or result["validation_only"] else 0
        fig.tight_layout(rect=(0, bottom, 1, .94))
    files, hashes = {}, {}
    for suffix in ("pdf", "svg", "png"):
        filename = identifier + "." + suffix
        fig.savefig(output / filename, dpi=160, bbox_inches="tight")
        files[suffix] = filename
        hashes[suffix] = summary.sha256_file(output / filename)
    plt.close(fig)
    english, chinese = _caption(result, caption_en, caption_zh)
    return dict(metadata or {}, id=identifier, kind=kind, files=files, sha256=hashes,
                caption_en=english, caption_zh=chinese)


def lookup_points(result):
    values = {}
    for point in result["points"]:
        key = point["scene"], point["condition_id"], point["strategy"], point["metric"]
        if key in values:
            raise ValueError("Duplicate plotted point")
        values[key] = point
    return values


def _draw_points(ax, xvalues, points, strategy, descriptive=False):
    estimates = [point["estimate"] if point["estimate"] is not None else np.nan
                 for point in points]
    index = int(strategy)
    ax.plot(xvalues, estimates, label=ALGORITHMS[index], color=COLORS[index],
            marker=MARKERS[index], linestyle=LINES[index], markersize=4, linewidth=1.2)
    for x, point in zip(xvalues, points):
        if descriptive:
            values = [v for v in point.get("run_values", []) if v is not None]
            ax.scatter([x] * len(values), values, s=13, alpha=.35,
                       color=COLORS[index], marker=MARKERS[index], zorder=2)
            if point["estimate"] is not None and point.get("run_sd") is not None:
                lo, hi = point["estimate"] - point["run_sd"], point["estimate"] + point["run_sd"]
                ax.vlines(x, lo, hi, color=COLORS[index], linewidth=.8)
                ax.plot([x, x], [lo, hi], "_", color=COLORS[index], markersize=5)
        elif point["estimate"] is not None and point["ci_low"] is not None:
            # Percentile intervals can exclude the point estimate. Plot the
            # endpoints directly, rather than assuming nonnegative yerr.
            ax.vlines(x, point["ci_low"], point["ci_high"], color=COLORS[index], linewidth=.8)
            ax.plot([x], [point["ci_low"]], marker="_", color=COLORS[index], markersize=5)
            ax.plot([x], [point["ci_high"]], marker="_", color=COLORS[index], markersize=5)


def scan_figures(result, output, points):
    figures = []
    conditions = {item["id"]: item for item in result["conditions"]}
    compact = result.get("design_profile") in (analysis_tools.COMPACT_PROFILE, analysis_tools.QUICK_PROFILE, analysis_tools.FIXED_MODEL_PROFILE)
    identifier = 1
    for scan in analysis_tools.SCANS:
        if scan not in result["scans"]:
            identifier += len(analysis_tools.MAIN_METRICS)
            continue
        ids = result["scans"][scan]
        variable = "requests" if scan == "interest" else "speed_kmh" if scan == "speed" else "vehicles"
        x = [conditions[condition][variable] for condition in ids]
        for metric in analysis_tools.MAIN_METRICS:
            fig, axes = plt.subplots(1, 3, figsize=(12.8, 3.6), sharey=True)
            for panel, (scene, ax) in enumerate(zip(SCENARIOS, axes)):
                for strategy in STRATEGIES:
                    records = [points[scene, condition, strategy, metric] for condition in ids]
                    _draw_points(ax, x, records, strategy, descriptive=compact)
                ax.set_title("({}) {}".format("abc"[panel], SCENE_LABELS[scene]))
                ax.set_xlabel(AXIS_LABELS[scan])
                ax.set_xticks(x)
                ax.grid(axis="y", alpha=.2)
                if metric == "isr_percent":
                    ax.set_ylim(0, 100)
                else:
                    ax.set_ylim(bottom=0)
            axes[0].set_ylabel(METRIC_LABELS[metric])
            handles, labels = axes[0].get_legend_handles_labels()
            fig.legend(handles, labels, ncol=4, loc="upper center", frameon=False, fontsize=8)
            figure_id = "F{:02d}-{}-{}".format(identifier, scan, metric)
            english = (
                "{} versus {}. Each point uses {} complete independent paired simulation blocks; "
                "bars are pointwise 95% whole-block bootstrap intervals. Success RTT is weighted "
                "by satisfied requests; unavailable intervals are omitted and recorded in the table."
                .format(METRIC_LABELS[metric], AXIS_LABELS[scan], analysis_tools.repetition_count(result)))
            chinese = (
                "{}随{}变化；每点{}个完整配对运行块，区间为整块重采样的点态95%区间。"
                "成功RTT按成功请求数加权；不可估计区间在数表注明。".format(
                    METRIC_LABELS[metric], AXIS_LABELS[scan], analysis_tools.repetition_count(result)))
            if compact:
                english = (
                    "{} versus {}. {} paired independent runs per condition; faint symbols show "
                    "individual run estimates and bars show one sample standard deviation, not a "
                    "confidence interval. RTT centers pool success counts across runs; its SD describes "
                    "defined per-run success means and omits zero-success runs only from the SD, never "
                    "from the performance denominator. The point estimate need not equal the mean of "
                    "the displayed per-run RTTs. Small-sample paired bootstrap intervals remain in "
                    "the tables; neither bootstrap draws nor packets are independent runs."
                    .format(METRIC_LABELS[metric], AXIS_LABELS[scan], analysis_tools.repetition_count(result)))
                chinese = (
                    "{}随{}变化，每条件{}个独立配对运行；淡点为各次运行，误差线为一倍样本标准差，"
                    "不是置信区间。RTT中心仍按成功数加权，SD仅描述有成功请求的各run均值，"
                    "因此中心不必等于淡点均值；零成功run仍留在性能分母。小样本配对bootstrap区间"
                    "保留于数表，重采样次数和包数不等于独立重复数。".format(
                        METRIC_LABELS[metric], AXIS_LABELS[scan], analysis_tools.repetition_count(result)))
            figures.append(save_figure(
                fig, output, figure_id, "scan", result,
                english, chinese,
                {"scan": scan, "metric": metric, "source_table": "plot-summary.csv",
                 "conditions": ids}))
            identifier += 1
    return figures


def baseline_data(directory, scene, representative_seed):
    successful = {strategy: [] for strategy in STRATEGIES}
    handover_successful = {strategy: [] for strategy in STRATEGIES}
    representative = {strategy: [] for strategy in STRATEGIES}
    counts = {strategy: {"generated": 0, "satisfied": 0, "handover_generated": 0,
                        "handover_satisfied": 0} for strategy in STRATEGIES}
    for row in csv_records(directory / "baseline-requests.csv"):
        if row["scene"] != scene:
            continue
        strategy = row["strategy"]
        counts[strategy]["generated"] += 1
        handover = row["common_handover"] == "1"
        counts[strategy]["handover_generated"] += int(handover)
        if row["terminal"] == "DATA":
            rtt = float(row["rtt_ms"])
            successful[strategy].append(rtt)
            counts[strategy]["satisfied"] += 1
            if handover:
                handover_successful[strategy].append(rtt)
                counts[strategy]["handover_satisfied"] += 1
        if int(row["seed_family"]) == representative_seed:
            representative[strategy].append(row)
    return successful, handover_successful, representative, counts


def _windows(directory, baseline):
    result = {}
    for row in csv_records(directory / "run-metrics.csv"):
        if row["condition_id"] == baseline:
            value = int(row["measurement_start_ns"]), int(row["measurement_end_ns"])
            if row["scene"] in result and result[row["scene"]] != value:
                raise ValueError("Baseline windows differ between comparison blocks")
            result[row["scene"]] = value
    return result


def legacy_figures(result, directory, output):
    figures, diagnostics, quantiles, bin_table = [], [], [], []
    windows = _windows(directory, result["baseline_condition_id"])
    for scene_index, scene in enumerate(SCENARIOS):
        representative_seed = result.get("representative_seeds_by_scene", {}).get(
            scene, result["representative_seed"])
        successful, handover, representative, counts = baseline_data(
            directory, scene, representative_seed)
        fig = plt.figure(figsize=(8.2, 4.6))
        ax = fig.add_subplot(111, projection="3d")
        for strategy in STRATEGIES:
            rows = time_bins(representative[strategy], *windows[scene], result["time_bin_seconds"])
            bin_table.extend(dict(row, scene=scene, strategy=strategy,
                                  seed_family=representative_seed) for row in rows)
            x = [(row["bin_start_s"] + row["bin_end_s"]) / 2 for row in rows]
            z = [row["mean_success_rtt_ms"] if row["mean_success_rtt_ms"] is not None else np.nan
                 for row in rows]
            ax.plot(x, [int(strategy)] * len(x), z, color=COLORS[int(strategy)],
                    linestyle=LINES[int(strategy)], marker=MARKERS[int(strategy)],
                    markersize=3, label=ALGORITHMS[int(strategy)])
        ax.set(xlabel="Interest generation time (s)", ylabel="Scheme",
               title=SCENE_LABELS[scene])
        # Some Matplotlib 3D projections omit the z-label from tight bounds.
        # Use a figure label with an explicit in-canvas location instead.
        fig.text(.92, .55, "Mean successful RTT (ms)", rotation=90,
                 ha="center", va="center")
        ax.set_yticks(range(4), ("Naive", "VTDF", "RTVTDF", "Proposed"), fontsize=7)
        figures.append(save_figure(
            fig, output, "F{:02d}-{}-rtt-3d".format(21 + scene_index, scene), "legacy_3d", result,
            "{} baseline, prespecified seed {}. Fixed {} s send-time bins contain only successful "
            "RTT; empty-success bins remain empty. Per-bin successes and failures are in "
            "time-bin-rtt.csv. This one-run mechanism illustration is not an independent-repeat "
            "confidence estimate.".format(SCENE_LABELS[scene], representative_seed,
                                          result["time_bin_seconds"]),
            "{}基准条件的事前指定种子{}；按发送时间固定{}秒分箱，仅平均成功RTT，"
            "无成功区间留空。各箱成功与失败数见配套表；单次示意不代表重复实验区间。".format(
                SCENE_LABELS[scene], representative_seed, result["time_bin_seconds"]),
            {"scene": scene, "source_table": "time-bin-rtt.csv"}))

        fig, axes = plt.subplots(1, 2, figsize=(9.5, 4))
        box_values = [successful[strategy] for strategy in STRATEGIES[1:]]
        for ax in axes:
            for position, (values, color) in enumerate(zip(box_values, COLORS[1:]), 1):
                if values:
                    artists = ax.boxplot([values], positions=[position], widths=.5,
                                         patch_artist=True, showfliers=True,
                                         flierprops={"markersize": 2, "alpha": .35})
                    artists["boxes"][0].set_facecolor(color)
                else:
                    ax.text(position, .5, "NA\n(no success)", ha="center",
                            transform=ax.get_xaxis_transform(), fontsize=8)
            ax.set_xticks([1, 2, 3], ("VTDF", "RTVTDF", "Proposed"))
            ax.set_ylim(bottom=0)
            ax.set_ylabel("Successful RTT (ms)")
            ax.grid(axis="y", alpha=.2)
        axes[0].set_title("Full successful distribution")
        axes[1].set_title("Body zoom; full tail shown at left")
        nonempty = [np.asarray(values) for values in box_values if values]
        if nonempty:
            all_values = np.concatenate(nonempty)
            upper = float(np.percentile(all_values, 95))
            axes[1].set_ylim(0, max(upper * 1.08, np.finfo(float).eps))
        figures.append(save_figure(
            fig, output, "F{:02d}-{}-rtt-box".format(24 + scene_index, scene), "legacy_box", result,
            "{} baseline: all successful RTTs from {} seeds, three recovery schemes. Left: full "
            "range; right: body zoom to 1.08 times the pooled 95th percentile. No RTT observations "
            "are removed. Packet-level pooled boxes are descriptive distributions, not independent "
            "replication or confidence intervals.".format(SCENE_LABELS[scene], analysis_tools.repetition_count(result)),
            "{}基准条件{}个种子的全部成功RTT；左图完整尾部，右图放大至合并P95的1.08倍。"
            "不删除样本；包级合并箱线仅描述分布，不能把包当作独立重复。".format(
                SCENE_LABELS[scene], analysis_tools.repetition_count(result)),
            {"scene": scene, "source_table": "baseline-requests.csv"}))

        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
        for strategy in STRATEGIES:
            for ax, values in zip(axes, (successful[strategy], handover[strategy])):
                if values:
                    ordered = np.sort(values)
                    # All values define the ECDF. Deterministic plotting of all
                    # distinct values avoids excessive duplicate vector points.
                    x, repetitions = np.unique(ordered, return_counts=True)
                    ax.step(x, np.cumsum(repetitions) / len(ordered), where="post",
                            color=COLORS[int(strategy)], linestyle=LINES[int(strategy)],
                            label=ALGORITHMS[int(strategy)], linewidth=1.1)
            for subset, values in (("all_success", successful[strategy]),
                                   ("common_handover_success", handover[strategy])):
                quantiles.append(dict(
                    scene=scene, strategy=strategy, subset=subset, count=len(values),
                    p50_ms=float(np.percentile(values, 50)) if values else None,
                    p95_ms=float(np.percentile(values, 95)) if values else None,
                    p99_ms=float(np.percentile(values, 99)) if values else None,
                    **counts[strategy]))
        for ax, title in zip(axes, ("All successful requests", "Common handover cohort, successful")):
            ax.set(xlabel="Successful RTT (ms)", ylabel="Empirical cumulative probability",
                   ylim=(0, 1), title=title)
            ax.grid(alpha=.2)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False, fontsize=8)
        diagnostics.append(save_figure(
            fig, output, "D{:02d}-{}-rtt-ecdf".format(scene_index + 1, scene), "diagnostic_ecdf", result,
            "{} baseline successful-RTT ECDF, with a shared handover cohort defined by NoForward "
            "association events in the closed request lifetime. Failed requests remain in the "
            "counts table. ECDFs pool correlated packets descriptively.".format(SCENE_LABELS[scene]),
            "{}基准成功RTT的ECDF；共同交接集合由NoForward参考关联事件和请求寿命闭区间定义。"
            "失败请求留在分母表；包级合并CDF仅描述分布。".format(SCENE_LABELS[scene]),
            {"scene": scene, "source_table": "baseline-rtt-quantiles.csv"}))
    analysis_tools.write_csv(output / "time-bin-rtt.csv", bin_table)
    analysis_tools.write_csv(output / "baseline-rtt-quantiles.csv", quantiles)
    return figures, diagnostics


def traffic_figure(result, output, points):
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.6), sharey=True)
    baseline = result["baseline_condition_id"]
    quick = result.get("design_profile") in (analysis_tools.QUICK_PROFILE, analysis_tools.FIXED_MODEL_PROFILE)
    for panel, (scene, ax) in enumerate(zip(SCENARIOS, axes)):
        for strategy in STRATEGIES:
            point = points[scene, baseline, strategy, "network_mbit"]
            x = int(strategy)
            ax.bar(x, point["estimate"], color=COLORS[x], width=.65)
            if quick:
                values = [value for value in point.get("run_values", []) if value is not None]
                ax.scatter([x] * len(values), values, color="black", alpha=.5, s=18, zorder=3)
                if point.get("run_sd") is not None:
                    lower, upper = point["estimate"] - point["run_sd"], point["estimate"] + point["run_sd"]
                    ax.vlines(x, lower, upper, color="black", linewidth=1)
                    ax.plot([x, x], [lower, upper], "_", color="black")
            elif point["ci_low"] is not None:
                ax.vlines(x, point["ci_low"], point["ci_high"], color="black", linewidth=1)
                ax.plot([x, x], [point["ci_low"], point["ci_high"]], "_", color="black")
        ax.set_xticks(range(4), ("Naive", "VTDF", "RTVTDF", "Proposed"), rotation=15, fontsize=8)
        ax.set_title("({}) {}".format("abc"[panel], SCENE_LABELS[scene]))
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=.2)
    axes[0].set_ylabel(METRIC_LABELS["network_mbit"])
    english = (
        "Baseline total outgoing NDN L3 traffic across network faces, including measurement and "
        "drain intervals. Means and pointwise 95% complete-block bootstrap intervals; native "
        "LP/MAC overhead and retries are outside this measurement layer.")
    chinese = ("三场景基准条件的全网NDN L3出站总量，包含测量与排空窗口。给出均值及整块重采样"
               "点态95%区间，不包括LP/MAC头和MAC重试。")
    if quick:
        english = (
            "Baseline total outgoing NDN L3 traffic across network faces, including measurement and "
            "drain intervals. Bars show equal-run means, dots show individual runs and error bars show "
            "one sample standard deviation, not a confidence interval. Native LP/MAC overhead and "
            "retries are outside this measurement layer.")
        chinese = ("三场景基准条件的全网NDN L3出站总量，包含测量与排空窗口。柱为各run等权均值，"
                   "点为各次运行，误差线为一倍样本标准差，不是置信区间；不包括LP/MAC头和MAC重试。")
    return save_figure(
        fig, output, "F27-baseline-total-traffic", "traffic", result, english, chinese,
        {"source_table": "plot-summary.csv", "condition_id": baseline})


def confusion_figures(result, output):
    figures, count_rows = [], []
    for index, scene in enumerate(SCENARIOS):
        evaluation = result["model_evaluations"][scene]
        matrix = np.asarray(evaluation["confusion_matrix"], dtype=np.int64)
        support = matrix.sum(axis=1)
        normalized = matrix / support[:, None]
        size = len(support)
        fig, ax = plt.subplots(figsize=(5.6, 4.6))
        im = ax.imshow(normalized, cmap="Blues", vmin=0, vmax=1)
        fig.colorbar(im, ax=ax, label="Fraction of true class")
        for row in range(size):
            for column in range(size):
                value = float(normalized[row, column])
                ax.text(column, row, "{:.1%}\n({})".format(value, matrix[row, column]),
                        ha="center", va="center", fontsize=8,
                        color="white" if value > .5 else "black")
                count_rows.append({"scene": scene, "true_rsu": row, "predicted_rsu": column,
                                   "count": int(matrix[row, column]), "support": int(support[row]),
                                   "row_fraction": value, "model_sha256": evaluation["model_sha256"]})
        ax.set_xticks(range(size), range(size))
        ax.set_yticks(range(size), ["{} (n={})".format(i, n) for i, n in enumerate(support)])
        ax.set(xlabel="Predicted RSU", ylabel="True RSU and support",
               title=SCENE_LABELS[scene] + ": independent evaluation")
        figures.append(save_figure(
            fig, output, "F{:02d}-{}-confusion".format(28 + index, scene), "confusion", result,
            "{} selected frozen model on the independent model-evaluation split. Rows normalize "
            "by true-class support; integer counts and support are retained. This classification "
            "result is distinct from Interest satisfaction and online path coverage."
            .format(SCENE_LABELS[scene]),
            "{}冻结模型在独立模型评估集上的混淆矩阵；按真实类行归一化并显示原始计数与支持数。"
            "分类性能不等同于在线请求满足率或回程覆盖率。".format(SCENE_LABELS[scene]),
            {"scene": scene, "model_sha256": evaluation["model_sha256"],
             "source_table": "model-confusion-counts.csv"}))
    analysis_tools.write_csv(output / "model-confusion-counts.csv", count_rows)
    return figures


def supplementary_diagnostics(result, directory, output):
    figures, decomposition_rows, mobility_rows = [], [], []
    details = summary.read_json(directory / "run-details.json")["runs"]
    baseline = result["baseline_condition_id"]
    for identifier, kind, categories, field, scale, ylabel in (
            ("D04-extra-submission-decomposition", "extra", sorted(summary.REASONS),
             "extra_attempts_by_reason", 1, "Mean extra Data application submissions"),
            ("D05-control-traffic-decomposition", "control", sorted(summary.CONTROL_CLASSES),
             "l3_bytes_by_class", 8 / 1e6, "Mean custom control L3 traffic (Mbit)")):
        fig, axes = plt.subplots(1, 3, figsize=(12.4, 4), sharey=True)
        palette = plt.get_cmap("tab20")
        for scene, ax in zip(SCENARIOS, axes):
            bottoms = np.zeros(4)
            for category_index, category in enumerate(categories):
                means = []
                for strategy in STRATEGIES:
                    selected = [row for row in details if row["scene"] == scene and
                                row["condition_id"] == baseline and row["strategy"] == strategy]
                    values = [row.get(field, {}).get(category, 0) * scale for row in selected]
                    if len(values) != analysis_tools.repetition_count(result):
                        raise ValueError("Missing baseline decomposition repetitions")
                    mean = float(np.mean(values))
                    means.append(mean)
                    decomposition_rows.append({
                        "scene": scene, "strategy": strategy, "kind": kind,
                        "category": category, "mean": mean, "repetitions": len(values),
                        "unit": "application submissions" if kind == "extra" else "Mbit"})
                ax.bar(range(4), means, bottom=bottoms, label=category,
                       color=palette(category_index * 2), width=.7)
                bottoms += means
            ax.set(title=SCENE_LABELS[scene], ylim=(0, max(float(max(bottoms)) * 1.15, 1e-9)))
            ax.set_xticks(range(4), ("Naive", "VTDF", "RTVTDF", "Proposed"),
                          rotation=15, fontsize=8)
        axes[0].set_ylabel(ylabel)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, ncol=3, loc="upper center", frameon=False, fontsize=7)
        figures.append(save_figure(
            fig, output, identifier, "decomposition", result,
            "Baseline {} components, arithmetic means over complete simulation blocks. "
            "These stacked descriptive means retain the application/L3 measurement boundary; "
            "aggregate uncertainty is shown in the main figures.".format(kind),
            "基准条件{}分项，按完整运行块求均值；堆叠图为描述性分解，保留应用提交/L3边界，"
            "总量不确定性见主图。".format(kind),
            {"source_table": "baseline-decomposition.csv"}))
    analysis_tools.write_csv(output / "baseline-decomposition.csv", decomposition_rows)

    conditions = {item["id"]: item for item in result["conditions"]}
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.8))
    for index, scene in enumerate(SCENARIOS):
        for row_index, scan, setting, measured in (
                (0, "speed", "speed_kmh", "vehicle_time_weighted_speed_kmh"),
                (1, "vehicles", "vehicles", "handover_count")):
            x, y = [], []
            for condition_id in result["scans"][scan]:
                selected = [row for row in details if row["scene"] == scene and
                            row["condition_id"] == condition_id and row["strategy"] == "0"]
                if len(selected) != analysis_tools.repetition_count(result):
                    raise ValueError("Missing reference mobility repetitions")
                x.append(conditions[condition_id][setting])
                y.append(float(np.mean([row[measured] for row in selected])))
                for row in selected:
                    mobility_rows.append({
                        "scene": scene, "scan": scan, "condition_id": condition_id,
                        "seed_family": row["seed_family"], "setting": x[-1],
                        "actual_mean_speed_kmh": row["vehicle_time_weighted_speed_kmh"],
                        "speed_p05_mps": row["speed_time_weighted_p05_mps"],
                        "speed_p50_mps": row["speed_time_weighted_p50_mps"],
                        "speed_p95_mps": row["speed_time_weighted_p95_mps"],
                        "stopped_fraction": row["stopped_vehicle_time_fraction"],
                        "handover_count": row["handover_count"]})
            ax = axes[row_index, index]
            ax.plot(x, y, "o-", color=COLORS[0], label="NoForward mobility reference")
            if row_index == 0:
                ax.plot(x, x, "--", color="#AAAAAA", label="Setting = measured")
            ax.set_title(SCENE_LABELS[scene])
            ax.set_xlabel(AXIS_LABELS[scan])
            ax.set_ylim(bottom=0)
            ax.grid(alpha=.2)
    axes[0, 0].set_ylabel("Mean measured speed (km/h)")
    axes[1, 0].set_ylabel("Mean observed handovers per run")
    figures.append(save_figure(
        fig, output, "D06-mobility-coverage", "mobility", result,
        "Reference mobility coverage: equal-run means of time-weighted actual speed and observed "
        "handovers. Requested speed is a setting, not the achieved velocity. Complete per-seed "
        "speed quantiles, stopping fractions and handover counts are retained. Paired physical "
        "mobility samples were checked across schemes.",
        "NoForward参考移动覆盖：实际时间加权车速及交接数的运行均值；设置速度不等于实际速度。"
        "附全部种子的速度分位数、停车比例及交接数；四算法物理移动样本已作配对核验。",
        {"source_table": "mobility-coverage.csv"}))
    analysis_tools.write_csv(output / "mobility-coverage.csv", mobility_rows)

    if not analysis_tools.includes_training_figures(result):
        return figures

    for index, scene in enumerate(SCENARIOS):
        history = result["model_evaluations"][scene].get("training_history")
        if not history:
            if result["validation_only"]:
                continue
            raise ValueError("Frozen selected-model training history is required")
        path = Path(history["path"])
        if summary.sha256_file(path) != history["sha256"]:
            raise ValueError("Training history hash mismatch")
        rows = list(csv_records(path))
        if not rows:
            raise ValueError("Training history is empty")
        epochs, train, validation, f1 = [], [], [], []
        for row in rows:
            epoch = summary.integer(row["epoch"], "history epoch", 1)
            numbers = [float(row[key]) for key in (
                "train_loss", "validation_loss", "validation_macro_f1")]
            if any(not math.isfinite(value) for value in numbers) or (
                    any(value < 0 for value in numbers) or numbers[2] > 1 or
                    (epochs and epoch <= epochs[-1])):
                raise ValueError("Invalid learning curve values or epoch ordering")
            epochs.append(epoch)
            train.append(numbers[0])
            validation.append(numbers[1])
            f1.append(numbers[2])
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
        axes[0].plot(epochs, train, label="Train optimization loss")
        axes[0].plot(epochs, validation, label="Validation cross-entropy")
        axes[0].set(xlabel="Epoch", ylabel="Loss", ylim=(0, None))
        axes[0].legend(frameon=False, fontsize=8)
        axes[1].plot(epochs, f1, color=COLORS[3])
        axes[1].set(xlabel="Epoch", ylabel="Validation macro-F1", ylim=(0, 1))
        fig.suptitle(SCENE_LABELS[scene] + ": selected initialization")
        figures.append(save_figure(
            fig, output, "D{:02d}-{}-learning".format(7 + index, scene), "learning", result,
            "{} selected initialization: training optimization loss, validation cross-entropy "
            "and validation macro-F1. Training loss may use frozen class weights, whereas validation "
            "metrics use original frequencies; no independent-evaluation curve is used for selection."
            .format(SCENE_LABELS[scene]),
            "{}所选初始化的训练损失、验证交叉熵和macro-F1；训练损失可能带固定类别权重，"
            "验证按原始频次统计。独立评估集不用于选模。".format(SCENE_LABELS[scene]),
            {"source_path": str(path), "source_sha256": history["sha256"]}))
    return figures


def write_draft_index(output, result, figures):
    """Local preview of the actual rendered artifacts, with their full captions."""
    title = "Exploratory draft / 探索初稿：{}张实验图".format(len(figures))
    pieces = [
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>' + title + '</title>',
        '<style>body{max-width:1200px;margin:2rem auto;padding:0 1rem;font-family:sans-serif;'
        'line-height:1.5;color:#222}article{border-top:1px solid #ddd;padding:1rem 0}'
        'img{max-width:100%;height:auto}a{margin-right:1rem}.note{color:#666}</style>',
        '<h1>' + title + '</h1>',
        '<p>在线对比每条件 n={} 个完整配对运行。图中淡点代表各次运行，主图与总流量图的误差线'
        '为样本标准差，不是置信区间；本初稿不作显著性结论。</p>'.format(analysis_tools.repetition_count(result)),
        '<p class="note">下列图片来自本次已完成的汇总。点击PNG预览可放大；PDF与SVG适合论文排版。'
        '各图保留英文与中文图注，完整来源见figure-index.json。</p>',
    ]
    if result["validation_only"]:
        pieces.append('<p><strong>VALIDATION ONLY：合成验证夹具，不是论文实验结果。</strong></p>')
    for item in figures:
        identifier = html.escape(item["id"], quote=True)
        files = {key: html.escape(value, quote=True) for key, value in item["files"].items()}
        pieces.extend([
            '<article data-figure-id="{}"><h2>{}</h2>'.format(identifier, identifier),
            '<a href="{png}"><img src="{png}" loading="lazy" alt="{name}"></a>'.format(
                name=identifier, **files),
            '<p><a href="{pdf}">PDF</a><a href="{svg}">SVG</a><a href="{png}">PNG</a></p>'.format(**files),
            '<p>' + html.escape(item["caption_zh"]) + '</p>',
            '<p class="note">' + html.escape(item["caption_en"]) + '</p></article>',
        ])
    pieces.append('</html>')
    path = output / "index.html"
    path.write_text("\n".join(pieces), encoding="utf-8")
    return {"path": path.name, "sha256": summary.sha256_file(path)}


def plot_campaign(analysis_directory, output_directory):
    directory = Path(analysis_directory).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise ValueError("Output directory already exists; refusing to overwrite figures")
    result = load_analysis(directory)
    points = lookup_points(result)
    output.mkdir(parents=True, exist_ok=False)
    analysis_tools.write_json(output / "status.json", {"status": "rendering",
                                                     "validation_only": result["validation_only"]})
    with plt.rc_context({"font.size": 9, "svg.fonttype": "none", "pdf.fonttype": 42,
                         "axes.spines.top": False, "axes.spines.right": False}):
        figures = scan_figures(result, output, points)
        legacy, diagnostics = legacy_figures(result, directory, output)
        figures.extend(legacy)
        figures.append(traffic_figure(result, output, points))
        if analysis_tools.includes_training_figures(result):
            figures.extend(confusion_figures(result, output))
        diagnostics.extend(supplementary_diagnostics(result, directory, output))
    figures.sort(key=lambda item: item["id"])
    expected = analysis_tools.expected_figure_ids(
        result["scans"], include_training=analysis_tools.includes_training_figures(result))
    if len(figures) != len(expected) or {item["id"] for item in figures} != set(expected):
        raise ValueError("Rendered figures do not match the declared primary/supplementary figure IDs")
    # Revalidate frozen analysis artifacts after rendering, before marking complete.
    load_analysis(directory)
    report = {
        "schema_version": 1, "status": "complete", "validation_only": result["validation_only"],
        "campaign_id": result["campaign_id"], "campaign_sha256": result["campaign_sha256"],
        "design_profile": result.get("design_profile", "full"), "figure_ids": expected,
        "analysis_sha256": summary.sha256_file(directory / "aggregate.json"),
        "plot_code_sha256": summary.sha256_file(Path(__file__)),
        "matplotlib_version": matplotlib.__version__, "numpy_version": np.__version__,
        "figures": figures, "diagnostics": diagnostics,
        "plot_configuration": {
            "colors": COLORS, "markers": MARKERS, "lines": LINES,
            "algorithms": ALGORITHMS, "scenario_order": SCENARIOS,
            "representative_seed": result["representative_seed"],
            "time_bin_seconds": result["time_bin_seconds"],
            "box_zoom": "0 to 1.08 times pooled successful RTT P95; full companion panel",
            "uncertainty": result["bootstrap"],
        },
        "source_tables": {path.name: summary.sha256_file(path)
                          for path in output.glob("*.csv")},
    }
    if result.get("design_profile") in (analysis_tools.QUICK_PROFILE, analysis_tools.FIXED_MODEL_PROFILE):
        browse_figures = (figures + diagnostics if result.get("design_profile") ==
                          analysis_tools.FIXED_MODEL_PROFILE else figures)
        report["browse_index"] = write_draft_index(output, result, browse_figures)
        report["plot_configuration"]["displayed_uncertainty"] = (
            "individual paired runs and one sample standard deviation; exploratory n=2, "
            "not a confidence interval or significance claim")
    if "representative_seeds_by_scene" in result:
        report["plot_configuration"]["representative_seeds_by_scene"] = result["representative_seeds_by_scene"]
    analysis_tools.write_json(output / "figure-index.json", report)
    analysis_tools.write_json(output / "status.json", {"status": "complete",
                                                     "validation_only": result["validation_only"]})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis_directory", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = plot_campaign(args.analysis_directory, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, "plot_campaign: {}\n".format(error))
    print(json.dumps({"status": report["status"], "figures": len(report["figures"]),
                      "diagnostics": len(report["diagnostics"]),
                      "validation_only": report["validation_only"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
