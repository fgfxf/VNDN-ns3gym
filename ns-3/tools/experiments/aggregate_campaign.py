#!/usr/bin/env python3.8
"""Audit frozen four-strategy campaigns and aggregate whole paired seed blocks.

Traffic is NDN L3 outgoing Interest/Data, extra copies are application
submissions.  Success RTT is weighted by satisfied requests; all unsuccessful
runs remain in the bootstrap.  See RETRAIN_AND_FIGURES_PLAN_20261021.md.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


_SPEC = importlib.util.spec_from_file_location(
    "campaign_run_summary", Path(__file__).with_name("summarize.py"))
summary = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summary)
SCENARIOS = ("circle", "grid", "spidermap")
STRATEGIES = ("0", "1", "2", "3")
METRICS = ("isr_percent", "mean_success_rtt_ms", "network_mbit", "control_mbit",
           "extra_data_app_attempts", "network_bytes_per_interest",
           "control_bytes_per_interest", "extra_attempts_per_interest")
MAIN_METRICS = METRICS[:5]
SCANS = ("interest", "speed", "vehicles", "vehicles_fixed_k")
COMPACT_PROFILE = "compact-exploratory-v1"
QUICK_PROFILE = "quick-draft-v1"
FIXED_MODEL_PROFILE = "quick-fixed-model-v1"
FIXED_MODEL_SEEDS = {"circle": [23001, 23002], "grid": [23009, 23010],
                     "spidermap": [23017, 23018]}
COUNT_FIELDS = ("generated", "satisfied", "sum_success_rtt_ns", "network_l3_bytes",
                "control_l3_bytes", "extra_data_app_attempts")


def expected_figure_ids(scans, include_training=True):
    """Stable numbering: the deferred fixed-K figures retain their reserved slots."""
    if set(scans) not in (set(SCANS), set(SCANS[:3])):
        raise ValueError("figures require the three primary scans and optional fixed-K scan")
    result = ["F{:02d}-{}-{}".format(scan_index * 5 + metric_index + 1, scan, metric)
              for scan_index, scan in enumerate(SCANS) if scan in scans
              for metric_index, metric in enumerate(MAIN_METRICS)]
    result.extend("F{:02d}-{}-rtt-3d".format(21 + i, scene) for i, scene in enumerate(SCENARIOS))
    result.extend("F{:02d}-{}-rtt-box".format(24 + i, scene) for i, scene in enumerate(SCENARIOS))
    result.append("F27-baseline-total-traffic")
    if include_training:
        result.extend("F{:02d}-{}-confusion".format(28 + i, scene) for i, scene in enumerate(SCENARIOS))
    return result


def seeds_for_scene(campaign, scene):
    if campaign.get("design_profile") == FIXED_MODEL_PROFILE:
        return campaign["test_seeds_by_scene"][scene]
    return campaign["repetitions"]


def repetition_count(campaign, scene=None):
    """The union of scene seeds is provenance, not the per-condition sample size."""
    if scene is not None:
        return len(seeds_for_scene(campaign, scene))
    counts = {len(seeds_for_scene(campaign, name)) for name in SCENARIOS}
    if len(counts) != 1:
        raise ValueError("Different scene repetition counts require explicit scene labels")
    return counts.pop()


def includes_training_figures(campaign):
    return campaign.get("design_profile") != FIXED_MODEL_PROFILE


def _positive_integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError("{} must be an integer >= {}".format(name, minimum))
    return int(value)


def _metric_estimates(blocks, indices):
    result = {}
    for strategy in STRATEGIES:
        arrays = {field: np.asarray([b[strategy][field] for b in blocks], dtype=np.float64)
                  for field in COUNT_FIELDS}
        generated, success = arrays["generated"], arrays["satisfied"]
        values = {
            "isr_percent": 100 * success / generated,
            "network_mbit": arrays["network_l3_bytes"] * 8 / 1e6,
            "control_mbit": arrays["control_l3_bytes"] * 8 / 1e6,
            "extra_data_app_attempts": arrays["extra_data_app_attempts"],
            "network_bytes_per_interest": arrays["network_l3_bytes"] / generated,
            "control_bytes_per_interest": arrays["control_l3_bytes"] / generated,
            "extra_attempts_per_interest": arrays["extra_data_app_attempts"] / generated,
        }
        output = {key: value[indices].mean(axis=1) for key, value in values.items()}
        numerator = arrays["sum_success_rtt_ns"][indices].sum(axis=1) / 1e6
        denominator = success[indices].sum(axis=1)
        output["mean_success_rtt_ms"] = np.divide(
            numerator, denominator, out=np.full_like(numerator, np.nan),
            where=denominator != 0)
        result[strategy] = output
    return result


def _interval(estimate, replicates):
    invalid = int((~np.isfinite(replicates)).sum())
    interval = (None, None) if invalid else tuple(
        float(value) for value in np.percentile(replicates, [2.5, 97.5]))
    return {"estimate": float(estimate) if math.isfinite(float(estimate)) else None,
            "ci_low": interval[0], "ci_high": interval[1],
            "resamples": len(replicates), "invalid_resamples": invalid,
            "invalid_fraction": invalid / len(replicates),
            "ci_status": "unavailable_zero_success" if invalid else "estimated"}


def paired_statistics(blocks, resamples=10000, seed=0):
    """Resample complete paired blocks, with no packet-level independence claim."""
    if not blocks:
        raise ValueError("At least one complete paired block is required")
    _positive_integer(resamples, "resamples", 1)
    _positive_integer(seed, "analysis seed")
    for block in blocks:
        if set(block) != set(STRATEGIES):
            raise ValueError("Each comparison block requires all four strategies")
        for value in block.values():
            for field in COUNT_FIELDS:
                _positive_integer(value.get(field), field, 1 if field == "generated" else 0)
            if value["satisfied"] > value["generated"] or (
                    not value["satisfied"] and value["sum_success_rtt_ns"] != 0):
                raise ValueError("Invalid success count/RTT sum")
            if value["control_l3_bytes"] > value["network_l3_bytes"]:
                raise ValueError("Control traffic is not a subset of network traffic")
    draws = np.random.RandomState(seed).randint(0, len(blocks), (resamples, len(blocks)))
    point = _metric_estimates(blocks, np.arange(len(blocks))[None, :])
    bootstrap = _metric_estimates(blocks, draws)
    per_run = _metric_estimates(blocks, np.arange(len(blocks))[:, None])
    result = {"repetitions": len(blocks), "resamples": resamples, "seed": seed,
              "method": "paired complete-block percentile bootstrap, pointwise 95%",
              "metrics": {}, "effects": {}}
    for metric in METRICS:
        result["metrics"][metric] = {
            strategy: _interval(point[strategy][metric][0], bootstrap[strategy][metric])
            for strategy in STRATEGIES}
        for strategy in STRATEGIES:
            values = per_run[strategy][metric]
            finite = values[np.isfinite(values)]
            result["metrics"][metric][strategy].update(
                run_values=[float(value) if math.isfinite(float(value)) else None for value in values],
                run_defined=len(finite),
                run_sd=float(np.std(finite, ddof=1)) if len(finite) > 1 else None)
        result["effects"][metric] = {
            "3-" + reference: _interval(
                point["3"][metric][0] - point[reference][metric][0],
                bootstrap["3"][metric] - bootstrap[reference][metric])
            for reference in STRATEGIES[:-1]}
    return result


def handover_events(rows):
    """Keep losses/restores separate; A -> -1 -> B is a handover at recovery."""
    state, events = {}, []
    ordered = sorted(enumerate(rows), key=lambda item: (int(item[1]["time_ns"]), item[0]))
    for _, row in ordered:
        if row["event"] != "ASSOCIATION":
            continue
        vehicle = row["vehicle_id"]
        time = summary.integer(row["time_ns"], "association time")
        previous = summary.integer(row["previous_rsu_id"], "previous rsu", -1)
        current = summary.integer(row["rsu_id"], "current rsu", -1)
        known, lost = state.get(vehicle, (-1, None))
        if current == previous:
            continue
        event = {"vehicle_id": vehicle, "time_ns": time, "from_rsu": previous,
                 "to_rsu": current, "loss_duration_ns": None, "is_handover": False}
        if previous >= 0 and current >= 0:
            event.update(kind="direct", is_handover=True)
            known, lost = current, None
        elif current < 0:
            event["kind"] = "loss"
            known, lost = previous if previous >= 0 else known, time
        else:
            event["from_rsu"] = known
            event["loss_duration_ns"] = time - lost if lost is not None else None
            event["kind"] = ("cross_reconnect" if known >= 0 and known != current
                             else "restore" if known == current else "initial")
            event["is_handover"] = event["kind"] == "cross_reconnect"
            known, lost = current, None
        events.append(event)
        state[vehicle] = known, lost
    return events


def request_handover(vehicle, send, deadline, events):
    matches = [event["time_ns"] for event in events if event["is_handover"] and
               event["vehicle_id"] == vehicle and send <= event["time_ns"] <= deadline]
    return bool(matches), any(time in (send, deadline) for time in matches)


def audit_factor_invariants(campaign, signatures):
    records = []
    for scene in SCENARIOS:
        for seed in seeds_for_scene(campaign, scene):
            baseline = signatures[scene, campaign["baseline_condition_id"], seed]
            for scan, fields in (
                    ("interest", ("mobility_sha256", "route_family_sha256", "network_sha256")),
                    ("speed", ("request_sha256", "route_family_sha256", "network_sha256"))):
                for condition in campaign["scans"][scan]:
                    candidate = signatures[scene, condition, seed]
                    if any(candidate[field] != baseline[field] for field in fields):
                        raise ValueError("{} scan changes fixed request/mobility/route inputs: {} {} {}"
                                         .format(scan, scene, condition, seed))
                records.append({"scene": scene, "seed_family": seed, "scan": scan,
                                "checked_fields": list(fields), "passed": True})
    return records


def aggregate_campaign(manifest_path, output_directory):
    """Validate every declared block before publishing a complete analysis directory."""
    manifest_path = Path(manifest_path).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise ValueError("Output directory already exists; historical analyses are immutable")
    campaign = summary.read_json(manifest_path)
    manifest_hash = summary.sha256_file(manifest_path)
    conditions, blocks = validate_campaign(campaign)
    base = manifest_path.parent
    models, evaluations, history_hashes = {}, {}, {}
    include_training = includes_training_figures(campaign)
    if not include_training and (not campaign["validation_only"] or campaign.get("external_models")):
        spec = importlib.util.spec_from_file_location(
            "aggregate_fixed_models", Path(__file__).with_name("fixed_models.py"))
        fixed_models = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixed_models)
        history_hashes.update(fixed_models.check_external_models(campaign))
    for scene in SCENARIOS:
        models[scene] = checked_file(campaign["models"][scene], base, "model")
        if not include_training:
            continue
        evaluation_file = checked_file(campaign["model_evaluations"][scene], base, "evaluation")
        evaluations[scene] = validate_evaluation(
            summary.read_json(evaluation_file), scene, campaign["models"][scene]["sha256"])
        history = evaluations[scene].get("training_history")
        if history:
            history_path = checked_file(history, evaluation_file.parent, "training history")
            history_hashes[str(history_path)] = history["sha256"]
            evaluations[scene]["training_history"] = dict(history, path=str(history_path))
        elif not campaign["validation_only"]:
            raise ValueError("Formal evaluation must identify its selected-model training history")

    grouped, run_records, provenance = defaultdict(list), [], []
    baseline_blocks = []
    used_seed_tuples = defaultdict(set)
    observed_windows, variation = {}, defaultdict(lambda: {"request": set(), "mobility": set()})
    block_signatures = {}
    resolved_run_paths = set()
    all_source_hashes = dict(history_hashes)
    for block in blocks.values():
        for ref in block["runs"].values():
            resolved = resolve_path(base, ref["path"])
            if resolved in resolved_run_paths:
                raise ValueError("duplicate resolved run path")
            resolved_run_paths.add(resolved)
    for scene in SCENARIOS:
        for condition_id in conditions:
            for repetition in seeds_for_scene(campaign, scene):
                block = blocks[scene, condition_id, repetition]
                paired, signatures, paths = {}, [], {}
                for strategy in STRATEGIES:
                    ref = block["runs"][strategy]
                    path = resolve_path(base, ref["path"])
                    path_manifest = path / "manifest.json"
                    if summary.sha256_file(path_manifest) != ref["manifest_sha256"]:
                        raise ValueError("Run manifest hash mismatch: " + str(path))
                    run_manifest = summary.read_json(path_manifest)
                    for filename, digest in run_manifest.get("artifact_hashes", {}).items():
                        all_source_hashes[str((path / filename).resolve())] = digest
                    for filename, digest in run_manifest.get("input_hashes", {}).items():
                        all_source_hashes[str(resolve_path(path, filename))] = digest
                    metrics = summary.summarize_run(path)
                    config = summary.read_json(path / "experiment.json")
                    signature = audit_run(
                        path, run_manifest, config, metrics, campaign, block,
                        conditions[condition_id], strategy, base)
                    signatures.append(signature)
                    paths[strategy] = path
                    paired[strategy] = metrics
                    run_records.append(dict(
                        metrics, scene=scene, condition_id=condition_id,
                        seed_family=repetition, strategy=strategy, run_path=str(path),
                        manifest_sha256=ref["manifest_sha256"]))
                    provenance.append({"path": str(path_manifest),
                                       "sha256": ref["manifest_sha256"]})
                if any(signature != signatures[0] for signature in signatures[1:]):
                    raise ValueError("Paired inputs, seeds, requests or mobility differ: " +
                                     block["block_id"])
                window = signatures[0]["window"]
                if scene in observed_windows and observed_windows[scene] != window:
                    raise ValueError("Measurement/drain window changes within a scenario")
                observed_windows[scene] = window
                seed_key = signatures[0]["seed_tuple"]
                group_key = scene, condition_id
                if seed_key in used_seed_tuples[group_key]:
                    raise ValueError("Repeated seed tuple is not an independent repetition")
                used_seed_tuples[group_key].add(seed_key)
                variation[group_key]["request"].add(signatures[0]["request_sha256"])
                variation[group_key]["mobility"].add(signatures[0]["mobility_sha256"])
                block_signatures[scene, condition_id, repetition] = signatures[0]
                grouped[group_key].append(paired)
                if condition_id == campaign["baseline_condition_id"]:
                    baseline_blocks.append((scene, repetition, paths))

    factor_audit = audit_factor_invariants(campaign, block_signatures)
    points, effects = [], []
    for (scene, condition_id), pairs in grouped.items():
        result = paired_statistics(pairs, **campaign["bootstrap"])
        for metric, by_strategy in result["metrics"].items():
            for strategy, values in by_strategy.items():
                points.append(dict(values, scene=scene, condition_id=condition_id,
                                   strategy=strategy, metric=metric,
                                   repetitions=len(pairs)))
        for metric, by_comparison in result["effects"].items():
            for comparison, values in by_comparison.items():
                effects.append(dict(values, scene=scene, condition_id=condition_id,
                                    comparison=comparison, metric=metric,
                                    repetitions=len(pairs)))
    # Only complete, audited inputs reach this point. Publication remains marked
    # incomplete if writing or the final stability check fails.
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "status.json", {"status": "writing", "validation_only":
                                      campaign["validation_only"]})
    write_csv(output / "plot-summary.csv", points)
    write_csv(output / "paired-effects.csv", effects)
    write_csv(output / "run-metrics.csv", run_records, scalar_only=True)
    write_json(output / "run-details.json", {"schema_version": 1, "runs": run_records})
    write_baseline(output, baseline_blocks)
    checked_inputs = dict(all_source_hashes)
    for entry in provenance:
        checked_inputs[entry["path"]] = entry["sha256"]
    for scene in SCENARIOS:
        for collection in (("models", "model_evaluations") if include_training else ("models",)):
            entry = campaign[collection][scene]
            checked_inputs[str(resolve_path(base, entry["path"]))] = entry["sha256"]
    checked_inputs[str(manifest_path)] = manifest_hash
    for path, digest in checked_inputs.items():
        if summary.sha256_file(path) != digest:
            raise ValueError("Input changed during aggregation: " + path)
    result = {
        "schema_version": 1, "status": "complete", "campaign_id": campaign["campaign_id"],
        "validation_only": campaign["validation_only"],
        "campaign_path": str(manifest_path), "campaign_sha256": manifest_hash,
        "source_sha256": campaign["source_sha256"], "measurement_scope": summary.MEASUREMENT_SCOPE,
        "repetitions": campaign["repetitions"], "representative_seed": campaign["repetitions"][0],
        "bootstrap": campaign["bootstrap"], "conditions": campaign["conditions"],
        "baseline_condition_id": campaign["baseline_condition_id"], "scans": campaign["scans"],
        "time_bin_seconds": campaign.get("time_bin_seconds", 5),
        "design_profile": campaign.get("design_profile", "full"),
        "figure_ids": expected_figure_ids(campaign["scans"], include_training=include_training),
        "models": campaign["models"], "model_evaluations": evaluations,
        "run_count": len(run_records), "block_count": len(blocks),
        "factor_audit": factor_audit,
        "variation_audit": [
            {"scene": scene, "condition_id": condition,
             "seed_families": repetition_count(campaign, scene),
             "unique_request_cohorts": len(value["request"]),
             "unique_physical_mobility": len(value["mobility"]),
             "mobility_scope": ("one observed trajectory realization; inference is conditional"
                                if len(value["mobility"]) == 1 else
                                "multiple observed physical mobility realizations")}
            for (scene, condition), value in variation.items()],
        "points": points, "effects": effects, "input_hashes": checked_inputs,
        "analysis_code": {
            str(Path(__file__).resolve()): summary.sha256_file(Path(__file__)),
            str(Path(__file__).with_name("summarize.py").resolve()):
                summary.sha256_file(Path(__file__).with_name("summarize.py"))},
        "artifacts": {path.name: summary.sha256_file(path) for path in output.iterdir()
                      if path.name != "status.json"},
        "notes": [
            "Confidence intervals are pointwise, paired complete-block percentile intervals.",
            "RTT is conditional on timely success; zero-success blocks remain in all resamples.",
            "Any undefined RTT replicate makes its interval unavailable, without deleting draws.",
            "Baseline handover cohorts use strategy 0 association events for all four strategies.",
            "Boxplots pool successful packets descriptively; packets are not independent runs.",
        ],
    }
    if not include_training:
        result.update(test_seeds_by_scene=campaign["test_seeds_by_scene"],
                      representative_seeds_by_scene={scene: seeds_for_scene(campaign, scene)[0]
                                                     for scene in SCENARIOS},
                      external_models=campaign["external_models"], skip_training_figures=True)
        result["notes"].append(
            "Exploratory fixed-model comparison reusing training seed families; two paired runs "
            "per scene and condition, not an independent generalization evaluation. Model weights "
            "remain frozen; training/evaluation figures are deliberately absent.")
    if campaign.get("design_profile") == QUICK_PROFILE:
        result["notes"].append(
            "Exploratory draft with two independent paired runs per condition; show individual "
            "runs and sample SD descriptively, without significance claims. Bootstrap draws and "
            "packets do not increase the independent replication count.")
    write_json(output / "aggregate.json", result)
    write_json(output / "status.json", {"status": "complete", "validation_only":
                                      campaign["validation_only"]})
    return result


def resolve_path(base, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Expected nonempty path")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def checked_file(record, base, label):
    path = resolve_path(base, record["path"])
    if not path.is_file() or summary.sha256_file(path) != record.get("sha256"):
        raise ValueError(label + " hash mismatch: " + str(path))
    return path


def _sha(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid SHA256 for " + label)
    return value


def validate_campaign(campaign):
    if campaign.get("schema_version") != 1 or type(campaign.get("validation_only")) is not bool:
        raise ValueError("Campaign schema/validation_only must be explicit")
    if not isinstance(campaign.get("campaign_id"), str) or not campaign["campaign_id"]:
        raise ValueError("Campaign ID is required")
    _sha(campaign.get("source_sha256"), "source")
    repetitions = campaign.get("repetitions", [])
    if not repetitions or len(set(repetitions)) != len(repetitions):
        raise ValueError("Missing or duplicate repetition seed families")
    for seed in repetitions:
        _positive_integer(seed, "seed_family", 1)
    conditions = {}
    for condition in campaign.get("conditions", []):
        name = condition.get("id")
        if not isinstance(name, str) or not name or name in conditions:
            raise ValueError("Missing or duplicate condition ID")
        for field in ("vehicles", "requests"):
            _positive_integer(condition.get(field), "condition " + field, 1)
        speed = condition.get("speed_kmh")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or (
                not math.isfinite(speed) or speed <= 0):
            raise ValueError("Invalid condition speed")
        conditions[name] = condition
    baseline = campaign.get("baseline_condition_id")
    if not conditions or baseline not in conditions:
        raise ValueError("A canonical baseline condition is required")
    profile = campaign.get("design_profile", "full")
    if profile not in ("full", COMPACT_PROFILE, QUICK_PROFILE, FIXED_MODEL_PROFILE):
        raise ValueError("Unknown campaign design profile")
    required_scans = SCANS[:3] if profile in (COMPACT_PROFILE, QUICK_PROFILE, FIXED_MODEL_PROFILE) else SCANS
    if set(campaign.get("scans", {})) != set(required_scans):
        raise ValueError("All scans declared by the design profile must be present")
    expected_figures = expected_figure_ids(campaign["scans"], includes_training_figures(campaign))
    if campaign.get("figure_ids", expected_figures) != expected_figures:
        raise ValueError("Figure declaration differs from the frozen scan design")
    for scan, names in campaign["scans"].items():
        if not names or len(names) != len(set(names)) or baseline not in names or (
                not set(names).issubset(conditions)):
            raise ValueError("Invalid or duplicate conditions in scan " + scan)
        base = conditions[baseline]
        axis = "requests" if scan == "interest" else "speed_kmh" if scan == "speed" else "vehicles"
        xvalues = [conditions[name][axis] for name in names]
        if xvalues != sorted(xvalues) or len(set(xvalues)) != len(xvalues):
            raise ValueError("Scan coordinates must be unique and increasing")
        for name in names:
            condition = conditions[name]
            fixed = (("vehicles", "speed_kmh") if scan == "interest" else
                     ("vehicles", "requests") if scan == "speed" else
                     ("speed_kmh", "requests") if scan == "vehicles_fixed_k" else ("speed_kmh",))
            if any(condition[key] != base[key] for key in fixed):
                raise ValueError("Scan changes more than its declared factor: " + scan)
            if scan == "vehicles" and (
                    condition["requests"] * base["vehicles"] !=
                    base["requests"] * condition["vehicles"]):
                raise ValueError("Vehicle scan must preserve per-vehicle request intensity")
    if set().union(*(set(v) for v in campaign["scans"].values())) != set(conditions):
        raise ValueError("Unused conditions cannot silently enter the matrix")
    bootstrap = campaign.get("bootstrap", {})
    _positive_integer(bootstrap.get("resamples"), "bootstrap resamples", 1)
    _positive_integer(bootstrap.get("seed"), "bootstrap seed")
    bin_seconds = campaign.get("time_bin_seconds", 5)
    if isinstance(bin_seconds, bool) or not isinstance(bin_seconds, (int, float)) or (
            not math.isfinite(bin_seconds) or bin_seconds <= 0):
        raise ValueError("Time-bin seconds must be positive and finite")
    if profile == FIXED_MODEL_PROFILE:
        if campaign.get("test_seeds_by_scene") != FIXED_MODEL_SEEDS or repetitions != [
                seed for scene in SCENARIOS for seed in FIXED_MODEL_SEEDS[scene]]:
            raise ValueError("Fixed-model campaign requires the approved scene-specific training seeds")
        if campaign.get("skip_training_figures") is not True or campaign.get("model_evaluations") != {}:
            raise ValueError("Fixed-model campaign skips training figures and new model evaluations")
        if not isinstance(campaign.get("external_models"), dict):
            raise ValueError("Fixed-model campaign requires external model provenance")
    if not campaign["validation_only"]:
        if profile == FIXED_MODEL_PROFILE:
            parameters = {(c["vehicles"], c["speed_kmh"], c["requests"]) for c in conditions.values()}
            expected_parameters = {(10, 30, k) for k in (1500, 3000, 6000, 9000, 12000)}
            expected_parameters.update((10, v, 6000) for v in (15, 30, 50, 60))
            expected_parameters.update((n, 30, n * 600) for n in (5, 10, 15, 20))
            if (len(conditions) != 11 or parameters != expected_parameters or
                    bootstrap["resamples"] != 10000 or
                    [len(campaign["scans"][s]) for s in SCANS[:3]] != [5, 4, 4]):
                raise ValueError("Fixed-model design requires eleven approved conditions, "
                                 "5/4/4 scan points and 10000 resamples")
        elif profile == QUICK_PROFILE:
            parameters = {(c["vehicles"], c["speed_kmh"], c["requests"]) for c in conditions.values()}
            expected_parameters = {(10, 30, 6000), (10, 30, 1500), (10, 30, 12000),
                                   (10, 10, 6000), (10, 50, 6000), (5, 30, 3000),
                                   (15, 30, 9000), (20, 30, 12000)}
            if (repetitions != [52001, 52002] or len(conditions) != 8 or
                    parameters != expected_parameters or bootstrap["resamples"] != 10000 or
                    [len(campaign["scans"][s]) for s in SCANS[:3]] != [3, 3, 4]):
                raise ValueError("Quick draft requires seeds 52001/52002, eight approved conditions, "
                                 "3/3/4 scan points and 10000 resamples")
        elif profile == COMPACT_PROFILE:
            parameters = {(c["vehicles"], c["speed_kmh"], c["requests"]) for c in conditions.values()}
            expected_parameters = {(10, 30, 15000), (10, 30, 3750), (10, 30, 30000),
                                   (10, 10, 15000), (10, 50, 15000), (5, 30, 7500),
                                   (15, 30, 22500), (20, 30, 30000)}
            if (len(repetitions) != 5 or len(conditions) != 8 or
                    parameters != expected_parameters or bootstrap["resamples"] != 10000 or
                    [len(campaign["scans"][s]) for s in SCANS[:3]] != [3, 3, 4]):
                raise ValueError("Formal compact design requires five seeds, eight approved conditions, "
                                 "3/3/4 scan points and 10000 resamples")
        elif (len(repetitions) != 20 or len(conditions) != 17 or bootstrap["resamples"] != 10000 or
                any(len(value) != 5 for value in campaign["scans"].values())):
            raise ValueError("Formal campaign requires 20 repetitions, 17 conditions and 10000 resamples")
    for field in (("models", "model_evaluations") if includes_training_figures(campaign) else ("models",)):
        if set(campaign.get(field, {})) != set(SCENARIOS):
            raise ValueError(field + " must cover all three scenarios")
    blocks, block_ids, run_paths = {}, set(), set()
    for block in campaign.get("blocks", []):
        key = block.get("scene"), block.get("condition_id"), block.get("seed_family")
        if key in blocks or block.get("block_id") in block_ids:
            raise ValueError("duplicate comparison block")
        if not isinstance(block.get("block_id"), str) or not block["block_id"]:
            raise ValueError("Missing block ID")
        if set(block.get("runs", {})) != set(STRATEGIES):
            raise ValueError("Each block requires four strategies")
        for ref in block["runs"].values():
            _sha(ref.get("manifest_sha256"), "run manifest")
            path = ref.get("path")
            if not isinstance(path, str) or path in run_paths:
                raise ValueError("duplicate or missing run path")
            run_paths.add(path)
        blocks[key] = block
        block_ids.add(block["block_id"])
    expected = {(scene, condition, seed) for scene in SCENARIOS for condition in conditions
                for seed in seeds_for_scene(campaign, scene)}
    if set(blocks) != expected:
        raise ValueError("Campaign matrix is not complete: missing or unexpected blocks")
    return conditions, blocks


def validate_evaluation(evaluation, scene, model_sha):
    classes = 2 if scene == "circle" else 7
    if evaluation.get("scenario") != scene or evaluation.get("split") != "evaluation" or (
            evaluation.get("model_sha256") != model_sha):
        raise ValueError("Independent evaluation split/scenario/model mismatch")
    _sha(evaluation.get("dataset_manifest_sha256"), "evaluation dataset")
    if evaluation.get("label_values") != list(range(classes)):
        raise ValueError("Evaluation labels do not cover the scenario")
    matrix = evaluation.get("confusion_matrix")
    if not isinstance(matrix, list) or len(matrix) != classes:
        raise ValueError("Evaluation confusion matrix dimensions are invalid")
    for row in matrix:
        if not isinstance(row, list) or len(row) != classes:
            raise ValueError("Evaluation confusion matrix dimensions are invalid")
        for count in row:
            _positive_integer(count, "confusion count")
        if sum(row) == 0:
            raise ValueError("Independent evaluation lacks class support")
    return evaluation


def rows_digest(path, event, fields):
    selected = [tuple(row[field] for field in fields)
                for row in summary.rows(path) if row["event"] == event]
    digest = hashlib.sha256()
    for row in sorted(selected):
        digest.update(json.dumps(row, separators=(",", ":"), ensure_ascii=True).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def audit_run(path, manifest, config, metrics, campaign, block, condition, strategy, base):
    if manifest.get("source", {}).get("sha256") != campaign["source_sha256"]:
        raise ValueError("Run source version differs from frozen campaign")
    if manifest.get("measurement_scope") != summary.MEASUREMENT_SCOPE:
        raise ValueError("Run measurement scope differs from the L3/application contract")
    if any((manifest.get("run_id") != config.get("run_id"),
            manifest.get("scenario") != block["scene"],
            manifest.get("block_id") != block["block_id"],
            manifest.get("strategy") != int(strategy),
            config.get("scenario") != block["scene"],
            config.get("strategy") != int(strategy),
            config.get("block_id") != block["block_id"])):
        raise ValueError("Run identity does not match its declared block")
    if type(manifest.get("validation_only")) is not bool or (
            manifest["validation_only"] and not campaign["validation_only"]):
        raise ValueError("Validation/test-controller run cannot enter formal results")
    if campaign.get("design_profile") in (QUICK_PROFILE, FIXED_MODEL_PROFILE) and not campaign["validation_only"]:
        window = [config.get(name) for name in
                  ("measurement_start_s", "measurement_end_s", "drain_end_s")]
        if window != [20, 140, 143.5]:
            raise ValueError("quick draft run window must be 20/140/143.5 seconds")
    if strategy == "3":
        expected_model = campaign["models"][block["scene"]]
        if not manifest.get("model") or manifest["model"].get("sha256") != expected_model["sha256"]:
            raise ValueError("Frozen scene model differs from run model")
    if metrics["generated"] != condition["requests"]:
        raise ValueError("Generated request budget differs from campaign condition")
    effective = summary.read_json(path / "raw/effective-experiment-config.json")
    if len(effective["vehicle_ids"]) != condition["vehicles"]:
        raise ValueError("Vehicle count differs from campaign condition")
    hashes = manifest.get("input_hashes", {})
    if not hashes:
        raise ValueError("Run input hashes are missing")
    for filename, digest in hashes.items():
        file_path = resolve_path(path, filename)
        if not file_path.is_file() or summary.sha256_file(file_path) != digest:
            raise ValueError("Run input hash mismatch")
    candidates = [resolve_path(path, name) for name in hashes
                  if Path(name).name.endswith("input-summary.json")]
    if len(candidates) != 1:
        raise ValueError("A hashed input-summary is required to verify condition parameters")
    inputs = summary.read_json(candidates[0])
    if inputs.get("scenario") != block["scene"] or (
            inputs.get("requested_speed_kmh") != condition["speed_kmh"] or
            inputs.get("requested_count") != condition["requests"] or
            len(inputs.get("vehicles", [])) != condition["vehicles"]):
        raise ValueError("Frozen input summary differs from campaign condition")
    networks = [digest for filename, digest in hashes.items()
                if Path(filename).name == "network.net.xml"]
    if len(networks) > 1 or (not networks and not campaign["validation_only"]):
        raise ValueError("Expected one hashed road network")
    route_families = [
        {key: vehicle.get(key) for key in
         ("vehicle_id", "source_route_index", "route_family_index", "route_start_offset")}
        for vehicle in inputs["vehicles"]]
    if not campaign["validation_only"] and any(
            value is None for vehicle in route_families for value in vehicle.values()):
        raise ValueError("Formal inputs lack route-family assignment evidence")
    seeds = config.get("seeds")
    if not isinstance(seeds, dict) or set(seeds) != {
            "rng_seed", "rng_run", "sumo_seed", "srand_seed"}:
        raise ValueError("Incomplete random seed tuple")
    for value in seeds.values():
        _positive_integer(value, "simulation seed")
    return {
        "input_hashes": hashes,
        "seed_tuple": json.dumps(seeds, sort_keys=True),
        "network_sha256": networks[0] if networks else None,
        "route_family_sha256": hashlib.sha256(
            json.dumps(route_families, sort_keys=True).encode("utf-8")).hexdigest(),
        "window": [config[name] for name in
                   ("measurement_start_s", "measurement_end_s", "drain_end_s")],
        "request_sha256": rows_digest(
            path / "raw/request-events.csv", "GENERATED",
            ("request_id", "name", "vehicle_id", "node_id", "sequence", "send_ns", "deadline_ns")),
        "mobility_sha256": rows_digest(
            path / "raw/mobility-events.csv", "SAMPLE",
            ("time_ns", "vehicle_id", "x", "y", "speed_mps")),
    }


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, records, scalar_only=False):
    if not records:
        raise ValueError("Refusing an empty result table")
    fields = list(records[0])
    if scalar_only:
        fields = [key for key in fields if all(
            record.get(key) is None or isinstance(record.get(key), (str, int, float, bool))
            for record in records)]
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def write_baseline(output, blocks):
    fields = ("scene", "seed_family", "strategy", "request_id", "vehicle_id",
              "send_ns", "deadline_ns", "terminal", "rtt_ms",
              "common_handover", "common_tie", "own_handover", "own_tie")
    event_fields = ("scene", "seed_family", "strategy", "vehicle_id", "time_ns",
                    "from_rsu", "to_rsu", "kind", "is_handover", "loss_duration_ns")
    with (output / "baseline-requests.csv").open("w", newline="", encoding="utf-8") as stream, (
            output / "baseline-associations.csv").open("w", newline="", encoding="utf-8") as events_stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        event_writer = csv.DictWriter(events_stream, fieldnames=event_fields)
        writer.writeheader()
        event_writer.writeheader()
        for scene, seed, paths in blocks:
            common_events = handover_events(summary.rows(paths["0"] / "raw/mobility-events.csv"))
            for strategy, path in paths.items():
                own_events = handover_events(summary.rows(path / "raw/mobility-events.csv"))
                event_writer.writerows(dict(event, scene=scene, seed_family=seed, strategy=strategy)
                                       for event in own_events)
                for row in summary.rows(path / "raw/request-events.csv"):
                    if row["event"] not in summary.TERMINALS:
                        continue
                    send, deadline = int(row["send_ns"]), int(row["deadline_ns"])
                    vehicle = row["vehicle_id"]
                    common, common_tie = request_handover(vehicle, send, deadline, common_events)
                    own, own_tie = request_handover(vehicle, send, deadline, own_events)
                    writer.writerow({
                        "scene": scene, "seed_family": seed, "strategy": strategy,
                        "request_id": row["request_id"], "vehicle_id": vehicle,
                        "send_ns": send, "deadline_ns": deadline, "terminal": row["event"],
                        "rtt_ms": (int(row["time_ns"]) - send) / 1e6 if row["event"] == "DATA" else "",
                        "common_handover": int(common), "common_tie": int(common_tie),
                        "own_handover": int(own), "own_tie": int(own_tie)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_manifest", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = aggregate_campaign(args.campaign_manifest, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, "aggregate_campaign: {}\n".format(error))
    print(json.dumps({"status": result["status"], "run_count": result["run_count"],
                      "validation_only": result["validation_only"],
                      "output": str(args.output_dir.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
