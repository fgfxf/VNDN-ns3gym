#!/usr/bin/env python3.8
"""Audit hashed causal training shards before fitting any scene model.

Counts describe correlated observations, not independent experimental repeats.
An empty run remains in the report; the coverage gates apply to whole splits.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np

AI_ROOT = Path(__file__).resolve().parents[2] / "contrib/vndn-nn-rd/ai-training"
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))
from formal_data import load_dataset_manifest, sha256_file  # noqa: E402

SCENES = {"circle": 2, "grid": 7, "spidermap": 7}
SPLITS = ("train", "validation", "evaluation")


def _integer(value, field, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError("invalid " + field)
    return value


def _counts(classes):
    return dict(observation_count=0, sample_count=0, class_counts=[0] * classes,
                excluded={}, short_history_count=0, empty_history_count=0,
                unknown_history_count=0, accepted_short_history_count=0,
                accepted_empty_history_count=0, handover_count=0,
                accepted_handover_count=0, cross_rsu_target_count=0)


def _record(counts, row, accepted):
    counts["observation_count"] += 1
    history = row.get("actual_history_length")
    valid_history = isinstance(history, int) and not isinstance(history, bool) and 0 <= history <= 10
    if not valid_history:
        counts["unknown_history_count"] += 1
    else:
        counts["short_history_count"] += history < 10
        counts["empty_history_count"] += history == 0
    counts["handover_count"] += bool(row.get("handover"))
    if accepted:
        counts["sample_count"] += 1
        counts["class_counts"][row["label"]] += 1
        counts["accepted_short_history_count"] += history < 10
        counts["accepted_empty_history_count"] += history == 0
        counts["accepted_handover_count"] += row["handover"]
        counts["cross_rsu_target_count"] += row["label"] != row["source_rsu_id"]
    else:
        reason = row["exclusion_reason"]
        counts["excluded"][reason] = counts["excluded"].get(reason, 0) + 1


def _same_counts(actual, declared, name, fields):
    for field in fields:
        value = declared.get(field)
        if field.endswith("_count"):
            _integer(value, name + "." + field)
        elif field == "class_counts":
            if not isinstance(value, list):
                raise ValueError(name + " class_counts must be a list")
            for item in value:
                _integer(item, name + ".class_counts")
        if value != actual[field]:
            raise ValueError("{} {} count mismatch: declared={!r}, observed={!r}".format(
                name, field, value, actual[field]))


def _audit_scene(scene, path):
    path = Path(path).resolve()
    digest = sha256_file(path)
    manifest = load_dataset_manifest(path)  # Verify original sources and every shard hash.
    if manifest["scenario"] != scene:
        raise ValueError("scenario does not match requested scene: " + scene)
    classes = SCENES[scene]
    result = dict(manifest_path=str(path), manifest_sha256=digest,
                  validation_only=manifest.get("validation_only"),
                  source_code_sha256=manifest["source_code_sha256"],
                  label_values=list(range(classes)), runs=[], splits={})
    for split in SPLITS:
        result["splits"][split] = dict(_counts(classes), run_count=0, seed_families=[],
                                       conditions={}, seeds={}, vehicles={})
    run_ids = set()
    for shard in manifest["shards"]:
        split = shard["split"]
        if split not in SPLITS:
            raise ValueError("invalid shard split")
        run_id, condition = shard["run_id"], shard["condition_id"]
        if not isinstance(run_id, str) or not run_id or run_id in run_ids:
            raise ValueError("invalid or duplicate run_id")
        if not isinstance(condition, str) or not condition:
            raise ValueError("invalid condition_id")
        run_ids.add(run_id)
        seed = _integer(shard["seed_family"], "seed_family", 1)
        selected = result["splits"][split]
        selected["run_count"] += 1
        selected["seed_families"] = sorted(set(selected["seed_families"]) | {seed})
        run = dict(_counts(classes), run_id=run_id, split=split, condition_id=condition,
                   seed_family=seed, source_path=shard["source_path"], vehicles={})
        condition_counts = selected["conditions"].setdefault(condition, _counts(classes))
        seed_counts = selected["seeds"].setdefault(str(seed), _counts(classes))
        targets = np.load(path.parent / shard["targets"], mmap_mode="r", allow_pickle=False)
        features = np.load(path.parent / shard["features"], mmap_mode="r", allow_pickle=False)
        sample_count = _integer(shard["sample_count"], "shard.sample_count")
        if (targets.shape != (sample_count,) or not np.issubdtype(targets.dtype, np.integer) or
                features.shape != (sample_count, 10, 6)):
            raise ValueError("feature/target array count or shape mismatch")
        samples_path = path.parent / shard["samples"]
        if shard["samples"] not in shard["hashes"]:
            raise ValueError("samples file lacks a declared hash")
        with samples_path.open(encoding="utf-8") as stream:
            for text in stream:
                row = json.loads(text)
                if not isinstance(row, dict):
                    raise ValueError("observation evidence must be a JSON object")
                reason = row.get("exclusion_reason")
                accepted = "sample_index" in row and reason in (None, "")
                if accepted:
                    index = _integer(row["sample_index"], "sample_index")
                    label = _integer(row.get("label"), "label")
                    source = _integer(row.get("source_rsu_id"), "source_rsu_id")
                    if index != run["sample_count"] or index >= sample_count:
                        raise ValueError("sample_index must be consecutive and in range")
                    if label >= classes or source >= classes:
                        raise ValueError("label/source_rsu_id outside scenario classes")
                    if label != int(targets[index]):
                        raise ValueError("sample label differs from target array")
                    if _integer(row.get("actual_history_length"), "actual_history_length") > 10:
                        raise ValueError("actual_history_length exceeds 10")
                    if not isinstance(row.get("handover"), bool):
                        raise ValueError("accepted handover marker must be boolean")
                elif ("sample_index" in row or not isinstance(reason, str) or not reason):
                    raise ValueError("sample_index and exclusion_reason contradict acceptance")
                vehicle_key = json.dumps([run_id, row.get("vehicle_id"), row.get("obu_node_id")],
                                         ensure_ascii=False, separators=(",", ":"))
                vehicle = dict(_counts(classes), run_id=run_id, vehicle_id=row.get("vehicle_id"),
                               obu_node_id=row.get("obu_node_id"))
                split_vehicle = selected["vehicles"].setdefault(vehicle_key, vehicle)
                run_vehicle = run["vehicles"].setdefault(vehicle_key, dict(_counts(classes),
                    vehicle_id=row.get("vehicle_id"), obu_node_id=row.get("obu_node_id")))
                for group in (run, selected, condition_counts, seed_counts, split_vehicle, run_vehicle):
                    _record(group, row, accepted)
        if sha256_file(samples_path) != shard["hashes"][shard["samples"]]:
            raise ValueError("samples hash changed during coverage audit")
        _same_counts(run, shard, run_id,
                     ("sample_count", "observation_count", "class_counts", "excluded"))
        result["runs"].append(run)
    for split in SPLITS:
        _same_counts(result["splits"][split], manifest["splits"][split], split,
                     ("sample_count", "class_counts", "run_count", "seed_families"))
    if sha256_file(path) != digest:
        raise ValueError("dataset manifest hash changed during coverage audit")
    return result


def audit_datasets(manifests, output_path):
    """Write a report, returning it on success or raising ValueError on any issue.

    ``manifests`` must map all three scene names to dataset-manifest.json paths.
    Hash/count errors and insufficient split coverage both retain a report with
    status ``insufficient``; issue kinds distinguish invalid evidence from gaps.
    """
    report = dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                  status="insufficient", issues=[], scenes={},
                  counting_unit="accepted decision observations; independent units are complete runs")
    if not isinstance(manifests, dict) or set(manifests) != set(SCENES):
        report["issues"].append(dict(kind="scene_set_mismatch",
                                     message="all three scenario manifests are required"))
    for scene in SCENES:
        if not isinstance(manifests, dict) or scene not in manifests:
            continue
        try:
            result = _audit_scene(scene, manifests[scene])
            report["scenes"][scene] = result
            for split, row in result["splits"].items():
                missing = [label for label, count in enumerate(row["class_counts"]) if not count]
                if not row["sample_count"]:
                    report["issues"].append(dict(scene=scene, split=split, kind="empty_split"))
                if missing:
                    report["issues"].append(dict(scene=scene, split=split, kind="missing_classes", labels=missing))
                if not row["cross_rsu_target_count"]:
                    report["issues"].append(dict(scene=scene, split=split, kind="no_cross_rsu_targets"))
        except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
            report["issues"].append(dict(scene=scene, kind="invalid_dataset", message=str(error)))
    if not report["issues"]:
        report["status"] = "complete"
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                      encoding="utf-8")
    if report["issues"]:
        raise ValueError("training coverage insufficient; see " + str(output))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for scene in SCENES:
        parser.add_argument("--" + scene, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_datasets({scene: getattr(args, scene) for scene in SCENES}, args.output)
    print("Training coverage: " + report["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
