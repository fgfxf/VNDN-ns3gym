"""Tiny complete, explicitly validation-only campaigns; no simulator is run."""
import hashlib
import importlib.util
import json
from pathlib import Path

from experiment_test_support import valid_run


_SPEC = importlib.util.spec_from_file_location(
    "campaign_fixture_summary", Path(__file__).resolve().parents[1] / "summarize.py")
summary = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summary)


def dump(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seal_run(run, source_sha, model, block_id, strategy):
    config = json.loads((run / "experiment.json").read_text())
    manifest = {
        "schema_version": 1, "run_id": run.name, "block_id": block_id,
        "scenario": config["scenario"], "strategy": strategy, "status": "complete",
        "validation_only": True, "source": {"sha256": source_sha},
        "input_hashes": {config["input_summary"]: digest(config["input_summary"])},
        "model": model if strategy == 3 else None,
        "processes": {"simulation": {"returncode": 0}, "controller": {"returncode": 0}},
        "measurement_scope": summary.MEASUREMENT_SCOPE,
    }
    calculated = summary.summarize_run(run, require_manifest=False)
    calculated.update(block_id=block_id, strategy=strategy, validation_only=True)
    dump(run / "run-metrics.json", calculated)
    manifest["artifact_hashes"] = {
        str(path.relative_to(run)): digest(path)
        for path in [run / "experiment.json", run / "run-metrics.json"] +
        list((run / "raw").iterdir())}
    dump(run / "manifest.json", manifest)
    return {"path": str(run), "manifest_sha256": digest(run / "manifest.json")}


def create_campaign(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = "a" * 64
    campaign = {
        "schema_version": 1, "campaign_id": "tiny-validation", "validation_only": True,
        "source_sha256": source, "repetitions": [50001, 50002],
        "bootstrap": {"resamples": 100, "seed": 7}, "baseline_condition_id": "base",
        "conditions": [{"id": "base", "vehicles": 1, "speed_kmh": 18, "requests": 4}],
        "scans": {name: ["base"] for name in (
            "interest", "speed", "vehicles", "vehicles_fixed_k")},
        "models": {}, "model_evaluations": {}, "blocks": [], "time_bin_seconds": .1,
    }
    for scene in ("circle", "grid", "spidermap"):
        model_path = root / (scene + ".pt")
        model_path.write_bytes(("validation placeholder " + scene).encode())
        model = {"path": str(model_path), "sha256": digest(model_path)}
        campaign["models"][scene] = model
        classes = 2 if scene == "circle" else 7
        evaluation = {
            "schema_version": 1, "scenario": scene, "split": "evaluation",
            "model_sha256": model["sha256"], "dataset_manifest_sha256": "b" * 64,
            "label_values": list(range(classes)),
            "confusion_matrix": [[int(i == j) for j in range(classes)]
                                 for i in range(classes)],
        }
        history_path = root / (scene + "-training-history.csv")
        history_path.write_text(
            "epoch,train_loss,validation_loss,validation_macro_f1\n"
            "1,1.0,1.2,0.4\n2,0.8,1.0,0.6\n3,0.6,0.9,0.7\n", encoding="utf-8")
        evaluation["training_history"] = {
            "path": str(history_path), "sha256": digest(history_path)}
        evaluation_path = root / (scene + "-evaluation.json")
        dump(evaluation_path, evaluation)
        campaign["model_evaluations"][scene] = {
            "path": str(evaluation_path), "sha256": digest(evaluation_path)}
        for repetition in campaign["repetitions"]:
            block_id = "{}-base-{}".format(scene, repetition)
            input_summary = root / (block_id + "-input-summary.json")
            dump(input_summary, {"scenario": scene, "vehicles": [{"vehicle_id": "veh0"}],
                                 "requested_speed_kmh": 18, "requested_count": 4,
                                 "seed": repetition})
            block = {"scene": scene, "condition_id": "base", "seed_family": repetition,
                     "block_id": block_id, "runs": {}}
            for strategy in range(4):
                run = valid_run(root / (block_id + "-s" + str(strategy)))
                config = json.loads((run / "experiment.json").read_text())
                config.update(scenario=scene, strategy=strategy, block_id=block_id,
                              input_summary=str(input_summary),
                              seeds={"rng_seed": 1, "rng_run": repetition,
                                     "sumo_seed": repetition, "srand_seed": repetition})
                dump(run / "experiment.json", config)
                valid_run(run, preserve_config=True)
                block["runs"][str(strategy)] = seal_run(
                    run, source, model, block_id, strategy)
            campaign["blocks"].append(block)
    path = root / "campaign.json"
    dump(path, campaign)
    return path
