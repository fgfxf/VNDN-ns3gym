#!/usr/bin/env python3.8
"""Explicit, resumable post-sampling stages; never freezes or runs simulations.

Each command executes one stage. P2 must freeze the development campaign before
datasets/train. P4 must freeze all three selected models before evaluate/figures.
Training configuration is a JSON object of CLI argument names with underscores;
initialization_seeds is required and contains the three predeclared integers.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AI_ROOT = ROOT / "contrib/vndn-nn-rd/ai-training"
SCENES = ("circle", "grid", "spidermap")
SPLITS = ("train", "validation", "evaluation")
_CANCELLATION = None


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


campaign = _module("_workflow_campaign", HERE / "campaign.py")
read_json = campaign.runner.summary.read_json
write_json = campaign.runner.write_json
digest = campaign.digest


def _hash_object(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _source_sha256():
    return campaign.runner.source_snapshot(ROOT)["sha256"]


def _export_runs(root, split):
    return campaign.export_runs(root, split)


def _load_dataset_manifest(path):
    if str(AI_ROOT) not in sys.path:
        sys.path.insert(0, str(AI_ROOT))
    from formal_data import load_dataset_manifest
    return load_dataset_manifest(path)


def _check_file(path, expected):
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or digest(path) != expected:
        raise ValueError("missing file or hash changed: " + str(path))
    return path


def _validate_checkpoint(path, scene, dataset_sha, source_sha, validation_only):
    import torch
    controller = _module("_workflow_controller",
                         ROOT / "scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py")
    torch.set_num_threads(1)
    _, checkpoint, _ = controller.load_model(
        Path(path), torch.device("cpu"), expected_scenario=scene,
        require_formal=True, allow_validation_only=validation_only)
    contract = checkpoint["formal_contract"]
    if (contract["dataset_manifest_sha256"], contract["source_code_sha256"],
            contract["validation_only"]) != (dataset_sha, source_sha, validation_only):
        raise ValueError("checkpoint differs from frozen dataset/source/validation status")


def _process_token(pid):
    try:
        # Field 22, with the potentially space-containing parenthesized comm removed.
        fields = Path("/proc/{}/stat".format(pid)).read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _free_disk_bytes(root):
    return shutil.disk_usage(root).free


@contextmanager
def _signal_scope():
    """Signals set a flag; they cannot interrupt registration or child cleanup."""
    global _CANCELLATION
    if _CANCELLATION is not None or threading.current_thread() is not threading.main_thread():
        yield
        return
    _CANCELLATION = {"signal": None}
    def requested(signum, frame):
        _CANCELLATION["signal"] = signum
    previous = {signum: signal.signal(signum, requested)
                for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        _CANCELLATION = None


def _check_cancelled():
    if _CANCELLATION and _CANCELLATION["signal"] is not None:
        raise KeyboardInterrupt("workflow received signal {}".format(_CANCELLATION["signal"]))


def _run_command(command, log_path, timeout):
    """Wait for the real child exit code and clean only this owned process group."""
    with _signal_scope():
        _run_registered_command(command, log_path, timeout)


def _run_registered_command(command, log_path, timeout):
    _check_cancelled()
    launch_token = uuid.uuid4().hex
    environment = dict(os.environ, JOBS="4", OMP_NUM_THREADS="1",
                       OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                       NUMEXPR_NUM_THREADS="1", MPLBACKEND="Agg",
                       VNDN_WORKFLOW_CHILD_TOKEN=launch_token)
    # Durable intent before Popen permits orphan detection even after SIGKILL
    # between process creation and recording its PID.
    write_json(Path(log_path).with_suffix(".launch.json"), {"token": launch_token})
    with Path(log_path).open("wb") as log:
        started = time.monotonic()
        process = None
        metadata_path = Path(log_path).with_suffix(".process.json")
        metadata = {"command": command, "started_utc": campaign.stamp(),
                    "launch_token": launch_token}
        try:
            _check_cancelled()
            process = subprocess.Popen(command, cwd=str(ROOT), env=environment,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            metadata.update(pid=process.pid, start_token=_process_token(process.pid))
            write_json(metadata_path, metadata)
            while True:
                _check_cancelled()
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    code = process.wait(timeout=min(.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            _check_cancelled()
        except BaseException as error:
            metadata["error"] = "{}: {}".format(type(error).__name__, error)
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            raise
        finally:
            metadata.update(returncode=process.returncode if process is not None else None,
                            finished_utc=campaign.stamp(),
                            wall_seconds=time.monotonic() - started)
            write_json(metadata_path, metadata)
    if code != 0:
        raise RuntimeError("stage child exit {}: {} (log {})".format(
            code, command[1], log_path))


def _inventory(roots):
    result = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            if path.is_symlink():
                raise ValueError("stage artifacts must not contain symlinks: " + str(path))
            if path.is_file() and path.name not in ("attempt.json", "attempt.sha256"):
                result[str(path)] = digest(path)
    return result


def _write_sealed(path, record):
    payload = {key: value for key, value in record.items() if key != "_record_sha256"}
    write_json(path, dict(payload, _record_sha256=_hash_object(payload)))


def _save_attempt(folder, record):
    # One atomic rename publishes payload and checksum together.
    _write_sealed(folder / "attempt.json", record)


def _assert_no_live_children(folder):
    for process_path in folder.glob("*.process.json"):
        process = read_json(process_path)
        if process.get("start_token") is not None and \
                _process_token(process["pid"]) == process["start_token"]:
            raise ValueError("interrupted workflow still has a live owned child; inspect " +
                             str(process_path))
    tokens = [read_json(path)["token"] for path in folder.glob("*.launch.json")]
    if tokens:
        markers = [("VNDN_WORKFLOW_CHILD_TOKEN=" + token).encode() for token in tokens]
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or _process_token(int(entry.name)) is None:
                continue
            try:
                environment = (entry / "environ").read_bytes().split(b"\0")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if any(marker in environment for marker in markers):
                raise ValueError("interrupted workflow still has a live owned child: " + entry.name)


def _record(folder):
    path = folder / "attempt.json"
    if not path.is_file():
        _assert_no_live_children(folder)
        path = folder / "recovery.json"
        if not path.exists():
            _write_sealed(path, dict(
                schema_version=1, status="failed", identity=None,
                recovered_from_incomplete_attempt=True, finished_utc=campaign.stamp(),
                error="interrupted before atomic attempt record; original directory preserved"))
    value = read_json(path)
    expected = value.pop("_record_sha256", None)
    if expected != _hash_object(value):
        raise ValueError("attempt record hash changed: " + str(folder))
    if value.get("status") == "complete":
        if _inventory(value["artifact_roots"]) != value["artifact_sha256"]:
            raise ValueError("completed stage artifact hash changed: " + str(folder))
        for filename, expected in value["dependencies"].items():
            _check_file(filename, expected)
    return value


def _completed(root, stage, scene, plan):
    parent = root / "workflow" / stage / scene
    records = [(folder, _record(folder)) for folder in sorted(parent.glob("attempt-*"))]
    finished = [(path, record) for path, record in records if record["status"] == "complete"]
    if len(finished) > 1:
        raise ValueError("multiple complete attempts for " + stage + "/" + scene)
    if not finished:
        raise ValueError("required {} stage is incomplete for {}".format(stage, scene))
    if finished[0][1]["plan_basis"] != _plan_basis(plan, stage):
        raise ValueError("completed stage belongs to a changed campaign design")
    return finished[0][1]


def _dataset_product(path, scene, plan, source_specification=None):
    dataset = _load_dataset_manifest(path)
    if (dataset["scenario"], dataset["validation_only"], dataset["source_code_sha256"]) != (
            scene, plan["validation_only"], plan["source_sha256"]):
        raise ValueError("dataset scenario/source/validation status changed")
    sources = Path(dataset["source_specification"])
    _check_file(sources, dataset["source_specification_sha256"])
    specification = read_json(sources)
    if source_specification is not None and specification != source_specification:
        raise ValueError("dataset source specification differs from the complete exported runs")
    expected = sorted((row["path"], row["split"], row["seed_family"], row["manifest_sha256"])
                      for row in specification["runs"])
    actual = sorted((row["source_path"], row["split"], row["seed_family"],
                     row["source_manifest_sha256"]) for row in dataset["shards"])
    if actual != expected:
        raise ValueError("dataset shards do not cover every exported source run")
    return dataset


def _model_product(path, scene, plan, dataset_path, config):
    model = read_json(path)
    dataset_path = Path(dataset_path)
    if (model.get("schema_version"), model.get("scenario"), model.get("frozen"),
            model.get("validation_only"), model.get("evaluation_opened")) != (
                1, scene, True, plan["validation_only"], False):
        raise ValueError("invalid frozen training model manifest")
    if Path(model["dataset_manifest"]).resolve() != dataset_path.resolve():
        raise ValueError("model uses a different dataset")
    _check_file(dataset_path, model["dataset_manifest_sha256"])
    _dataset_product(dataset_path, scene, plan)
    checkpoint = _check_file(model["checkpoint_path"], model["checkpoint_sha256"])
    candidates = model["candidates"]
    seeds = [row["seed"] for row in candidates]
    if sorted(seeds) != sorted(config["initialization_seeds"]):
        raise ValueError("model must include all three predeclared initialization candidates")
    for row in candidates:
        _check_file(row["checkpoint_path"], row["checkpoint_sha256"])
        _check_file(row["history_path"], row["history_sha256"])
    chosen = [row for row in candidates if row["seed"] == model["selected_seed"]]
    if len(chosen) != 1 or chosen[0]["checkpoint_sha256"] != model["checkpoint_sha256"]:
        raise ValueError("selected model does not match its initialization candidate")
    _check_file(model["training_history"]["path"], model["training_history"]["sha256"])
    _validate_checkpoint(checkpoint, scene, model["dataset_manifest_sha256"],
                         plan["source_sha256"], plan["validation_only"])
    return model


def _evaluation_product(path, scene, plan, model_path):
    value, model = read_json(path), read_json(model_path)
    if (value.get("schema_version"), value.get("scenario"), value.get("split"),
            value.get("validation_only"), value.get("model_sha256"),
            value.get("dataset_manifest_sha256")) != (
                1, scene, "evaluation", plan["validation_only"], model["checkpoint_sha256"],
                model["dataset_manifest_sha256"]):
        raise ValueError("evaluation model/dataset/split differs from frozen stage")
    if Path(value["model_manifest"]).resolve() != Path(model_path).resolve():
        raise ValueError("evaluation uses a different model manifest")
    _check_file(model_path, value["model_manifest_sha256"])
    _check_file(Path(path).parent / "predictions.jsonl", value["prediction_file_sha256"])
    _check_file(value["training_history"]["path"], value["training_history"]["sha256"])
    if (value["bootstrap"]["repetitions"], value["bootstrap"]["analysis_seed"]) != (
            plan["bootstrap"]["resamples"], plan["bootstrap"]["seed"]):
        raise ValueError("evaluation bootstrap differs from frozen analysis plan")
    return value


def _figure_product(analysis, figures, manifest, plan):
    aggregate = read_json(analysis / "aggregate.json")
    index = read_json(figures / "figure-index.json")
    for value in (aggregate, index):
        if (value.get("schema_version"), value.get("status"), value.get("validation_only"),
                value.get("campaign_id")) != (
                    1, "complete", plan["validation_only"], plan["campaign_id"]):
            raise ValueError("analysis/figure stage did not report the expected complete campaign")
    if aggregate["campaign_sha256"] != digest(manifest):
        raise ValueError("analysis input manifest hash changed")
    if index["analysis_sha256"] != digest(analysis / "aggregate.json"):
        raise ValueError("figure analysis hash changed")
    items = index["figures"]
    if len(items) != 30 or len({item["id"] for item in items}) != 30:
        raise ValueError("exactly 30 numbered figures are required")
    for item in items + index["diagnostics"]:
        if set(item["files"]) != {"pdf", "svg", "png"}:
            raise ValueError("each figure requires actual PDF, SVG and PNG artifacts")
        for extension, filename in item["files"].items():
            path = (figures / filename).resolve()
            if figures.resolve() not in path.parents or path.stat().st_size == 0:
                raise ValueError("invalid or empty rendered figure")
            _check_file(path, item["sha256"][extension])


def _configuration(path):
    config = read_json(Path(path))
    defaults = dict(epochs=100, hidden_size=32, grid_size=5, spline_order=3, dropout=.1,
                    batch_size=256, learning_rate=.001, patience=15,
                    selection_tolerance=1e-10, threads=1, device="cpu")
    if set(config) - set(defaults) - {"initialization_seeds"}:
        raise ValueError("unknown training configuration fields")
    seeds = config.get("initialization_seeds", [])
    if (len(seeds) != 3 or len(set(seeds)) != 3 or
            any(type(seed) is not int or seed < 0 for seed in seeds)):
        raise ValueError("exactly three unique nonnegative initialization seeds are required")
    defaults.update(config)
    for key in ("epochs", "hidden_size", "grid_size", "spline_order", "batch_size",
                "patience", "threads"):
        if type(defaults[key]) is not int or defaults[key] < 1:
            raise ValueError("positive integer training configuration required: " + key)
    if defaults["threads"] > 4 or defaults["device"] != "cpu":
        raise ValueError("this campaign uses CPU training with at most four threads")
    for key in ("dropout", "learning_rate", "selection_tolerance"):
        if isinstance(defaults[key], bool) or not math.isfinite(defaults[key]):
            raise ValueError("finite training configuration required: " + key)
    if not 0 <= defaults["dropout"] < 1 or defaults["learning_rate"] <= 0 or \
            defaults["selection_tolerance"] < 0:
        raise ValueError("invalid dropout/learning rate/selection tolerance")
    return defaults


def _validated_exports(root, plan, split):
    rows = _export_runs(root, split)
    expected = {row["job_id"]: row for row in campaign.jobs_for(plan, split)}
    if len(expected) != len(campaign.jobs_for(plan, split)):
        raise ValueError("duplicate jobs in campaign plan")
    received, paths = set(), set()
    for row in rows:
        key = row["job_id"]
        if key in received or str(Path(row["path"]).resolve()) in paths:
            raise ValueError("duplicate exported run")
        received.add(key)
        paths.add(str(Path(row["path"]).resolve()))
        if key not in expected or any(row[k] != value for k, value in expected[key].items()):
            raise ValueError("exported job identity differs from frozen plan")
        _check_file(Path(row["path"]) / "manifest.json", row["manifest_sha256"])
    if received != set(expected):
        raise ValueError("complete split is required: " + split)
    return sorted(rows, key=lambda row: row["job_id"])


def _plan_basis(plan, stage):
    basis = dict(validation_only=plan["validation_only"],
                 development={split: campaign.execution_identity(plan, split) for split in SPLITS})
    if stage in ("evaluate", "figures"):
        basis.update(models=plan["models"], bootstrap=plan["bootstrap"])
    if stage == "figures":
        basis.update(test=campaign.execution_identity(plan, "test"),
                     time_bin_seconds=plan["time_bin_seconds"])
    return basis


def _check_plan(plan, stage, allow_validation_only):
    status = plan.get("status")
    if stage in ("evaluate", "figures") and status != "formal-frozen":
        raise ValueError(stage + " requires formal-frozen campaign models")
    if status not in ("development-frozen", "formal-frozen"):
        raise ValueError("development-frozen campaign is required")
    if type(plan.get("validation_only")) is not bool:
        raise ValueError("explicit validation_only status is required")
    if plan["validation_only"] and not allow_validation_only:
        raise ValueError("validation_only campaign requires explicit --allow-validation-only")
    if _source_sha256() != plan["source_sha256"]:
        raise ValueError("current source differs from frozen campaign")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", plan["campaign_id"]):
        raise ValueError("campaign_id must be a safe directory component")
    if (plan["bootstrap"].get("resamples") != 10000 or
            type(plan["bootstrap"].get("seed")) is not int or plan["bootstrap"]["seed"] < 0):
        raise ValueError("campaign bootstrap requires 10000 resamples and a fixed nonnegative seed")
    seen = set()
    for split, seeds in plan["seed_families"].items():
        if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
            raise ValueError("each split needs nonnegative integer seed families")
        if len(seeds) != len(set(seeds)) or seen.intersection(seeds):
            raise ValueError("seed family overlap within/across campaign splits")
        seen.update(seeds)


@contextmanager
def _lock(root):
    with (root / "plan/workflow.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _assert_unchanged(root, plan, stage, dependencies):
    _check_cancelled()
    now = read_json(root / "plan/design.json")
    if now["status"] != plan["status"] or _plan_basis(now, stage) != _plan_basis(plan, stage):
        raise ValueError("campaign design changed during workflow stage")
    if _source_sha256() != plan["source_sha256"]:
        raise ValueError("source changed during workflow stage")
    for path, expected in dependencies.items():
        _check_file(path, expected)


def _stage(root, stage, scene, plan, context, dependencies, action, verify):
    parent = root / "workflow" / stage / scene
    identity = _hash_object(dict(plan=_plan_basis(plan, stage), context=context,
                                 dependencies=dependencies))
    folders = sorted(parent.glob("attempt-*"))
    records = [(folder, _record(folder)) for folder in folders]
    if any(record["identity"] != identity and
           not record.get("recovered_from_incomplete_attempt") for _, record in records):
        raise ValueError("stage identity/config changed; use a separately declared campaign")
    finished = [(folder, row) for folder, row in records if row["status"] == "complete"]
    if len(finished) > 1:
        raise ValueError("duplicate completed workflow stages")
    if finished:
        record = finished[0][1]
        _assert_unchanged(root, plan, stage, dependencies)
        verify(record["products"])
        return record["products"]
    if stage in ("datasets", "train") and plan["status"] == "formal-frozen":
        raise ValueError("formal-frozen campaign cannot start new development work")
    if _free_disk_bytes(root) < plan.get("minimum_free_disk_bytes", 0):
        raise ValueError("campaign disk reserve reached; existing evidence preserved")
    for folder, record in records:
        if record["status"] == "running":
            _assert_no_live_children(folder)
            record.update(status="failed", error="interrupted attempt; products preserved",
                          finished_utc=campaign.stamp())
            _save_attempt(folder, record)
    number = max([int(folder.name.split("-")[-1]) for folder in folders] + [0]) + 1
    folder = parent / "attempt-{:03d}".format(number)
    folder.mkdir(parents=True, exist_ok=False)
    record = dict(schema_version=1, stage=stage, scene=scene, identity=identity,
                  plan_basis=_plan_basis(plan, stage),
                  context=context, dependencies=dependencies, status="running",
                  started_utc=campaign.stamp(), validation_only=plan["validation_only"])
    _save_attempt(folder, record)
    try:
        products, extra_roots = action(folder, number, identity)
        _assert_unchanged(root, plan, stage, dependencies)
        verify(products)
        roots = [str(folder)] + [str(path) for path in extra_roots]
        artifacts = _inventory(roots)
        _check_cancelled()
        record.update(products=products, artifact_roots=roots,
                      artifact_sha256=artifacts, status="complete",
                      finished_utc=campaign.stamp())
    except BaseException as error:
        record.update(status="failed", error="{}: {}".format(type(error).__name__, error),
                      finished_utc=campaign.stamp())
        _save_attempt(folder, record)
        raise
    _save_attempt(folder, record)
    return record["products"]


def execute(root, stage, scene=None, training_config=None, python=sys.executable,
            model_root=None, timeout=172800, allow_validation_only=False):
    """Execute one explicit stage, with immutable per-attempt evidence and logs."""
    if stage not in ("datasets", "train", "evaluate", "figures"):
        raise ValueError("unknown workflow stage")
    if scene is not None and scene not in SCENES:
        raise ValueError("unknown scenario")
    if stage == "figures" and scene is not None:
        raise ValueError("figures requires all three scenarios")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("positive finite stage timeout required")
    root = Path(root).expanduser().resolve()
    python = str(Path(python).expanduser().resolve())
    model_root = Path(model_root or ROOT / "data/models").expanduser().resolve()
    with _signal_scope(), _lock(root):
        _check_cancelled()
        plan = read_json(root / "plan/design.json")
        _check_plan(plan, stage, allow_validation_only)
        selected = (scene,) if scene else SCENES
        products = {}
        extra_flags = ["--allow-validation-only"] if plan["validation_only"] else []
        if stage == "datasets":
            exported = [row for split in SPLITS for row in _validated_exports(root, plan, split)]
            all_paths = [str(Path(row["path"]).resolve()) for row in exported]
            if len(all_paths) != len(set(all_paths)):
                raise ValueError("duplicate source paths across data splits")
            for current in selected:
                spec = dict(schema_version=1, scenario=current, validation_only=plan["validation_only"],
                            split_version=plan["campaign_id"] + "-" + _hash_object(
                                _plan_basis(plan, stage))[:16],
                            runs=[dict(path=row["path"], split=row["split"],
                                       seed_family=row["seed_family"], condition_id=row["condition_id"],
                                       manifest_sha256=row["manifest_sha256"])
                                  for row in exported if row["scene"] == current])
                dependencies = {str(Path(row["path"]) / "manifest.json"): row["manifest_sha256"]
                                for row in spec["runs"]}
                def build(folder, number, identity):
                    sources = folder / "sources.json"
                    write_json(sources, spec)
                    output = folder / "dataset"
                    command = [python, str(HERE / "build_training_dataset.py"),
                               "--sources", str(sources), "--output-dir", str(output)]
                    write_json(folder / "commands.json", [command])
                    _run_command(command, folder / "build.log", timeout)
                    return {"dataset_manifest": str(output / "dataset-manifest.json")}, []
                def verify(value):
                    _dataset_product(Path(value["dataset_manifest"]), current, plan, spec)
                products[current] = _stage(root, stage, current, plan, spec, dependencies, build, verify)
        elif stage == "train":
            if training_config is None:
                raise ValueError("train requires --training-config frozen before evaluation")
            training_config = Path(training_config).expanduser().resolve()
            config = _configuration(training_config)
            config_sha = digest(training_config)
            for current in selected:
                dataset_record = _completed(root, "datasets", current, plan)
                dataset = Path(dataset_record["products"]["dataset_manifest"])
                _dataset_product(dataset, current, plan)
                dependencies = {str(dataset): digest(dataset),
                                str(training_config): config_sha}
                context = dict(config=config, model_root=str(model_root))
                def train(folder, number, identity):
                    # Neither an old model nor a failed attempt is ever overwritten.
                    output = (model_root / current / "tkan-lstm" /
                              ("{}-{}-attempt-{:03d}".format(plan["campaign_id"], identity[:16], number)))
                    if output.exists():
                        raise FileExistsError("model attempt directory already exists: " + str(output))
                    output.mkdir(parents=True)
                    write_json(folder / "training-config.json", config)
                    command = [python, str(AI_ROOT / current / "train_tkan_lstm.py"),
                               "--dataset-manifest", str(dataset), "--output-root", str(output)]
                    for key, value in config.items():
                        command.append("--" + key.replace("_", "-"))
                        command.extend(str(item) for item in (value if isinstance(value, list) else [value]))
                    command.extend(extra_flags)
                    write_json(folder / "commands.json", [command])
                    _run_command(command, folder / "train.log", timeout)
                    manifests = list(output.glob("*/model-manifest.json"))
                    if len(manifests) != 1:
                        raise ValueError("training must produce exactly one timestamped model manifest")
                    model = read_json(manifests[0])
                    return dict(model_manifest=str(manifests[0]), checkpoint_path=model["checkpoint_path"],
                                checkpoint_sha256=model["checkpoint_sha256"],
                                training_config=config), [output]
                def verify(value):
                    _model_product(Path(value["model_manifest"]), current, plan, dataset, config)
                products[current] = _stage(root, stage, current, plan, context, dependencies, train, verify)
        else:
            if set(plan["models"]) != set(SCENES):
                raise ValueError("all three frozen campaign models are required")
            models = {}
            for current in SCENES:
                record = _completed(root, "train", current, plan)
                dataset = Path(_completed(root, "datasets", current, plan)["products"]["dataset_manifest"])
                path = Path(record["products"]["model_manifest"])
                model = _model_product(path, current, plan, dataset, record["products"]["training_config"])
                frozen = plan["models"][current]
                if Path(frozen["path"]).resolve() != Path(model["checkpoint_path"]).resolve() or \
                        frozen["sha256"] != model["checkpoint_sha256"]:
                    raise ValueError("selected model differs from formal frozen campaign model")
                _check_file(frozen["path"], frozen["sha256"])
                models[current] = path
            if stage == "evaluate":
                for current in selected:
                    model_path = models[current]
                    dependencies = {str(model_path): digest(model_path),
                                    plan["models"][current]["path"]: plan["models"][current]["sha256"]}
                    def evaluate(folder, number, identity):
                        output = folder / "evaluation"
                        command = [python, str(AI_ROOT / "formal_training.py"),
                                   "--model-manifest", str(model_path), "--output-dir", str(output),
                                   "--bootstrap-repetitions", str(plan["bootstrap"]["resamples"]),
                                   "--analysis-seed", str(plan["bootstrap"]["seed"])] + extra_flags
                        write_json(folder / "commands.json", [command])
                        _run_command(command, folder / "evaluate.log", timeout)
                        return {"evaluation": str(output / "evaluation.json")}, []
                    def verify(value):
                        _evaluation_product(Path(value["evaluation"]), current, plan, model_path)
                    products[current] = _stage(root, stage, current, plan, {}, dependencies, evaluate, verify)
            else:
                evaluations = {}
                for current in SCENES:
                    path = Path(_completed(root, "evaluate", current, plan)["products"]["evaluation"])
                    _evaluation_product(path, current, plan, models[current])
                    evaluations[current] = dict(path=str(path), sha256=digest(path))
                exported = _validated_exports(root, plan, "test")
                blocks = {}
                for row in exported:
                    key = row["block_id"]
                    block = blocks.setdefault(key, dict(
                        scene=row["scene"], condition_id=row["condition_id"],
                        seed_family=row["seed_family"], block_id=key, runs={}))
                    if str(row["strategy"]) in block["runs"]:
                        raise ValueError("duplicate test strategy in paired block")
                    block["runs"][str(row["strategy"])] = dict(
                        path=row["path"], manifest_sha256=row["manifest_sha256"])
                manifest = dict(schema_version=1, campaign_id=plan["campaign_id"],
                                validation_only=plan["validation_only"], source_sha256=plan["source_sha256"],
                                repetitions=plan["seed_families"]["test"], bootstrap=plan["bootstrap"],
                                conditions=plan["conditions"], baseline_condition_id=plan["baseline_condition_id"],
                                scans=plan["scans"], models=plan["models"], model_evaluations=evaluations,
                                blocks=[blocks[key] for key in sorted(blocks)],
                                time_bin_seconds=plan["time_bin_seconds"])
                dependencies = {str(Path(row["path"]) / "manifest.json"): row["manifest_sha256"]
                                for row in exported}
                dependencies.update({row["path"]: row["sha256"] for row in evaluations.values()})
                def figures(folder, number, identity):
                    source = folder / "campaign.json"
                    write_json(source, manifest)
                    analysis, images = folder / "analysis", folder / "figures"
                    commands = [[python, str(HERE / "aggregate_campaign.py"), str(source),
                                 "--output-dir", str(analysis)],
                                [python, str(HERE / "plot_campaign.py"), str(analysis),
                                 "--output-dir", str(images)]]
                    write_json(folder / "commands.json", commands)
                    for command, name in zip(commands, ("aggregate", "plot")):
                        _run_command(command, folder / (name + ".log"), timeout)
                    return dict(campaign_manifest=str(source), analysis=str(analysis),
                                figures=str(images)), []
                def verify(value):
                    _figure_product(Path(value["analysis"]), Path(value["figures"]),
                                    Path(value["campaign_manifest"]), plan)
                products["all"] = _stage(root, stage, "all", plan, manifest,
                                         dependencies, figures, verify)
        _check_cancelled()
        return dict(schema_version=1, status="complete", stage=stage,
                    validation_only=plan["validation_only"], products=products)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("datasets", "train", "evaluate", "figures"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scene", choices=SCENES)
    parser.add_argument("--training-config", type=Path)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=172800,
                        help="per child process wall-clock limit in seconds")
    parser.add_argument("--allow-validation-only", action="store_true")
    args = vars(parser.parse_args(argv))
    result = execute(**args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
