#!/usr/bin/env python3.8
"""Run/resume the approved 99-run supplement using existing binaries and models.

Examples: followup_campaign.py all; followup_campaign.py status --watch;
followup_campaign.py stop. Complete runs are revalidated and never overwritten.
"""
import argparse
from collections import Counter
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "data/experiments/paper-figures-followup-20261026"
SCENES = ("circle", "grid", "spidermap")
SEEDS = (84001, 84002, 84003)
PERIODS = (20, 40, 80, 160)
STAGES = {"accuracy": "周期预测准确率", "online": "神经策略在线交付与成本", "state": "车辆数量与状态表规模"}


def module(name):
    spec = importlib.util.spec_from_file_location("_followup_" + name, Path(__file__).with_name(name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runner = module("run_experiment")
generator = module("generate_inputs")
read = runner.summary.read_json
sha = runner.summary.sha256_file


def sync_directory(path):
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write(path, value):
    """Commit progress only after its file and directory entry reach storage."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    sync_directory(path.parent)


def sync_files(paths):
    directories = set()
    for path in paths:
        path = Path(path)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        directories.add(path.parent)
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        sync_directory(directory)
        sync_directory(directory.parent)


def make_tasks():
    result = []
    for stage in STAGES:
        for scene in SCENES:
            conditions = [(10, period) for period in PERIODS] if stage != "state" else [(n, 20) for n in (5, 15, 20)]
            for vehicles, period in conditions:
                requests = vehicles * 600
                condition = "n{}-v30-k{}-hello{}".format(vehicles, requests, period)
                for seed in SEEDS:
                    identifier = "{}-{}-{}-s{}".format(stage, scene, condition, seed)
                    result.append(dict(id=identifier, scene=scene, scenario=scene, stage=stage,
                                       condition_id=condition, strategy=0 if stage == "accuracy" else 3,
                                       hello_interval_ms=period, rsu_timeout_ms=2 * period,
                                       obu_neighbor_timeout_ms=2000, vehicles=vehicles,
                                       speed_kmh=30, requests=requests, seed=seed, seed_family=seed,
                                       measurement_start_s=20, measurement_end_s=140, drain_end_s=143.5,
                                       training_snapshots=stage == "accuracy", resource_observations=True))
    return result


def input_key(task):
    return "{}/{}/s{}".format(task["scene"], task["condition_id"], task["seed_family"])


def process_identity(pid):
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else (int(pid), fields[19])
    except (OSError, ValueError, IndexError):
        return None


def clean_binary(evidence):
    return {key: value for key, value in evidence.items() if key != "captured"}


def bind_models(source_root):
    """Check historical training provenance without pretending runtime source matches it."""
    source_root = Path(source_root).resolve()
    design_path = source_root / "plan/design.json"
    design = read(design_path)
    if design.get("status") != "formal-frozen" or design.get("validation_only") is not False:
        raise ValueError("Historical model source must be frozen non-validation evidence")
    models = design.get("models", {})
    if set(models) != set(SCENES):
        raise ValueError("Exactly three historical models are required")
    dependencies = {str(design_path): sha(design_path)}
    provenance = {}
    loader = module("fixed_models")
    for scene in SCENES:
        model = models[scene]
        path = Path(model["path"]).resolve()
        runner.verify_hashes({str(path): model["sha256"]}, "Historical model")
        manifest_path = path.parent / "model-manifest.json"
        manifest = read(manifest_path)
        if (manifest.get("scenario") != scene or manifest.get("frozen") is not True or
                manifest.get("validation_only") is not False or
                Path(manifest["checkpoint_path"]).resolve() != path or
                manifest.get("checkpoint_sha256") != model["sha256"]):
            raise ValueError("Historical model manifest differs: " + scene)
        dataset_path = Path(manifest["dataset_manifest"]).resolve()
        runner.verify_hashes({str(dataset_path): manifest["dataset_manifest_sha256"]}, "Training dataset")
        dataset = read(dataset_path)
        specification = Path(dataset["source_specification"]).resolve()
        runner.verify_hashes({str(specification): dataset["source_specification_sha256"]}, "Training source specification")
        checkpoint = loader.load_checkpoint(path, scene)
        contract = checkpoint["formal_contract"]
        if (dataset.get("scenario") != scene or dataset.get("validation_only") is not False or
                contract["source_code_sha256"] != design["source_sha256"] or
                dataset["source_code_sha256"] != design["source_sha256"] or
                contract["dataset_manifest_sha256"] != manifest["dataset_manifest_sha256"] or
                any(contract[k] != dataset[k] for k in ("observation_contract", "label_contract", "split_version")) or
                checkpoint["feature_names"] != dataset["feature_names"] or
                checkpoint["label_values"] != dataset["label_values"] or
                checkpoint["model_parameters"]["sequence_length"] != dataset["sequence_length"]):
            raise ValueError("Historical model input/target contract differs: " + scene)
        prior_seeds = set()
        for split in dataset["splits"].values():
            prior_seeds.update(split["seed_families"])
        if prior_seeds.intersection(SEEDS):
            raise ValueError("Supplement seeds overlap model development data: " + scene)
        for artifact in (path, manifest_path, dataset_path, specification):
            dependencies[str(artifact)] = sha(artifact)
        provenance[scene] = dict(model_manifest=str(manifest_path), dataset_manifest=str(dataset_path),
                                 training_source_sha256=design["source_sha256"], formal_contract=contract,
                                 excluded_development_seeds=sorted(prior_seeds))
    return models, dependencies, provenance


def initialize(root, timeout):
    plan_path = root / "plan/followup-manifest.json"
    if plan_path.is_file():
        expected = (root / "plan/followup-manifest.sha256").read_text().strip()
        if sha(plan_path) != expected:
            raise ValueError("Frozen follow-up manifest hash changed")
        plan = read(plan_path)
        if plan["run_timeout_seconds"] != timeout:
            raise ValueError("Run timeout differs from the frozen plan")
        return plan
    tasks = make_tasks()
    model_source = ROOT / "data/experiments/retrain-quick-20261021"
    models, dependencies, provenance = bind_models(model_source)
    source = runner.source_snapshot(ROOT)
    binaries = {scene: runner.binary_evidence(ROOT, "vndn-" + scene + "-simulator") for scene in SCENES}
    inputs = {}
    for task in tasks:
        key = input_key(task)
        if key not in inputs:
            directory = root / "inputs" / key
            config = directory / "experiment-template.json"
            if not config.exists():
                generator.generate_inputs(scenario=task["scene"], output_dir=directory,
                                          vehicles=task["vehicles"], speed_kmh=30, requests=task["requests"],
                                          measurement_start=20, measurement_duration=120, drain_seconds=3.5,
                                          seed=task["seed_family"], ns3_root=ROOT,
                                          hello_interval_ms=task["hello_interval_ms"], resource_observations=True)
            template, hashes = runner.prepare_inputs(config)
            # A partially initialized directory is never silently repurposed.
            info = read(directory / "input-summary.json")
            if (template.get("hello_interval_ms") != task["hello_interval_ms"] or
                    template.get("resource_observations") is not True or info["seed"] != task["seed_family"] or
                    info["requested_count"] != task["requests"] or len(info["vehicles"]) != task["vehicles"]):
                raise ValueError("Existing input does not match follow-up task: " + key)
            inputs[key] = (str(config), hashes)
            sync_files(hashes)
        task["config_path"], task["input_hashes"] = inputs[key]
    plan = dict(schema_version=1, campaign_id=root.name, created_utc=runner.utc_now(),
                design="fixed-model-beacon-and-resource-supplement-v1", tasks=tasks,
                periods_ms=list(PERIODS), seed_families=list(SEEDS), total=99,
                old_campaign_root=str(ROOT / "data/experiments/quick-fixed-model-20261022"),
                model_source_root=str(model_source), models=models, model_provenance=provenance,
                dependencies=dependencies, source=source, binaries=binaries,
                run_timeout_seconds=timeout, max_attempts=2,
                seed_policy="new paired seeds; fixed historical models; no retraining",
                execution_mode="existing-binary")
    write(plan_path, plan)
    (root / "plan/followup-manifest.sha256").write_text(sha(plan_path) + "\n")
    sync_files([root / "plan/followup-manifest.sha256"])
    return plan


def verify_runtime(plan):
    if runner.source_snapshot(ROOT)["sha256"] != plan["source"]["sha256"]:
        raise ValueError("Source changed after follow-up freeze; do not mix versions")
    runner.verify_hashes(plan["dependencies"], "Frozen historical model provenance")
    for scene in SCENES:
        actual = runner.binary_evidence(ROOT, "vndn-" + scene + "-simulator")
        if clean_binary(actual) != clean_binary(plan["binaries"][scene]):
            raise ValueError("Simulator or shared dependencies changed: " + scene)


def verify_completed(record, task, plan):
    run = Path(record["run_dir"]).resolve()
    path = run / "manifest.json"
    if sha(path) != record["manifest_sha256"]:
        raise ValueError("Completed run manifest hash changed: " + task["id"])
    manifest = runner.summary.validate_manifest(run)
    if (manifest.get("status") != "complete" or manifest.get("block_id") != task["id"] or
            manifest.get("scenario") != task["scene"] or manifest.get("strategy") != task["strategy"] or
            manifest.get("source", {}).get("sha256") != plan["source"]["sha256"] or
            manifest.get("validation_only") is not False or
            manifest.get("execution_mode") != "existing-binary" or
            manifest.get("input_hashes") != task["input_hashes"]):
        raise ValueError("Completed run identity differs from frozen task: " + task["id"])
    if task["strategy"] == 3 and manifest.get("model") != plan["models"][task["scene"]]:
        raise ValueError("Completed run model differs from frozen model")
    if clean_binary(manifest["binary"]) != clean_binary(plan["binaries"][task["scene"]]):
        raise ValueError("Completed run binary differs from frozen binary")
    runner.verify_hashes(task["input_hashes"], "Completed run inputs")
    config = read(run / "experiment.json")
    if (config.get("hello_interval_ms") != task["hello_interval_ms"] or
            config.get("resource_observations") is not True or
            config.get("training_snapshots") != task["training_snapshots"]):
        raise ValueError("Completed run deployment or recording configuration differs")
    return run


def task_record(root, task):
    return root / "plan/tasks" / (task["id"] + ".json")


def recover_completed(root, task, plan):
    path = task_record(root, task)
    if path.is_file() and read(path).get("status") == "complete":
        record = read(path)
        verify_completed(record, task, plan)
        return record
    candidates = []
    for manifest_path in sorted((root / "runs" / task["id"]).glob("attempt-*/*/manifest.json")):
        manifest = read(manifest_path)
        if manifest.get("status") == "complete":
            candidates.append(dict(status="complete", task_id=task["id"], run_dir=str(manifest_path.parent),
                                   path=str(manifest_path.parent), manifest_sha256=sha(manifest_path),
                                   artifact_hashes=manifest["artifact_hashes"]))
    if len(candidates) > 1:
        raise ValueError("Multiple completed attempts for one task")
    if candidates:
        run = verify_completed(candidates[0], task, plan)
        manifest = read(run / "manifest.json")
        sync_files([run / name for name in manifest["artifact_hashes"]] + [run / "manifest.json"])
        sync_directory(run.parent.parent)
        write(path, candidates[0])
        return candidates[0]
    return None


def next_attempt(root, task):
    directories = sorted((root / "runs" / task["id"]).glob("attempt-*"))
    number = max([int(path.name.split("-")[-1]) for path in directories] + [0]) + 1
    if number > 2:
        raise ValueError("Task has exhausted its 2 attempts; preserve failures for diagnosis: " + task["id"])
    return number


def format_status(state, plan):
    completed = state.get("completed", 0)
    total = len(plan.get("tasks", [])) or 99
    lines = ["状态: {} | 阶段: {} | 本次已用: {:.1f} 分钟 | 累计已用: {:.1f} 分钟".format(
        state.get("status", "not-started"), STAGES.get(state.get("stage"), state.get("stage", "准备")),
        state.get("session_elapsed_seconds", 0) / 60, state.get("cumulative_elapsed_seconds", 0) / 60),
        "完整补充实验: {}/{} 完成，{} 剩余".format(completed, total, total - completed)]
    counts = state.get("stage_completed", {})
    for stage, label in STAGES.items():
        lines.append("{}: {}/{}".format(label, counts.get(stage, 0), 27 if stage == "state" else 36))
    task = state.get("current_task")
    if task:
        lines.append("当前: {} | 策略 {} | 周期 {} ms | {} 车 | seed {} | 当前轮已用 {:.1f} 分钟".format(
            task["scene"], task["strategy"], task["hello_interval_ms"], task["vehicles"], task["seed_family"],
            state.get("current_elapsed_seconds", 0) / 60))
    if state.get("analysis"):
        analysis = state["analysis"]
        lines.append("分析出图: {} | {} | {}/{}".format(analysis.get("stage", ""),
                     analysis.get("current", analysis.get("current_scene", "")),
                     analysis.get("completed", "?"), analysis.get("total", "?")))
    if state.get("error"):
        lines.append("说明: " + state["error"])
    return "\n".join(lines)


def request_stop(root):
    state_path = root / "plan/followup-state.json"
    if not state_path.is_file():
        return False
    state = read(state_path)
    identity = (state.get("pid"), state.get("start_token"))
    if identity[0] is None or process_identity(identity[0]) != identity:
        return False
    os.kill(identity[0], signal.SIGTERM)
    return True


def show_status(root, watch=False):
    while True:
        state_path = root / "plan/followup-state.json"
        plan_path = root / "plan/followup-manifest.json"
        state = read(state_path) if state_path.is_file() else {"status": "not-started"}
        plan = read(plan_path) if plan_path.is_file() else {"tasks": make_tasks()}
        if state.get("status") in ("running", "initializing") and process_identity(state.get("pid")) != (
                state.get("pid"), state.get("start_token")):
            state.update(status="interrupted", error="进程已退出；运行 resume 可验证并复用已完成轮次。")
        if state.get("stage") == "analysis" and (root / "analysis/status.json").is_file():
            state["analysis"] = read(root / "analysis/status.json")
        print(format_status(state, plan), flush=True)
        if not watch or state.get("status") not in ("running", "initializing"):
            return 0
        time.sleep(5)
        print(flush=True)


def execute(root, timeout=900, max_runs=None):
    root = Path(root).expanduser().resolve()
    if ROOT / "data/experiments" not in root.parents:
        raise ValueError("Follow-up root must be under data/experiments")
    if root in (ROOT / "data/experiments/retrain-quick-20261021",
                ROOT / "data/experiments/quick-fixed-model-20261022"):
        raise ValueError("Refusing to write into a historical campaign")
    (root / "plan/tasks").mkdir(parents=True, exist_ok=True)
    with (root / "plan/followup.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This follow-up campaign is already running")
        state_path = root / "plan/followup-state.json"
        previous_state = read(state_path) if state_path.is_file() else {}
        accumulated = previous_state.get("cumulative_elapsed_seconds", 0)
        started, heartbeat = time.monotonic(), [0]
        cancelled, previous_handlers = [], {}
        identity = process_identity(os.getpid())
        state = dict(schema_version=1, status="initializing", stage="prepare", pid=os.getpid(),
                     start_token=identity[1], started_utc=runner.utc_now(), completed=0,
                     stage_completed={}, current_task=None, session_elapsed_seconds=0,
                     cumulative_elapsed_seconds=accumulated)
        plan = {"tasks": make_tasks()}
        current_start = [None]

        def update(force=False):
            now = time.monotonic()
            if force or now - heartbeat[0] >= 5:
                state.update(session_elapsed_seconds=now - started,
                             cumulative_elapsed_seconds=accumulated + now - started,
                             current_elapsed_seconds=0 if current_start[0] is None else now - current_start[0],
                             updated_utc=runner.utc_now())
                write(state_path, state)
                print(format_status(state, plan), flush=True)
                heartbeat[0] = now

        def check_cancelled():
            update()
            if cancelled:
                raise KeyboardInterrupt("立即停止：当前轮保留，下次重跑；已完成轮次不丢失")

        def stop(signum, frame):
            if not cancelled:
                cancelled.append(signum)

        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, stop)
        update(True)
        try:
            plan = initialize(root, timeout)
            verify_runtime(plan)
            state.update(status="running", stage="verify")
            completed = set()
            for task in plan["tasks"]:
                check_cancelled()
                if recover_completed(root, task, plan):
                    completed.add(task["id"])
            state["stage_completed"] = dict(Counter(t["stage"] for t in plan["tasks"] if t["id"] in completed))
            state["completed"] = len(completed)
            executed = 0
            for task in plan["tasks"]:
                if task["id"] in completed:
                    continue
                if max_runs is not None and executed >= max_runs:
                    state.update(status="paused", current_task=None)
                    update(True)
                    return 0
                state.update(stage=task["stage"], current_task=task)
                while True:
                    check_cancelled()
                    verify_runtime(plan)
                    number = next_attempt(root, task)
                    attempt = root / "runs" / task["id"] / "attempt-{:03d}".format(number)
                    attempt.mkdir(parents=True, exist_ok=False)
                    current_start[0] = time.monotonic()
                    update(True)
                    args = ["--config", task["config_path"], "--output-root", str(attempt),
                            "--block-id", task["id"], "--strategy", str(task["strategy"]),
                            "--no-build", "--require-formal-contract", "--python", sys.executable,
                            "--timeout", str(timeout)]
                    if task["training_snapshots"]:
                        args.append("--training-snapshots")
                    if task["strategy"] == 3:
                        args += ["--model-file", plan["models"][task["scene"]]["path"]]
                    code = runner._run_block(args, ROOT, check_cancelled)
                    check_cancelled()
                    record = recover_completed(root, task, plan)
                    if code == 0 and record is not None:
                        completed.add(task["id"])
                        executed += 1
                        state["completed"] = len(completed)
                        state["stage_completed"][task["stage"]] = state["stage_completed"].get(task["stage"], 0) + 1
                        current_start[0] = None
                        update(True)
                        break
                    write(attempt / "attempt-status.json", dict(status="failed", exit_code=code,
                                                               finished_utc=runner.utc_now()))
                    if number == 2:
                        raise ValueError("Task failed both attempts: " + task["id"])
            state.update(stage="analysis", current_task=None)
            current_start[0] = None
            update(True)
            log_path = root / "plan/analysis.log"
            with log_path.open("a") as log:
                environment = os.environ.copy()
                environment.update(JOBS="4", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
                process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("followup_analysis.py")),
                                            "--root", str(root)], cwd=str(ROOT), env=environment,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    while process.poll() is None:
                        check_cancelled()
                        status_path = root / "analysis/status.json"
                        if status_path.is_file():
                            state["analysis"] = read(status_path)
                        time.sleep(.2)
                    if process.returncode != 0:
                        raise ValueError("Analysis failed; all 99 completed runs remain reusable. See " + str(log_path))
                finally:
                    if process.poll() is None:
                        runner.stop_group(process)
            analysis = read(root / "analysis/summary.json")
            final_status = read(root / "analysis/status.json")
            if (analysis.get("status") != "complete" or final_status.get("status") != "complete" or
                    analysis.get("counts") != {"accuracy": 36, "online": 63, "cpu_processes": 15} or
                    not (root / "figures/index.html").is_file()):
                raise ValueError("Analysis exit succeeded but required completion artifacts are missing")
            artifacts = analysis.get("artifact_hashes", {})
            if "figures/index.html" not in artifacts:
                raise ValueError("Analysis summary did not seal the figure index")
            for relative, digest in artifacts.items():
                artifact = (root / relative).resolve()
                if root not in artifact.parents or not artifact.is_file() or sha(artifact) != digest:
                    raise ValueError("Analysis artifact hash mismatch: " + relative)
            state.update(status="complete", stage="complete", figures=str(root / "figures/index.html"))
            update(True)
            return 0
        except KeyboardInterrupt as error:
            state.update(status="interrupted", error=str(error))
            update(True)
            return 130
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            state.update(status="failed", error=str(error))
            update(True)
            return 1
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("all", "resume", "status", "stop"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--run-timeout", type=float, default=900)
    parser.add_argument("--max-runs", type=int)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.action == "status":
            return show_status(root, args.watch)
        if args.action == "stop":
            print("已发送立即停止请求。" if request_stop(root) else "没有匹配的运行进程；未发送信号。")
            return 0
        if not math.isfinite(args.run_timeout) or args.run_timeout <= 0 or args.max_runs is not None and args.max_runs <= 0:
            raise ValueError("timeout/max-runs must be positive")
        os.environ.update(JOBS="4", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        return execute(root, args.run_timeout, args.max_runs)
    except (OSError, ValueError, KeyError) as error:
        print("followup: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
