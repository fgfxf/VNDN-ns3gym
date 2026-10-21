#!/usr/bin/env python3.8
"""Serial campaign design and execution with preserved attempts."""
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCENES = ("circle", "grid", "spidermap")
CANCEL_GRACE_SECONDS = 30
COMPACT_PROFILE = "compact-exploratory-v1"
QUICK_PROFILE = "quick-draft-v1"
SPARSE_PROFILES = (COMPACT_PROFILE, QUICK_PROFILE)
SAMPLING_SPLITS = ("train", "validation", "evaluation")


def _module(name):
    spec = importlib.util.spec_from_file_location("_campaign_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _module("run_experiment")
generator = _module("generate_inputs")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return runner.summary.sha256_file(Path(path))


def make_plan(campaign_id, duration=None, warmup=20, drain=3.5, profile="full"):
    if profile not in ("full",) + SPARSE_PROFILES:
        raise ValueError("unknown design profile")
    if duration is None:
        duration = 120 if profile == QUICK_PROFILE else 300
    if profile == COMPACT_PROFILE and (duration, warmup, drain) != (300, 20, 3.5):
        raise ValueError("compact profile freezes measurement/warmup/drain at 300/20/3.5 seconds")
    if profile == QUICK_PROFILE and (duration, warmup, drain) != (120, 20, 3.5):
        raise ValueError("quick profile freezes measurement/warmup/drain at 120/20/3.5 seconds")
    for value in (duration, warmup, drain):
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("time settings must be finite")
    if duration <= 0 or warmup < 0 or drain < 3:
        raise ValueError("invalid measurement/warmup/drain")
    base = duration * 50
    if int(base) != base or int(base / 4) != base / 4:
        raise ValueError("duration must permit exact integral request levels")
    base = int(base)
    conditions, by_parameters = [], {}

    def condition(n, speed, requests):
        key = (n, speed, requests)
        if key not in by_parameters:
            name = "baseline" if key == (10, 30, base) else "n{}-v{}-k{}".format(*key)
            by_parameters[key] = name
            conditions.append(dict(id=name, vehicles=n, speed_kmh=speed, requests=requests))
        return by_parameters[key]

    condition(10, 30, base)
    scans = {
        "interest": [condition(10, 30, k) for k in
                     (base // 4, base // 2, base, base * 3 // 2, base * 2)],
        "speed": [condition(10, v, base) for v in (10, 20, 30, 40, 50)],
        "vehicles": [condition(n, 30, int(n * 5 * duration)) for n in (5, 10, 20, 30, 40)],
        "vehicles_fixed_k": [condition(n, 30, base) for n in (5, 10, 20, 30, 40)],
    }
    if profile in SPARSE_PROFILES:
        conditions, by_parameters = [], {}
        condition(10, 30, base)
        scans = {
            "interest": [condition(10, 30, k) for k in (base // 4, base, base * 2)],
            "speed": [condition(10, v, base) for v in (10, 30, 50)],
            "vehicles": [condition(n, 30, int(n * 5 * duration)) for n in (5, 10, 15, 20)],
        }
    pilot = ["baseline"]
    for scan in ("interest", "speed", "vehicles"):
        pilot.extend([scans[scan][0], scans[scan][-1]])
    plan = {
        "schema_version": 1, "campaign_id": campaign_id,
        "created_utc": stamp(), "validation_only": False,
        "measurement_start": warmup, "measurement_duration": duration, "drain_seconds": drain,
        "conditions": conditions, "scans": scans, "baseline_condition_id": "baseline",
        "pilot_conditions": pilot,
        "seed_families": {
            "pilot": [10001, 10002], "train": list(range(20001, 20011)),
            "validation": list(range(30001, 30004)),
            "evaluation": list(range(40001, 40006)), "test": list(range(50001, 50021)),
        },
        "bootstrap": {"resamples": 10000, "seed": 61021},
        "time_bin_seconds": 5, "source_sha256": None, "models": {},
        "timeouts": {}, "minimum_free_disk_bytes": 20 * 1024**3,
        "status": "candidate-unfrozen",
    }
    if profile in SPARSE_PROFILES:
        quick = profile == QUICK_PROFILE
        plan.update(design_profile=profile, sampling_jobs=_compact_initial_jobs(conditions, profile),
                    sampling_revisions=[], sampling_max_additional_jobs=0 if quick else 24,
                    sampling_max_additional_per_scene=0 if quick else 8,
                    figure_ids=_module("aggregate_campaign").expected_figure_ids(scans))
        plan["seed_families"] = {
            "pilot": [12021] if quick else [11021],
            **{split: sorted(row["seed_family"] for row in plan["sampling_jobs"][split])
               for split in SAMPLING_SPLITS},
            "test": [52001, 52002] if quick else list(range(51001, 51006)),
        }
        plan["pilot_conditions"] = ["baseline"]
        validate_sampling_plan(plan)
    return plan


def _compact_initial_jobs(conditions, profile=COMPACT_PROFILE):
    base = 6000 if profile == QUICK_PROFILE else 15000
    representative = {(10, 30, base), (10, 10, base), (10, 50, base), (20, 30, base * 2)}
    selected = [row["id"] for row in conditions if
                (row["vehicles"], row["speed_kmh"], row["requests"]) in representative]
    result = {}
    offset = 2000 if profile == QUICK_PROFILE else 0
    for split, start in (("train", 21001), ("validation", 31001), ("evaluation", 41001)):
        ids = [row["id"] for row in conditions] if split == "train" else selected
        result[split] = [dict(scene=scene, condition_id=cid,
                              seed_family=start + offset + scene_index * len(ids) + index)
                         for scene_index, scene in enumerate(SCENES) for index, cid in enumerate(ids)]
    return result


def validate_sampling_plan(plan):
    """Validate sparse rows rather than multiplying their seed union by conditions."""
    profile = plan.get("design_profile", "full")
    if profile not in ("full",) + SPARSE_PROFILES:
        raise ValueError("unknown design profile")
    if profile not in SPARSE_PROFILES:
        return
    quick = profile == QUICK_PROFILE
    duration = 120 if quick else 300
    base = duration * 50
    if (plan["measurement_duration"], plan["measurement_start"], plan["drain_seconds"]) != (
            duration, 20, 3.5):
        raise ValueError("sparse profile measurement window changed")
    expected_parameters = {(10, 30, base), (10, 30, base // 4), (10, 30, base * 2),
                           (10, 10, base), (10, 50, base), (5, 30, base // 2),
                           (15, 30, base * 3 // 2), (20, 30, base * 2)}
    conditions = plan["conditions"]
    if len(conditions) != 8 or {(c["vehicles"], c["speed_kmh"], c["requests"])
                              for c in conditions} != expected_parameters:
        raise ValueError("compact requires exactly the eight approved conditions")
    analysis = _module("aggregate_campaign")
    if (set(plan["scans"]) != {"interest", "speed", "vehicles"} or
            [len(plan["scans"][s]) for s in ("interest", "speed", "vehicles")] != [3, 3, 4]):
        raise ValueError("compact requires three declared scans with 3/3/4 points")
    by_parameters = {(c["vehicles"], c["speed_kmh"], c["requests"]): c["id"] for c in conditions}
    expected_scans = {
        "interest": [by_parameters[10, 30, k] for k in (base // 4, base, base * 2)],
        "speed": [by_parameters[10, v, base] for v in (10, 30, 50)],
        "vehicles": [by_parameters[n, 30, n * 5 * duration] for n in (5, 10, 15, 20)],
    }
    if plan["scans"] != expected_scans or plan["baseline_condition_id"] != by_parameters[10, 30, base]:
        raise ValueError("compact scan coordinates or shared baseline changed")
    if plan.get("figure_ids") != analysis.expected_figure_ids(plan["scans"]):
        raise ValueError("compact figure declaration differs from the planned 25 figures")
    formal_seeds = [52001, 52002] if quick else list(range(51001, 51006))
    if plan["seed_families"]["test"] != formal_seeds:
        raise ValueError("sparse profile requires its predeclared formal seed families")
    limits = (0, 0) if quick else (24, 8)
    if (plan.get("sampling_max_additional_jobs"), plan.get("sampling_max_additional_per_scene")) != limits:
        raise ValueError("sampling addition limits differ from the approved profile")
    if quick and (plan.get("sampling_revisions") != [] or plan["seed_families"]["pilot"] != [12021]):
        raise ValueError("quick profile has fixed sampling and pilot seed declarations")
    initial = _compact_initial_jobs(conditions, profile)
    rows_by_split = plan.get("sampling_jobs", {})
    if set(rows_by_split) != set(SAMPLING_SPLITS):
        raise ValueError("all three sparse sampling splits must be declared")
    ids = {row["id"] for row in conditions}
    if len(ids) != 8:
        raise ValueError("duplicate condition IDs")
    seen = set()
    if set(plan["seed_families"]) != {"pilot", "train", "validation", "evaluation", "test"}:
        raise ValueError("compact requires the five declared seed-purpose splits")
    for split, seeds in plan["seed_families"].items():
        if (not seeds or any(type(s) is not int or s <= 0 for s in seeds) or
                len(seeds) != len(set(seeds)) or seen.intersection(seeds)):
            raise ValueError("invalid, duplicate or leaking seed families")
        seen.update(seeds)
    extras = []
    for split in SAMPLING_SPLITS:
        rows = rows_by_split[split]
        if quick and rows != initial[split]:
            raise ValueError("quick profile has a fixed 48-run sampling budget and assignment")
        if rows[:len(initial[split])] != initial[split]:
            raise ValueError("initial sparse sampling jobs cannot be removed or reinterpreted")
        if sorted(row["seed_family"] for row in rows) != sorted(plan["seed_families"][split]):
            raise ValueError("sampling jobs disagree with their declared seed families")
        for index, row in enumerate(rows):
            if (set(row) != {"scene", "condition_id", "seed_family"} or
                    row["scene"] not in SCENES or row["condition_id"] not in ids):
                raise ValueError("invalid sparse sampling job")
            if index >= len(initial[split]):
                start = {"train": 22000, "validation": 32000, "evaluation": 42000}[split]
                if not start < row["seed_family"] < start + 100:
                    raise ValueError("sampling addition must use its reserved seed domain")
                extras.append(dict(row, split=split))
    if len(extras) > 24 or any(sum(row["scene"] == scene for row in extras) > 8 for scene in SCENES):
        raise ValueError("sampling additions exceed the approved 24/eight-per-scene budget")
    declared = [row for revision in plan.get("sampling_revisions", []) for row in revision["additions"]]
    key = lambda row: (row["split"], row["scene"], row["condition_id"], row["seed_family"])
    if sorted(extras, key=key) != sorted(declared, key=key):
        raise ValueError("sampling additions require an explicit revision record")


def extend_sampling_plan(plan, additions, reason):
    validate_sampling_plan(plan)
    if plan.get("design_profile") == QUICK_PROFILE:
        raise ValueError("quick profile has a fixed 48-run sampling budget; coverage failures must be reported")
    if plan.get("design_profile") != COMPACT_PROFILE:
        raise ValueError("bounded sampling additions require the compact profile")
    if plan.get("status") == "formal-frozen" or plan.get("models"):
        raise ValueError("sampling cannot change after models have been frozen")
    if not isinstance(reason, str) or not reason.strip() or not additions:
        raise ValueError("sampling additions require a nonempty coverage reason and job list")
    revised = copy.deepcopy(plan)
    for row in additions:
        if set(row) != {"split", "scene", "condition_id", "seed_family"} or row["split"] not in SAMPLING_SPLITS:
            raise ValueError("only explicit train/validation/evaluation jobs may be appended")
        if type(row["seed_family"]) is not int or row["seed_family"] < 1:
            raise ValueError("sampling seed family must be a positive integer")
        split = row["split"]
        revised["sampling_jobs"][split].append({k: v for k, v in row.items() if k != "split"})
        revised["seed_families"][split].append(row["seed_family"])
        revised["seed_families"][split].sort()
    revised["sampling_revisions"].append(dict(number=len(revised["sampling_revisions"]) + 1,
        utc=stamp(), reason=reason.strip(), additions=copy.deepcopy(additions)))
    validate_sampling_plan(revised)
    return revised


def _commit_sampling_revision(root, directory):
    """Replay a prepared write set; an interrupted multi-file update stays auditable."""
    record_path = directory / "revision.json"
    record = runner.summary.read_json(record_path)
    for item in record["files"]:
        path = root / "plan" / item["name"]
        if item["name"] != Path(item["name"]).name:
            raise ValueError("invalid sampling revision path")
        current = digest(path)
        for label in ("before", "after"):
            if digest(directory / item[label]) != item[label + "_sha256"]:
                raise ValueError("sampling revision evidence was modified")
        if current not in (item["before_sha256"], item["after_sha256"]):
            raise ValueError("sampling revision cannot overwrite an unrelated design or state")
    for item in record["files"]:
        runner.write_json(root / "plan" / item["name"],
                          runner.summary.read_json(directory / item["after"]))
    record.update(status="complete", completed_utc=stamp())
    runner.write_json(record_path, record)


def recover_sampling_revision(root):
    root = Path(root).resolve()
    with (root / "plan/campaign.lock").open("a+") as lock, \
            (root / "plan/workflow.lock").open("a+") as workflow_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(workflow_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (ROOT / "build/experiment-run.lock").open("a+") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(list((root / "workflow" / stage).glob("*/attempt-*"))
               for stage in ("train", "evaluate", "figures")):
            raise ValueError("cannot recover sampling changes after model/assessment work")
        pending = [p.parent for p in (root / "plan/sampling-revisions").glob("*/revision.json")
                   if runner.summary.read_json(p).get("status") == "prepared"]
        if len(pending) != 1:
            raise ValueError("exactly one prepared sampling revision is required")
        revised = runner.summary.read_json(pending[0] / "after-design.json")
        validate_sampling_plan(revised)
        if runner.source_snapshot(ROOT)["sha256"] != revised["source_sha256"]:
            raise ValueError("source changed since sampling revision preparation")
        _commit_sampling_revision(root, pending[0])
        return revised


def append_sampling_jobs(root, additions, reason):
    """Append covered-purpose jobs; preserve and revalidate every existing job identity."""
    root = Path(root).resolve()
    with (root / "plan/campaign.lock").open("a+") as lock, \
            (root / "plan/workflow.lock").open("a+") as workflow_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(workflow_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Dataset-only coverage audits may legitimately trigger additions.
        # workflow uses a new datasets-revision-NNN namespace afterwards, so
        # the old dataset evidence and all its absolute paths stay intact.
        if any(list((root / "workflow" / stage).glob("*/attempt-*"))
               for stage in ("train", "evaluate", "figures")):
            raise ValueError("sampling additions must precede model/assessment workflow attempts")
        for path in (root / "plan/sampling-revisions").glob("*/revision.json"):
            if runner.summary.read_json(path).get("status") != "complete":
                raise ValueError("pending sampling revision; run recover-sampling first")
        plan = runner.summary.read_json(root / "plan/design.json")
        if plan.get("status") != "development-frozen":
            raise ValueError("sampling additions require development-frozen and unfitted models")
        if runner.source_snapshot(ROOT)["sha256"] != plan["source_sha256"]:
            raise ValueError("source changed; old sampling cannot be reinterpreted")
        with (ROOT / "build/experiment-run.lock").open("a+") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        revised = extend_sampling_plan(plan, additions, reason)
        states = {}
        for split in plan["seed_families"]:
            path = root / "plan" / ("state-" + split + ".json")
            if not path.exists():
                continue
            state = runner.summary.read_json(path)
            if state.get("execution_design_sha256") != execution_identity(plan, split):
                raise ValueError("old execution identity differs before sampling revision")
            expected = {j["job_id"]: j for j in jobs_for(plan, split)}
            for job_id, entry in state["jobs"].items():
                if job_id not in expected or any(entry.get(k) != v for k, v in expected[job_id].items()):
                    raise ValueError("existing job identity differs from the frozen sampling plan")
                if entry.get("status") == "running":
                    raise ValueError("reconcile interrupted running jobs before sampling revision")
                job = expected[job_id]
                model_sha = (plan["models"].get(job["scene"]) or {}).get("sha256")
                complete = completed_attempt(entry.get("attempts", []), job, plan["source_sha256"], model_sha)
                if entry.get("status") == "complete" and complete is None:
                    raise ValueError("completed state has no verified completed attempt")
                if complete is not None:
                    _, hashes = runner.prepare_inputs(prepare_job_input(root, plan, job))
                    if runner.summary.read_json(complete / "manifest.json")["input_hashes"] != hashes:
                        raise ValueError("completed input differs during sampling revision")
            new_state = copy.deepcopy(state)
            new_state["execution_design_sha256"] = execution_identity(revised, split)
            new_state["updated_utc"] = stamp()
            states[path.name] = (state, new_state)
        number = len(revised["sampling_revisions"])
        directory = root / "plan/sampling-revisions" / ("revision-{:03d}".format(number))
        directory.mkdir(parents=True, exist_ok=False)
        files = []
        # Commit the design last; any interruption before that leaves a prepared
        # journal and a mismatch, which fails closed until explicit recovery.
        for name, (before, after) in list(states.items()) + [("design.json", (plan, revised))]:
            old, new = "before-" + name, "after-" + name
            # Preserve the original bytes too: valid JSON whitespace is not a
            # reason to reject (or silently rewrite) the previous identity.
            shutil.copyfile(root / "plan" / name, directory / old)
            runner.write_json(directory / new, after)
            files.append(dict(name=name, before=old, after=new,
                              before_sha256=digest(directory / old), after_sha256=digest(directory / new)))
        previous_namespace = "datasets" if number == 1 else "datasets-revision-{:03d}".format(number - 1)
        runner.write_json(directory / "revision.json", dict(schema_version=1, status="prepared",
            number=number, reason=reason, additions=additions, created_utc=stamp(), files=files,
            superseded_dataset_namespace=str(root / "workflow" / previous_namespace)))
        _commit_sampling_revision(root, directory)
        return revised


def jobs_for(plan, split):
    validate_sampling_plan(plan)
    if split not in plan["seed_families"]:
        raise ValueError("unknown data split: " + split)
    if plan.get("design_profile") in SPARSE_PROFILES and split in SAMPLING_SPLITS:
        jobs = []
        for row in plan["sampling_jobs"][split]:
            block = "{}-{}-{}-s{}".format(split, row["scene"], row["condition_id"], row["seed_family"])
            jobs.append(dict(row, job_id=block + "-a0", block_id=block, split=split, strategy=0))
        return jobs
    conditions = (plan["pilot_conditions"] if split == "pilot" else
                  [item["id"] for item in plan["conditions"]])
    jobs = []
    for scene in SCENES:
        for cid in conditions:
            for seed in plan["seed_families"][split]:
                block = "{}-{}-{}-s{}".format(split, scene, cid, seed)
                for strategy in (range(4) if split == "test" else (0,)):
                    jobs.append(dict(job_id=block + "-a" + str(strategy), block_id=block,
                                     split=split, scene=scene, condition_id=cid,
                                     seed_family=seed, strategy=strategy))
    if plan.get("design_profile") in SPARSE_PROFILES and split == "test":
        baseline = plan["baseline_condition_id"]
        ordered_conditions = [baseline] + [cid for cid in conditions if cid != baseline]
        jobs.sort(key=lambda job: (plan["seed_families"][split].index(job["seed_family"]),
                                   ordered_conditions.index(job["condition_id"]),
                                   SCENES.index(job["scene"]), job["strategy"]))
    return jobs


def initialize(root, plan):
    validate_sampling_plan(plan)
    path = Path(root) / "plan/design.json"
    if path.exists():
        raise FileExistsError("refusing to overwrite campaign design: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    runner.write_json(path, plan)


def completed_attempt(attempts, job, source_sha256, model_sha256=None):
    complete = [x for x in attempts if x.get("status") == "complete"]
    if len(complete) > 1:
        raise ValueError("multiple complete attempts for one independent job")
    if not complete:
        return None
    record = complete[0]
    path = Path(record["manifest_path"])
    if not path.is_file() or digest(path) != record["manifest_sha256"]:
        raise ValueError("completed attempt manifest hash changed")
    manifest = runner.summary.read_json(path)
    if (manifest.get("status"), manifest.get("block_id"), manifest.get("scenario"),
        manifest.get("strategy"), manifest.get("source", {}).get("sha256")) != (
            "complete", job["block_id"], job["scene"], job["strategy"], source_sha256):
        raise ValueError("completed attempt does not match frozen job/source")
    if job["split"] == "test" and manifest.get("validation_only") is not False:
        raise ValueError("pilot evidence cannot satisfy a final test job")
    if job["strategy"] == 3 and (manifest.get("model") or {}).get("sha256") != model_sha256:
        raise ValueError("completed attempt model differs from frozen model")
    runner.summary.summarize_run(path.parent)
    return path.parent


def reconcile_attempts(root, job, records):
    stage = "runs" if job["split"] == "test" else (
        "pilot" if job["split"] == "pilot" else "sampling")
    folder = Path(root) / stage / job["job_id"]
    by_number = {int(x["attempt"]): x for x in records}
    if len(by_number) != len(records):
        raise ValueError("duplicate attempt numbers in campaign state")
    for directory in sorted(folder.glob("attempt-*")):
        if not directory.is_dir():
            continue
        number = int(directory.name.split("-")[-1])
        if number in by_number:
            continue
        path = directory / "attempt.json"
        record = (runner.summary.read_json(path) if path.is_file() else
                  dict(attempt=number, status="running", path=str(directory)))
        if int(record.get("attempt", -1)) != number:
            raise ValueError("attempt directory disagrees with its identity")
        if record["status"] == "running":
            manifests = list((directory / "runs").glob("*/manifest.json"))
            if len(manifests) == 1:
                manifest = runner.summary.read_json(manifests[0])
                record.update(manifest_path=str(manifests[0]),
                              manifest_sha256=digest(manifests[0]))
                record["status"] = "complete" if manifest.get("status") == "complete" else "failed"
            else:
                record["status"] = "failed"
            record["recovered_utc"] = stamp()
            record["recovery_note"] = "Recovered after interrupted campaign state update"
            if record["status"] != "complete":
                record["error"] = "incomplete interrupted attempt; raw evidence preserved"
            runner.write_json(directory / "recovery.json", record)
        by_number[number] = record
    return [by_number[k] for k in sorted(by_number)]


def execution_identity(plan, split):
    keys = ("campaign_id", "measurement_start", "measurement_duration", "drain_seconds",
            "conditions", "baseline_condition_id", "scans", "source_sha256")
    value = {key: plan[key] for key in keys}
    value["seed_families"] = plan["seed_families"][split]
    if plan.get("design_profile") in SPARSE_PROFILES:
        value["design_profile"] = plan["design_profile"]
        value["figure_ids"] = plan["figure_ids"]
        if split in SAMPLING_SPLITS:
            value["sampling_jobs"] = plan["sampling_jobs"][split]
    if split == "pilot":
        value["pilot_conditions"] = plan["pilot_conditions"]
    if split == "test":
        value["models"] = plan["models"]
        value["timeouts"] = plan["timeouts"]
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def prepare_job_input(root, plan, job):
    condition = next(x for x in plan["conditions"] if x["id"] == job["condition_id"])
    output = (root / "inputs" / job["split"] / job["scene"] /
              job["condition_id"] / str(job["seed_family"]))
    config = output / "experiment-template.json"
    if not output.exists():
        generator.generate_inputs(
            scenario=job["scene"], output_dir=output, vehicles=condition["vehicles"],
            speed_kmh=condition["speed_kmh"], requests=condition["requests"],
            measurement_start=plan["measurement_start"],
            measurement_duration=plan["measurement_duration"], drain_seconds=plan["drain_seconds"],
            seed=job["seed_family"], ns3_root=ROOT)
    template, hashes = runner.prepare_inputs(config)
    expected = (job["scene"], job["seed_family"], plan["measurement_start"],
                plan["measurement_start"] + plan["measurement_duration"])
    actual = (template["scenario"], template["seeds"]["rng_run"],
              template["measurement_start_s"], template["measurement_end_s"])
    info = runner.summary.read_json(output / "input-summary.json")
    if actual != expected or (len(info["vehicles"]), info["requested_speed_kmh"],
                              info["requested_count"]) != (
                                  condition["vehicles"], condition["speed_kmh"], condition["requests"]):
        raise ValueError("existing input differs from frozen job: " + job["job_id"])
    seal = output / "bundle-sha256.json"
    if seal.exists():
        if runner.summary.read_json(seal) != hashes:
            raise ValueError("frozen job input has changed: " + job["job_id"])
    else:
        runner.write_json(seal, hashes)
    return config


@contextmanager
def cancellation_signals():
    state = {"signal": None}
    previous = {}

    def request_stop(signum, frame):
        if state["signal"] is None:
            state["signal"] = signal.Signals(signum).name

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, request_stop)
        yield state
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def check_cancelled(cancellation):
    if cancellation and cancellation["signal"]:
        raise ValueError("Interrupted by " + cancellation["signal"])


def process_identity(pid):
    """Linux process identity prevents signalling a reused PID during cleanup."""
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else (pid, fields[19])
    except (FileNotFoundError, ProcessLookupError):
        return None


def direct_children(pid):
    try:
        path = Path("/proc") / str(pid) / "task" / str(pid) / "children"
        return [int(value) for value in path.read_text().split()]
    except (FileNotFoundError, ProcessLookupError):
        return []


def descendants(pid):
    result = []
    for child in direct_children(pid):
        identity = process_identity(child)
        if identity is not None:
            result.append(identity)
            result.extend(descendants(child))
    return result


def signal_owned(identity, signum):
    if process_identity(identity[0]) != identity:
        return False
    try:
        os.kill(identity[0], signum)
        return True
    except ProcessLookupError:
        return False


def cancel_measured_runner(process):
    """Let the direct runner reap its separate simulation sessions before time exits."""
    started = time.monotonic()
    owned, notified = {}, set()
    cleanup = dict(grace_seconds=CANCEL_GRACE_SECONDS, runner_pids=[], forced_pids=[])
    while process.poll() is None:
        for identity in descendants(process.pid):
            owned[identity] = None
        for pid in direct_children(process.pid):
            identity = process_identity(pid)
            if identity is not None and identity not in notified:
                # /usr/bin/time stays alive to collect wait4/resource evidence.
                if signal_owned(identity, signal.SIGTERM):
                    cleanup["runner_pids"].append(pid)
                notified.add(identity)
        if time.monotonic() - started >= CANCEL_GRACE_SECONDS:
            break
        time.sleep(.05)

    # A broken runner may exit without reaping its separately-sessioned children.
    # Retain identities observed before reparenting; never kill by process name.
    live = [identity for identity in owned if process_identity(identity[0]) == identity]
    if live:
        # Stop known parents first, then discover children forked since the last
        # poll. Once those parents are stopped, the owned tree cannot keep growing.
        stopped = set()
        while True:
            for identity in live:
                if identity not in stopped:
                    signal_owned(identity, signal.SIGSTOP)
                    stopped.add(identity)
            for identity in descendants(process.pid):
                owned[identity] = None
            live = [identity for identity in owned
                    if process_identity(identity[0]) == identity]
            if all(identity in stopped for identity in live):
                break
        for identity in reversed(live):
            if signal_owned(identity, signal.SIGKILL):
                cleanup["forced_pids"].append(identity[0])
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Only after its runner/known children have been handled may time itself
        # be stopped. Missing resource output remains visible in the failed attempt.
        process.kill()
        process.wait()
        cleanup["time_wrapper_forced"] = True
    cleanup["elapsed_seconds"] = time.monotonic() - started
    return cleanup


def _run_job(root, plan, job, attempt_number, cancellation=None, no_build=False):
    config = prepare_job_input(root, plan, job)
    stage = "runs" if job["split"] == "test" else (
        "pilot" if job["split"] == "pilot" else "sampling")
    attempt = root / stage / job["job_id"] / ("attempt-{:03d}".format(attempt_number))
    timeout = float(plan["timeouts"].get(job["condition_id"],
                                         plan["timeouts"].get("default", 1800)))
    command = [
        sys.executable, str(HERE / "run_experiment.py"), "--config", str(config),
        "--output-root", str(attempt / "runs"), "--block-id", job["block_id"],
        "--strategy", str(job["strategy"]), "--timeout", str(timeout), "--python", sys.executable,
    ]
    if no_build:
        command.append("--no-build")
    if job["split"] != "test":
        command.append("--training-snapshots")
    if job["split"] == "pilot":
        command.append("--validation-only")
    if job["strategy"] == 3:
        model = plan["models"].get(job["scene"])
        if not model or digest(model["path"]) != model["sha256"]:
            raise ValueError("missing or changed frozen model")
        command.extend(["--model-file", model["path"], "--require-formal-contract"])
    attempt.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment.update(JOBS="4", OMP_NUM_THREADS="4", MKL_NUM_THREADS="4",
                       OPENBLAS_NUM_THREADS="4")
    resource_path = attempt / "resources.txt"
    measured = ["/usr/bin/time", "-f",
                '{"wall_seconds":%e,"max_rss_kib":%M,"exit_code":%x}',
                "-o", str(resource_path)] + command
    record = dict(attempt=attempt_number, status="running", started_utc=stamp(),
                  command=command, path=str(attempt), validation_only=job["split"] == "pilot")
    runner.write_json(attempt / "attempt.json", record)
    process = None
    launch_error = None
    with (attempt / "runner.log").open("w") as log:
        try:
            check_cancelled(cancellation)
            process = subprocess.Popen(
                measured, cwd=str(ROOT), env=environment, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                if cancellation and cancellation["signal"]:
                    record["cleanup"] = cancel_measured_runner(process)
                    break
                time.sleep(.05)
        except (OSError, ValueError) as error:
            launch_error = str(error)
        finally:
            if process is not None and process.poll() is None:
                record["cleanup"] = cancel_measured_runner(process)
    returncode = process.returncode if process is not None else None
    record.update(returncode=returncode, finished_utc=stamp())
    manifests = list((attempt / "runs").glob("*/manifest.json"))
    if len(manifests) == 1:
        path = manifests[0]
        manifest = runner.summary.read_json(path)
        record.update(manifest_path=str(path), manifest_sha256=digest(path))
        record["status"] = ("complete" if returncode == 0 and
                            manifest.get("status") == "complete" else "failed")
        if manifest.get("error"):
            record["error"] = manifest["error"]
    else:
        record["status"] = "failed"
        record["error"] = "runner did not produce exactly one run manifest"
    if launch_error:
        record.update(status="failed", error=launch_error)
    if cancellation and cancellation["signal"]:
        record.update(status="failed", interrupted_by=cancellation["signal"],
                      error="Interrupted by " + cancellation["signal"])
    if resource_path.is_file():
        for line in reversed(resource_path.read_text().splitlines()):
            try:
                record["resources"] = json.loads(line)
                break
            except ValueError:
                pass
    record["artifact_bytes"] = sum(p.stat().st_size for p in attempt.rglob("*") if p.is_file())
    runner.write_json(attempt / "attempt.json", record)
    return record


def execute(root, split, *, scenes=None, conditions=None, seeds=None, max_jobs=None,
            max_attempts=2, no_build=False):
    root = Path(root).resolve()
    with cancellation_signals() as cancellation, (root / "plan/campaign.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _execute_locked(root, split, scenes=scenes, conditions=conditions, seeds=seeds,
                               max_jobs=max_jobs, max_attempts=max_attempts,
                               cancellation=cancellation, no_build=no_build)


def _execute_locked(root, split, *, scenes, conditions, seeds, max_jobs, max_attempts,
                    cancellation, no_build=False):
    check_cancelled(cancellation)
    plan = runner.summary.read_json(root / "plan/design.json")
    source = runner.source_snapshot(ROOT)["sha256"]
    if plan.get("source_sha256") != source:
        raise ValueError("source must be frozen before execution; changed source is not resumable")
    if split != "pilot" and plan.get("status") not in ("development-frozen", "formal-frozen"):
        raise ValueError("development design must be frozen after pilot")
    if split == "test" and plan.get("status") != "formal-frozen":
        raise ValueError("models and runtime must be frozen before final testing")
    selected = [j for j in jobs_for(plan, split) if
                (not scenes or j["scene"] in scenes) and
                (not conditions or j["condition_id"] in conditions) and
                (not seeds or j["seed_family"] in seeds)]
    if not selected:
        raise ValueError("no selected jobs")
    state_path = root / "plan" / ("state-" + split + ".json")
    state = (runner.summary.read_json(state_path) if state_path.exists() else
             dict(schema_version=1, split=split, design_sha256=digest(root / "plan/design.json"),
                  execution_design_sha256=execution_identity(plan, split),
                  jobs={}, created_utc=stamp()))
    if state.get("execution_design_sha256") != execution_identity(plan, split):
        raise ValueError("execution design changed; old jobs cannot be reused for new conditions")
    # An orphaned runner may still be cleaning its separately-sessioned
    # descendants. Do not recover its attempt or start a competing simulation.
    with (ROOT / "build/experiment-run.lock").open("a+") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    executed = 0
    for job in selected:
        check_cancelled(cancellation)
        entry = state["jobs"].setdefault(job["job_id"], dict(job, status="planned", attempts=[]))
        entry["attempts"] = reconcile_attempts(root, job, entry["attempts"])
        model_sha = (plan["models"].get(job["scene"]) or {}).get("sha256")
        if completed_attempt(entry["attempts"], job, source, model_sha) is not None:
            # Check the current input seal as well as the complete run's
            # own hashes. Condition names alone are never sufficient.
            config = prepare_job_input(root, plan, job)
            _, expected_hashes = runner.prepare_inputs(config)
            actual_manifest = runner.summary.read_json(Path(
                next(a for a in entry["attempts"] if a["status"] == "complete")["manifest_path"]))
            if actual_manifest["input_hashes"] != expected_hashes:
                raise ValueError("completed input differs from current frozen input")
            entry["status"] = "complete"
            runner.write_json(state_path, state)
            continue
        if max_jobs is not None and executed >= max_jobs:
            break
        if runner.source_snapshot(ROOT)["sha256"] != source:
            raise ValueError("source changed during campaign")
        if shutil.disk_usage(root).free < plan["minimum_free_disk_bytes"]:
            raise ValueError("disk reserve reached; no raw data deleted")
        if len(entry["attempts"]) >= max_attempts:
            raise ValueError("retry budget exhausted: " + job["job_id"])
        entry["status"] = "running"
        state["updated_utc"] = stamp()
        runner.write_json(state_path, state)
        print("RUN {} attempt {}".format(job["job_id"], len(entry["attempts"]) + 1), flush=True)
        number = max([a["attempt"] for a in entry["attempts"]] or [0]) + 1
        record = _run_job(root, plan, job, number, cancellation, no_build=no_build)
        entry["attempts"].append(record)
        entry["status"] = record["status"]
        state["updated_utc"] = stamp()
        runner.write_json(state_path, state)
        executed += 1
        if record["status"] != "complete":
            raise ValueError("attempt preserved; campaign stopped: " + record.get("error", job["job_id"]))
        completed_attempt(entry["attempts"], job, source, model_sha)
        print("COMPLETE {}".format(job["job_id"]), flush=True)
    return state


def export_runs(root, split):
    """Return only verified results; never infer completion from an exit code."""
    root = Path(root).resolve()
    with (root / "plan/campaign.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _export_locked(root, split)


def _export_locked(root, split):
    plan = runner.summary.read_json(root / "plan/design.json")
    state = runner.summary.read_json(root / "plan" / ("state-" + split + ".json"))
    if state.get("execution_design_sha256") != execution_identity(plan, split):
        raise ValueError("cannot export old runs under a changed execution design")
    entries = []
    for job in jobs_for(plan, split):
        record = state["jobs"].get(job["job_id"], {})
        run = completed_attempt(record.get("attempts", []), job, plan["source_sha256"],
                                (plan["models"].get(job["scene"]) or {}).get("sha256"))
        if run is None:
            raise ValueError("required job is incomplete: " + job["job_id"])
        _, hashes = runner.prepare_inputs(prepare_job_input(root, plan, job))
        if runner.summary.read_json(run / "manifest.json")["input_hashes"] != hashes:
            raise ValueError("export input differs from frozen job input")
        entries.append(dict(job, path=str(run), manifest_sha256=digest(run / "manifest.json")))
    return entries


def freeze(root, phase, models, timeout):
    with (root / "plan/campaign.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = runner.summary.read_json(root / "plan/design.json")
        validate_sampling_plan(plan)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        for value in models:
            scene, filename = value.split("=", 1)
            if scene not in SCENES:
                raise ValueError("unknown model scene")
            path = Path(filename).expanduser().resolve()
            plan["models"][scene] = dict(path=str(path), sha256=digest(path))
        if phase == "formal" and set(plan["models"]) != set(SCENES):
            raise ValueError("three frozen scene models are required")
        plan["source_sha256"] = runner.source_snapshot(ROOT)["sha256"]
        if phase == "formal":
            import runpy
            import torch
            loader = runpy.run_path(str(ROOT / "scratch/vndn-circle-simulator/"
                                       "vndn-circle-tkan-gym.py"))["load_model"]
            for scene, record in plan["models"].items():
                try:
                    _, checkpoint, _ = loader(
                        Path(record["path"]), torch.device("cpu"), expected_scenario=scene,
                        require_formal=True, allow_validation_only=False)
                    if checkpoint["formal_contract"]["source_code_sha256"] != plan["source_sha256"]:
                        raise ValueError("model's training source differs from the frozen campaign")
                except Exception as error:
                    raise ValueError("formal model rejected for {}: {}".format(scene, error)) from error
        plan["status"] = phase + "-frozen"
        plan["timeouts"]["default"] = timeout
        for split in plan["seed_families"]:
            path = root / "plan" / ("state-" + split + ".json")
            if path.exists() and runner.summary.read_json(path).get(
                    "execution_design_sha256") != execution_identity(plan, split):
                raise ValueError("freeze would reinterpret existing " + split + " evidence")
        plan.setdefault("freeze_history", []).append(
            dict(phase=phase, utc=stamp(), source_sha256=plan["source_sha256"]))
        runner.write_json(root / "plan/design.json", plan)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "freeze", "run", "export", "append-sampling", "recover-sampling"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--duration", type=float,
                        help="measurement duration; defaults to 120 for quick-draft-v1, otherwise 300")
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--drain", type=float, default=3.5)
    parser.add_argument("--profile", choices=("full",) + SPARSE_PROFILES, default="full")
    parser.add_argument("--additions", type=Path, help="JSON list of explicit split/scene/condition_id/seed_family jobs")
    parser.add_argument("--reason", help="coverage deficiency that requires bounded sampling additions")
    parser.add_argument("--no-build", action="store_true", help="run existing binaries without invoking a build")
    parser.add_argument("--phase", choices=("pilot", "development", "formal"), default="pilot")
    parser.add_argument("--model", action="append", default=[], help="scene=/absolute/checkpoint.pt")
    parser.add_argument("--split", choices=("pilot", "train", "validation", "evaluation", "test"),
                        default="pilot")
    parser.add_argument("--scene", action="append", choices=SCENES)
    parser.add_argument("--condition", action="append")
    parser.add_argument("--seed", action="append", type=int)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.action == "init":
            initialize(root, make_plan(root.name, args.duration, args.warmup, args.drain, args.profile))
        elif args.action == "freeze":
            freeze(root, args.phase, args.model, args.timeout)
        elif args.action == "run":
            execute(root, args.split, scenes=args.scene, conditions=args.condition, seeds=args.seed,
                    max_jobs=args.max_jobs, max_attempts=args.max_attempts, no_build=args.no_build)
        elif args.action == "append-sampling":
            if not args.additions:
                raise ValueError("append-sampling requires --additions and --reason")
            append_sampling_jobs(root, json.loads(args.additions.read_text()), args.reason)
        elif args.action == "recover-sampling":
            recover_sampling_revision(root)
        else:
            entries = export_runs(root, args.split)
            path = root / "plan" / ("verified-" + args.split + "-runs.json")
            runner.write_json(path, {"schema_version": 1, "split": args.split, "runs": entries})
            print(path)
        return 0
    except (OSError, ValueError, KeyError) as error:
        print("campaign: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
