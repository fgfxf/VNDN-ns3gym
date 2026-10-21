#!/usr/bin/env python3.8
"""Prepare models, explicitly run formal experiments, or display live progress.

The prepare action never starts formal simulations; explicit all runs through
figures. All simulation commands use existing binaries; failed attempts are
preserved by campaign.py and never count as runs.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROFILE = "compact-exploratory-v1"
SCENES = ("circle", "grid", "spidermap")
SPLITS = ("train", "validation", "evaluation", "test")


def module(name):
    spec = importlib.util.spec_from_file_location("_pipeline_" + name, HERE / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


campaign = module("campaign")
read_json = campaign.runner.summary.read_json
write_json = campaign.runner.write_json


def read_plan(root):
    return read_json(Path(root) / "plan/design.json")


def planned_jobs(plan, split):
    return campaign.jobs_for(plan, split)


def is_live(record):
    pid, token = record.get("pid"), record.get("start_token")
    return bool(pid and token and campaign.process_identity(pid) == (pid, token))


def elapsed(start, end):
    return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def progress(root, now=None):
    """Read state only; a live process is never inferred from a stale JSON status."""
    root = Path(root)
    now = now or campaign.stamp()
    path = root / "plan/pipeline-state.json"
    state = read_json(path) if path.exists() else {"status": "not-started", "stage": None}
    plan = read_plan(root)
    alive = is_live(state)
    result = dict(status=state["status"], stage=state.get("stage"), process_alive=alive,
                  scene=state.get("current_scene"), updated_utc=state.get("updated_utc"),
                  error=state.get("error"), current_job=None)
    if result["status"] == "running" and not alive:
        result["status"] = "interrupted"
    result["elapsed_seconds"] = state.get("elapsed_seconds", 0)
    result["session_elapsed_seconds"] = state.get("session_elapsed_seconds", 0)
    if alive and state.get("started_utc"):
        result["session_elapsed_seconds"] = elapsed(state["started_utc"], now)
        result["elapsed_seconds"] = state.get("previous_elapsed_seconds", 0) + result["session_elapsed_seconds"]
    result["splits"] = {}
    offset = 0
    for split in SPLITS:
        jobs = planned_jobs(plan, split)
        path = root / "plan" / ("state-" + split + ".json")
        entries = read_json(path).get("jobs", {}) if path.exists() else {}
        count = sum(entries.get(job["job_id"], {}).get("status") == "complete" for job in jobs)
        result["splits"][split] = dict(completed=count, total=len(jobs), remaining=len(jobs) - count)
        for ordinal, job in enumerate(jobs, 1):
            entry = entries.get(job["job_id"], {})
            if alive and entry.get("status") == "running" and state.get("stage") == (
                    "test" if split == "test" else "sample-" + split):
                current = dict(job, ordinal=ordinal, total=len(jobs), split=split,
                               sampling_ordinal=None if split == "test" else offset + ordinal)
                folder = root / ("runs" if split == "test" else "sampling") / job["job_id"]
                attempts = sorted(folder.glob("attempt-*/attempt.json"))
                if attempts:
                    attempt = read_json(attempts[-1])
                    current["attempt"] = attempt["attempt"]
                    current["attempt_status"] = attempt.get("status")
                    if attempt.get("started_utc"):
                        current["elapsed_seconds"] = elapsed(attempt["started_utc"],
                            attempt.get("finished_utc", now))
                result["current_job"] = current
        if split != "test":
            offset += len(jobs)
    result["sampling"] = {key: sum(result["splits"][s][key] for s in SPLITS[:3])
                          for key in ("completed", "total", "remaining")}
    result["formal"] = result["splits"]["test"]
    return result


def completed_product(root, stage, scene):
    return module("campaign_workflow")._completed(Path(root), stage, scene, read_plan(root))


def audit_coverage(manifests, output):
    return module("training_coverage").audit_datasets(manifests, output)


def command(settings, tool, *args):
    return [settings["python"], str(HERE / (tool + ".py"))] + [str(x) for x in args]


def sample_command(root, settings, split):
    return command(settings, "campaign", "run", "--root", root, "--split", split,
                   "--no-build", "--max-attempts", 2)


def workflow_command(root, settings, stage, scene=None):
    value = command(settings, "campaign_workflow", stage, "--root", root,
                    "--python", settings["python"], "--timeout", settings["stage_timeout"])
    if scene:
        value.extend(["--scene", scene])
    if stage == "train":
        value.extend(["--training-config", settings["training_config"]])
    return value


def prepare_campaign(root, settings, step):
    """All transitions are explicit; there is no path to test or figures here."""
    if read_plan(root)["status"] != "formal-frozen":
        for split in SPLITS[:3]:
            step("sample-" + split, sample_command(root, settings, split))
        for scene in SCENES:
            step("datasets", workflow_command(root, settings, "datasets", scene), scene)
        manifests = {scene: completed_product(root, "datasets", scene)["products"]["dataset_manifest"]
                     for scene in SCENES}
        step("coverage")
        audit_coverage(manifests, Path(root) / "plan/training-coverage.json")
        for scene in SCENES:
            step("train", workflow_command(root, settings, "train", scene), scene)
        models = {scene: completed_product(root, "train", scene)["products"]["checkpoint_path"]
                  for scene in SCENES}
        freeze = command(settings, "campaign", "freeze", "--root", root, "--phase", "formal",
                         "--timeout", settings["run_timeout"])
        for scene, path in models.items():
            freeze.extend(["--model", scene + "=" + path])
        step("freeze-models", freeze)
    for scene in SCENES:
        step("evaluate", workflow_command(root, settings, "evaluate", scene), scene)
    return "ready-for-formal"


def source_files(snapshot):
    trace_root = ROOT / "contrib/vndn-nn-rd/traces"
    for relative in snapshot["scope"]:
        base = ROOT / relative
        if base.is_file():
            yield base
        elif base.is_dir():
            for directory, folders, names in os.walk(str(base)):
                folders[:] = sorted(x for x in folders if x not in (
                    ".git", "__pycache__", "build", "data", ".pytest_cache"))
                parent = Path(directory)
                trace = parent == trace_root or trace_root in parent.parents
                for name in sorted(names):
                    if name == "wscript" or Path(name).suffix in (
                            ".cc", ".cpp", ".c", ".h", ".hpp", ".py", ".sh") or (
                            trace and Path(name).suffix in snapshot["trace_configuration_suffixes"]):
                        yield parent / name


def seal_source(root):
    """Archive the same source scope hashed by every run before launching work."""
    snapshot = campaign.runner.source_snapshot(ROOT)
    if snapshot["sha256"] != read_plan(root)["source_sha256"]:
        raise ValueError("source differs from frozen design; refusing to resume")
    path = root / "plan/source-seal.json"
    if path.exists():
        record = read_json(path)
        if record["source"]["sha256"] != snapshot["sha256"] or campaign.digest(
                record["archive_path"]) != record["archive_sha256"]:
            raise ValueError("sealed source/archive changed")
        return
    archive = root / "plan/source.tar.gz"
    if archive.exists():
        raise ValueError("unsealed source archive exists; preserve it and inspect before retry")
    with tarfile.open(str(archive), "x:gz") as output:
        for filename in sorted(set(source_files(snapshot))):
            output.add(str(filename), arcname=str(filename.relative_to(ROOT)), recursive=False)
    if campaign.runner.source_snapshot(ROOT)["sha256"] != snapshot["sha256"]:
        raise ValueError("source changed while being archived")
    write_json(path, dict(schema_version=1, source=snapshot, created_utc=campaign.stamp(),
                         archive_path=str(archive), archive_sha256=campaign.digest(archive)))


def _stop_owned(process, owned):
    """Allow nested runners to reap sessions, then stop only observed identities."""
    identity = campaign.process_identity(process.pid)
    if identity:
        owned.add(identity)
        owned.update(campaign.descendants(process.pid))
        campaign.signal_owned(identity, signal.SIGTERM)
    started = time.monotonic()
    while process.poll() is None and time.monotonic() - started < 40:
        owned.update(campaign.descendants(process.pid))
        time.sleep(.1)
    # A child can have its own session; killing only the parent's group is insufficient.
    survivors = [item for item in owned if campaign.process_identity(item[0]) == item]
    for item in survivors:
        campaign.signal_owned(item, signal.SIGTERM)
    until = time.monotonic() + 5
    while survivors and time.monotonic() < until:
        time.sleep(.1)
        survivors = [item for item in survivors if campaign.process_identity(item[0]) == item]
    forced = []
    for item in reversed(survivors):
        if campaign.signal_owned(item, signal.SIGKILL):
            forced.append(item[0])
    process.wait(timeout=5)
    return dict(observed_pids=sorted(item[0] for item in owned), forced_pids=forced)


def run_command(command, log_path, cancellation, heartbeat):
    log_path = Path(log_path)
    token = uuid.uuid4().hex
    record = dict(command=command, started_utc=campaign.stamp(), launch_token=token)
    write_json(log_path.with_suffix(".launch.json"), {"token": token})
    process, owned = None, set()
    with log_path.open("wb") as log:
        try:
            if cancellation["signal"]:
                raise KeyboardInterrupt(cancellation["signal"])
            process = subprocess.Popen(command, cwd=str(ROOT), stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, JOBS="4", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                         OPENBLAS_NUM_THREADS="1", MPLBACKEND="Agg", VNDN_PIPELINE_TOKEN=token))
            identity = campaign.process_identity(process.pid)
            record.update(pid=process.pid, start_token=identity[1] if identity else None)
            write_json(log_path.with_suffix(".process.json"), record)
            while True:
                owned.update(campaign.descendants(process.pid))
                heartbeat(record)
                if cancellation["signal"]:
                    raise KeyboardInterrupt(cancellation["signal"])
                code = process.poll()
                if code is not None:
                    break
                time.sleep(.2)
            if code:
                raise RuntimeError("stage child exit {}: {}".format(code, log_path))
            remaining = [item for item in owned if campaign.process_identity(item[0]) == item]
            if remaining:
                raise RuntimeError("stage exited with live descendants; refusing continuation")
        except BaseException as error:
            record["error"] = "{}: {}".format(type(error).__name__, error)
            if process is not None:
                record["cleanup"] = _stop_owned(process, owned)
            raise
        finally:
            record.update(returncode=process.returncode if process is not None else None,
                          finished_utc=campaign.stamp())
            write_json(log_path.with_suffix(".process.json"), record)


def active_children(root):
    logs = root / "plan/pipeline-logs"
    records = [read_json(path) for path in logs.glob("*.process.json")]
    live = {row["pid"]: row for row in records if is_live(row)}
    # A durable launch token also covers SIGKILL between Popen and PID recording.
    tokens = {read_json(path)["token"] for path in logs.glob("*.launch.json")}
    markers = {("VNDN_PIPELINE_TOKEN=" + token).encode() for token in tokens}
    if markers:
        for directory in Path("/proc").iterdir():
            if not directory.name.isdigit():
                continue
            try:
                if not markers.intersection((directory / "environ").read_bytes().split(b"\0")):
                    continue
                identity = campaign.process_identity(int(directory.name))
                if identity:
                    live.setdefault(identity[0], dict(pid=identity[0], start_token=identity[1],
                                                     discovered_by="owned-launch-token"))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    return list(live.values())


def stage_heartbeat(root, state, save, clock=None):
    """Update the durable state and reassure a foreground user every 10 seconds."""
    clock = clock or time.monotonic
    last_save, last_display = [float("-inf")], [float("-inf")]
    def heartbeat(child):
        now = clock()
        if now - last_save[0] >= 2:
            state["child"] = child
            save()
            last_save[0] = now
        if now - last_display[0] >= 10:
            display(progress(root))
            last_display[0] = now
    return heartbeat


def execute(root, action, settings):
    if action not in ("prepare", "formal", "figures", "all"):
        raise ValueError("unknown pipeline action: " + action)
    root = Path(root).expanduser().resolve()
    (root / "plan").mkdir(parents=True, exist_ok=True)
    with (root / "plan/pipeline.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if active_children(root):
            raise ValueError("a previously started stage is still alive; use stop before resume")
        plan_path = root / "plan/design.json"
        if not plan_path.exists():
            if action not in ("prepare", "all"):
                raise ValueError("prepare the campaign first")
            campaign.initialize(root, campaign.make_plan(root.name,
                profile=settings.get("profile") or PROFILE))
        plan = read_plan(root)
        profile = plan.get("design_profile")
        if profile not in (PROFILE, campaign.QUICK_PROFILE):
            raise ValueError("this pipeline requires a supported exploratory profile")
        if settings.get("profile") and settings["profile"] != profile:
            raise ValueError("requested profile differs from the existing frozen design")
        if action in ("prepare", "all"):
            if not settings.get("training_config"):
                raise ValueError("prepare requires --training-config")
            config_path = Path(settings["training_config"]).expanduser().resolve()
            module("campaign_workflow")._configuration(config_path, profile=profile)
            sealed_config = root / "plan/training-config.json"
            value = read_json(config_path)
            if sealed_config.exists() and read_json(sealed_config) != value:
                raise ValueError("training configuration changed after preparation began")
            if not sealed_config.exists():
                write_json(sealed_config, value)
            settings = dict(settings, training_config=str(sealed_config))
            if plan["status"] == "candidate-unfrozen":
                campaign.freeze(root, "development", [], settings["run_timeout"])
            elif plan["timeouts"].get("default") != settings["run_timeout"]:
                raise ValueError("resume run timeout must match the frozen design")
        elif plan["status"] != "formal-frozen":
            raise ValueError("formal runs require the three prepared frozen models")
        seal_source(root)
        state_path = root / "plan/pipeline-state.json"
        previous = read_json(state_path) if state_path.exists() else {}
        state = dict(schema_version=1, pid=os.getpid(),
            start_token=campaign.process_identity(os.getpid())[1], action=action,
            status="running", stage="starting", started_utc=campaign.stamp(),
            previous_elapsed_seconds=previous.get("elapsed_seconds", 0),
            completed_stages=[], current_scene=None)
        started = time.monotonic()
        logs = root / "plan/pipeline-logs"
        logs.mkdir(exist_ok=True)
        def save():
            state["updated_utc"] = campaign.stamp()
            state["session_elapsed_seconds"] = time.monotonic() - started
            state["elapsed_seconds"] = state["previous_elapsed_seconds"] + state["session_elapsed_seconds"]
            write_json(state_path, state)
        with campaign.cancellation_signals() as cancellation:
            def step(stage, command=None, scene=None):
                if cancellation["signal"]:
                    raise KeyboardInterrupt(cancellation["signal"])
                state.update(stage=stage, current_scene=scene, child=None)
                save()
                print("STAGE {}{}".format(stage, " / " + scene if scene else ""), flush=True)
                if command:
                    path = logs / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f") +
                                   "-" + stage + ("-" + scene if scene else "") + ".log")
                    run_command(command, path, cancellation, stage_heartbeat(root, state, save))
                    state["completed_stages"].append(dict(stage=stage, scene=scene, log=str(path)))
                    save()
            try:
                if action in ("prepare", "all"):
                    state["status"] = prepare_campaign(root, settings, step)
                if action in ("formal", "all"):
                    # Validate the independent assessment before any final simulation.
                    for scene in SCENES:
                        completed_product(root, "evaluate", scene)
                    step("test", sample_command(root, settings, "test"))
                    state["status"] = "formal-complete"
                if action in ("figures", "all"):
                    step("figures", workflow_command(root, settings, "figures"))
                    state["status"] = "complete"
                state.update(stage=state["status"], child=None, current_scene=None)
                save()
                return state
            except BaseException as error:
                state.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                             error="{}: {}".format(type(error).__name__, error), child=None)
                save()
                raise


def stop(root):
    path = root / "plan/pipeline-state.json"
    state = read_json(path) if path.exists() else {}
    if is_live(state):
        campaign.signal_owned((state["pid"], state["start_token"]), signal.SIGTERM)
        until = time.monotonic() + 55
        while is_live(state) and time.monotonic() < until:
            time.sleep(.2)
        if is_live(state):
            raise RuntimeError("pipeline has not finished child cleanup; state and logs retained")
    children = active_children(root)
    if children:
        # The parent may have been killed. These identities came from this
        # campaign's sealed launch tokens; never signal by executable name.
        identities = {(row["pid"], row["start_token"]) for row in children}
        for identity in identities:
            campaign.signal_owned(identity, signal.SIGTERM)
        until = time.monotonic() + 40
        while identities and time.monotonic() < until:
            time.sleep(.2)
            identities = {identity for identity in identities
                          if campaign.process_identity(identity[0]) == identity}
        for identity in identities:
            campaign.signal_owned(identity, signal.SIGKILL)
        if active_children(root):
            raise RuntimeError("owned descendants have not exited; inspect pipeline-logs")
    return {"status": "stopped", "data_preserved": True}


def display(report):
    current = report.get("current_job")
    print("状态: {} | 阶段: {} | 本次已用: {:.1f} 分钟 | 累计已用: {:.1f} 分钟".format(
        report["status"], report["stage"], report["session_elapsed_seconds"] / 60,
        report["elapsed_seconds"] / 60))
    for name, key in (("采样", "sampling"), ("正式实验", "formal")):
        count = report[key]
        print("{}: {}/{} 完成，{} 剩余".format(name, count["completed"], count["total"], count["remaining"]))
    if current:
        print("当前: {scene} / 策略 {strategy} / {condition_id} / seed {seed_family} / "
              "本阶段第 {ordinal}/{total} 轮".format(**current))
        if "elapsed_seconds" in current:
            print("当前轮已用: {:.1f} 分钟".format(current["elapsed_seconds"] / 60))
    elif report.get("scene"):
        print("当前场景: " + report["scene"])
    if report.get("error"):
        print("错误: " + report["error"])
    print(flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "formal", "figures", "all", "status", "stop"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", choices=(PROFILE, campaign.QUICK_PROFILE))
    parser.add_argument("--training-config", type=Path)
    parser.add_argument("--run-timeout", type=float, default=1800)
    parser.add_argument("--stage-timeout", type=float, default=172800)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.action == "status":
            while True:
                report = progress(root)
                if args.json:
                    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
                else:
                    display(report)
                if not args.watch:
                    return 0
                time.sleep(5)
        if args.watch:
            raise ValueError("--watch applies only to status")
        if args.action == "stop":
            print(json.dumps(stop(root), ensure_ascii=False))
            return 0
        if any(not math.isfinite(value) or value <= 0 for value in (args.run_timeout, args.stage_timeout)):
            raise ValueError("timeouts must be finite and positive")
        result = execute(root, args.action, dict(profile=args.profile,
            training_config=str(args.training_config) if args.training_config else None,
            run_timeout=args.run_timeout, stage_timeout=args.stage_timeout, python=args.python))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print("pipeline: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
