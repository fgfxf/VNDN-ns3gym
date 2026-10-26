#!/usr/bin/env python3.8
"""Run one serial comparison block; never configure, train, or overwrite old data.

The input template defines one fixed seed tuple and request/mobility input.
Repeat this command with a separately generated input/seed block for independent
replications. A zero process exit alone never certifies a valid experiment.
"""
import argparse
import ast
import csv
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import uuid
from xml.etree import ElementTree


_SPEC = importlib.util.spec_from_file_location(
    "_vndn_experiment_summary", Path(__file__).with_name("summarize.py"))
summary = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summary)
ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ("circle", "grid", "spidermap")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    temporary.replace(path)


def source_snapshot(root):
    """Hash code and trace configuration dependencies; never dump diffs."""
    import hashlib
    roots = ("scratch", "contrib/vndn-nn-rd", "src/ndnSIM", "tools/experiments",
             "wscript", "waf")
    trace_root = root / "contrib/vndn-nn-rd/traces"
    trace_suffixes = (".xml", ".sumocfg", ".cfg")
    files = []
    for relative in roots:
        path = root / relative
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for directory, folders, names in os.walk(str(path)):
                folders[:] = sorted(x for x in folders if x not in (
                    ".git", "__pycache__", "build", "data", ".pytest_cache"))
                current = Path(directory)
                trace_configuration = current == trace_root or trace_root in current.parents
                files.extend(Path(directory) / name for name in sorted(names)
                             if name == "wscript" or Path(name).suffix in (
                                 ".cc", ".cpp", ".c", ".h", ".hpp", ".py", ".sh") or (
                                 trace_configuration and Path(name).suffix in trace_suffixes))
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        digest.update(str(path.relative_to(root)).encode("utf-8") + b"\0")
        digest.update(summary.sha256_file(path).encode("ascii") + b"\n")
    result = {"sha256": digest.hexdigest(), "file_count": len(set(files)),
              "scope": list(roots), "git_revision": None, "git_diff_sha256": None,
              "trace_configuration_suffixes": list(trace_suffixes)}
    try:
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        diff = subprocess.run(["git", "-C", str(root), "diff", "--binary", "HEAD", "--", "."],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        result.update(git_revision=revision.stdout.decode().strip(),
                      git_diff_sha256=hashlib.sha256(diff.stdout).hexdigest())
    except (OSError, subprocess.CalledProcessError):
        pass
    return result


def prepare_inputs(config_path):
    config_path = config_path.expanduser().resolve()
    template = summary.read_json(config_path)
    if template.get("schema_version") != 1 or template.get("scenario") not in SCENARIOS:
        raise ValueError("Unsupported experiment schema/scenario")
    for field in ("training_snapshots", "validation_only", "require_formal_contract",
                  "resource_observations"):
        if field in template and type(template[field]) is not bool:
            raise ValueError(field + " must be a JSON boolean")
    if "hello_interval_ms" in template and (
            type(template["hello_interval_ms"]) is not int or
            not 1 <= template["hello_interval_ms"] <= 2147483647):
        raise ValueError("hello_interval_ms must be an integer in [1, 2147483647]")
    if not isinstance(template.get("seeds"), dict):
        raise ValueError("Missing explicit seed tuple")
    for key in ("rng_seed", "rng_run", "sumo_seed", "srand_seed"):
        template["seeds"][key] = summary.integer(template["seeds"].get(key), key)
    start, end, drain = (summary.seconds_ns(template.get(key)) for key in (
        "measurement_start_s", "measurement_end_s", "drain_end_s"))
    if not (0 <= start < end and drain >= end + 3000000000):
        raise ValueError("Invalid measurement/drain interval")
    files = {config_path}
    for key in ("sumo_config", "route_file", "request_plan"):
        path = Path(template[key])
        if not path.is_absolute():
            path = config_path.parent / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError("Missing frozen input: " + str(path))
        template[key] = str(path)
        files.add(path)
    if not isinstance(template.get("input_files"), list) or not template["input_files"]:
        raise ValueError("input_files must list the complete frozen input bundle")
    resolved_files = []
    for filename in template["input_files"]:
        path = Path(filename)
        if not path.is_absolute():
            path = config_path.parent / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError("Missing declared input: " + str(path))
        resolved_files.append(str(path))
        files.add(path)
    template["input_files"] = resolved_files
    # Hash the files SUMO actually names, not merely a user-supplied subset.
    sumo_path = Path(template["sumo_config"])
    try:
        document = ElementTree.parse(str(sumo_path))
    except ElementTree.ParseError as error:
        raise ValueError("Invalid SUMO config: " + str(error))
    input_element = document.getroot().find("input")
    if input_element is None or input_element.find("net-file") is None or (
            input_element.find("route-files") is None):
        raise ValueError("SUMO config must identify its network and route files")
    required = {Path(template[key]) for key in ("sumo_config", "route_file", "request_plan")}
    route_references = []
    for item in input_element:
        if item.tag == "include":
            raise ValueError("SUMO XML includes require an explicitly flattened input bundle")
        if item.tag.endswith(("-file", "-files")):
            values = item.attrib.get("value", "").split(",")
            if not values or any(not value.strip() for value in values):
                raise ValueError("Empty SUMO file reference: " + item.tag)
            resolved = [(sumo_path.parent / value.strip()).resolve() for value in values]
            required.update(resolved)
            if item.tag == "route-files":
                route_references = resolved
    if route_references != [Path(template["route_file"])]:
        raise ValueError("SUMO must use the declared single route_file")
    if not required.issubset({Path(path) for path in resolved_files}):
        raise ValueError("input_files omits files actually referenced by SUMO/config")
    return template, {str(path): summary.sha256_file(path) for path in sorted(files)}


def verify_hashes(mapping, label):
    for filename, digest in mapping.items():
        path = Path(filename)
        if not path.is_file() or summary.sha256_file(path) != digest:
            raise ValueError(label + " changed during the block: " + filename)


def stop_group(process):
    """Reap the leader and stop only descendants in our own new process group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=.5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_processes(commands, root, run, timeout, check_cancelled=lambda: None):
    processes, handles, records = {}, {}, {}
    environment = os.environ.copy()
    environment.update(JOBS="4", VNDN_EXPERIMENT_RUN_DIR=str(run))
    # Shared simulation ports are protected by the project-level runner lock.
    started = time.monotonic()
    error = None
    try:
        for name, command in commands:
            check_cancelled()
            handles[name] = (run / (name + ".log")).open("w", encoding="utf-8")
            records[name] = {"command": command, "returncode": None, "cwd": str(root),
                             "log": name + ".log", "JOBS": "4"}
            handles[name].write("JOBS=4\ncommand: " + shlex.join(command) + "\n\n")
            handles[name].flush()
            processes[name] = subprocess.Popen(
                command, cwd=str(root), env=environment, stdout=handles[name],
                stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            check_cancelled()
            for name, process in processes.items():
                code = process.poll()
                records[name]["returncode"] = code
                if code is not None and code != 0:
                    raise RuntimeError("{} exited with {}".format(name, code))
            # Use the statuses checked above. A second poll could observe a
            # newly failed child and break without checking its exit code.
            if all(record["returncode"] is not None for record in records.values()):
                break
            if time.monotonic() - started > timeout:
                raise RuntimeError("Experiment process timeout after {} s".format(timeout))
            time.sleep(.02)
    except (OSError, RuntimeError, KeyboardInterrupt) as caught:
        error = str(caught) or "Interrupted"
    finally:
        for name, process in processes.items():
            # Also clean any descendants when the leader has already exited.
            stop_group(process)
            records[name]["returncode"] = process.returncode
        for handle in handles.values():
            handle.close()
    if error is None:
        for name, record in records.items():
            if record["returncode"] != 0:
                error = "{} exited with {}".format(name, record["returncode"])
                break
    if error is None:
        try:
            check_cancelled()
        except KeyboardInterrupt as caught:
            error = str(caught) or "Interrupted"
    if error is None and "controller" in records:
        text = (run / "controller.log").read_text(encoding="utf-8", errors="replace")
        if "Done / 完成" not in text:
            error = "Controller exited without a Gym done acknowledgement"
    return records, error, time.monotonic() - started


def write_metrics(run, metrics):
    write_json(run / "run-metrics.json", metrics)
    flat = {key: value for key, value in metrics.items() if not isinstance(value, dict)}
    with (run / "run-metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat))
        writer.writeheader()
        writer.writerow(flat)


RESOURCE_HEADERS = {
    "rsu-state.csv": "time_ns,event,rsu_id,present_vehicles,cache_vehicle_entries,cache_name_entries,cache_edges,reverse_cache_edges,mac_entries,next_rsu_entries,history_vehicles,history_records,history_timestamp_records",
    "hello-payloads.csv": "time_ns,obu_node_id,rsu_id,category,content_bytes,wire_bytes,cache_items,added_items,removed_items",
}


def validate_resource_outputs(run, config, completion):
    """Require opt-in observer outputs and the actual C++ deployment settings."""
    effective = summary.read_json(run / "raw/effective-experiment-config.json")
    if "hello_interval_ms" in config or config.get("resource_observations"):
        interval = config.get("hello_interval_ms", 20)
        for field, expected in (("hello_interval_ms", interval),
                                ("rsu_timeout_ms", 2 * interval),
                                ("obu_neighbor_timeout_ms", 2000)):
            if type(effective.get(field)) is not int or effective[field] != expected:
                raise ValueError("C++ effective config mismatch: " + field)
    if not config.get("resource_observations", False):
        return []
    if effective.get("resource_observations") is not True or (
            completion.get("resource_observations") is not True):
        raise ValueError("Enabled resource observations missing from C++ completion")
    artifacts = []
    for name, count_field in (("rsu-state.csv", "rsu_state_rows"),
                              ("hello-payloads.csv", "hello_payload_rows")):
        path = run / "raw" / name
        if not path.is_file():
            raise ValueError("Missing enabled resource output: " + name)
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != RESOURCE_HEADERS[name].split(","):
                raise ValueError("Invalid resource CSV header: " + name)
            count = 0
            for row in reader:
                if None in row or any(value is None or value == "" for value in row.values()):
                    raise ValueError("Incomplete resource CSV row: " + name)
                count += 1
        if type(completion.get(count_field)) is not int or completion[count_field] != count:
            raise ValueError("Resource row count differs from completion ledger: " + name)
        artifacts.append("raw/" + name)
    return artifacts


def binary_evidence(root, target):
    binary = root / "build/scratch" / target / target
    if not binary.is_file():
        raise ValueError("Simulator executable missing after waf run: " + str(binary))
    evidence = {"path": str(binary), "sha256": summary.sha256_file(binary),
                "captured": "after successful waf run", "shared_libraries": {}}
    cache = root / "build/c4che/_cache.py"
    # Match wutils.get_proc_env without executing the configuration cache or
    # invoking waf/configure. build/lib is absent from the parent shell by default.
    module_paths = None
    try:
        for line in cache.read_text(encoding="utf-8").splitlines():
            if line.startswith("NS3_MODULE_PATH = "):
                module_paths = ast.literal_eval(line.split("=", 1)[1].strip())
                break
    except (OSError, ValueError, SyntaxError) as error:
        raise ValueError("Cannot read waf dependency search paths: " + str(error))
    if not isinstance(module_paths, list) or any(
            not isinstance(path, str) or not path for path in module_paths):
        raise ValueError("Missing or invalid waf NS3_MODULE_PATH dependency search paths")
    environment = os.environ.copy()
    search_paths = list(module_paths)
    if "LD_LIBRARY_PATH" in environment:
        search_paths.append(environment["LD_LIBRARY_PATH"])
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(search_paths)
    environment["LC_ALL"] = "C"
    try:
        probe = subprocess.run(["ldd", str(binary)], cwd=str(root), env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("ldd dependency resolution failed: " + str(error))
    if probe.returncode != 0:
        raise ValueError("ldd dependency resolution failed: " + probe.stderr.strip())
    resolved = {}
    for line in probe.stdout.splitlines():
        text = line.strip()
        if "=>" in text:
            name, value = text.split("=>", 1)
            if value.strip().startswith("not found"):
                raise ValueError("ldd dependency not found: " + name.strip())
            value = value.rsplit(" (", 1)[0].strip()
        elif text.startswith("/"):
            value = text.rsplit(" (", 1)[0].strip()
            name = Path(value).name
        else:
            # linux-vdso is supplied by the kernel and has no backing ELF file.
            continue
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Invalid ldd dependency path: " + value)
        resolved[name.strip()] = str(path.resolve())
    if not resolved:
        raise ValueError("ldd did not resolve any shared dependencies")
    evidence["shared_libraries"] = {
        filename: summary.sha256_file(Path(filename)) for filename in sorted(set(resolved.values()))}
    evidence["resolved_dependencies"] = resolved
    evidence["resolution_method"] = "ldd with waf NS3_MODULE_PATH and inherited LD_LIBRARY_PATH"
    evidence["module_search_paths"] = module_paths
    evidence["build_cache_sha256"] = summary.sha256_file(cache)
    return evidence


def execute_run(args, root, template, input_hashes, strategy, source):
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    run = args.output_root / identifier
    run.mkdir(parents=True, exist_ok=False)
    (run / "raw").mkdir()
    effective = dict(template, run_id=identifier, output_dir=str(run / "raw"))
    effective["strategy"] = strategy
    effective["block_id"] = args.block_id
    effective["validation_only"] = bool(
        args.test_controller or args.validation_only or template.get("validation_only", False))
    effective["training_snapshots"] = bool(
        args.training_snapshots or template.get("training_snapshots", False))
    effective["require_formal_contract"] = bool(
        args.require_formal_contract or template.get("require_formal_contract", False))
    write_json(run / "experiment.json", effective)
    manifest = {
        "schema_version": 1, "run_id": identifier, "block_id": args.block_id,
        "scenario": effective["scenario"], "strategy": strategy,
        "status": "running", "validation_only": effective["validation_only"],
        "training_snapshots": effective["training_snapshots"],
        "require_formal_contract": effective["require_formal_contract"],
        "started_utc": utc_now(), "input_hashes": input_hashes, "source": source,
        "config_sha256": summary.sha256_file(run / "experiment.json"),
        "model": None, "processes": {}, "measurement_scope": summary.MEASUREMENT_SCOPE,
        "timeout_seconds": args.timeout,
        "execution_mode": "existing-binary" if args.no_build else "waf-build-and-run",
    }
    try:
        args.check_cancelled()
        verify_hashes(input_hashes, "Input")
        if args.model_file is not None:
            verify_hashes({str(args.model_file): args.model_sha256}, "Model")
        if source_snapshot(root)["sha256"] != source["sha256"]:
            raise ValueError("Source changed before a run in the comparison block")
        commands = []
        scenario = effective["scenario"]
        target = "vndn-" + scenario + "-simulator"
        if args.no_build:
            executable = root / "build/scratch" / target / target
            if not executable.is_file() or not os.access(str(executable), os.X_OK):
                raise ValueError("--no-build requires an existing executable: " + str(executable))
            manifest["binary_before"] = binary_evidence(root, target)
            manifest["binary_before"]["captured"] = "before existing-binary execution"
        if strategy == 3:
            if args.test_controller:
                controller = root / "tools/experiments/test_controller.py"
                controller_args = ["--port", str(args.gym_port)]
            else:
                controller = root / "scratch" / ("vndn-" + scenario + "-simulator") / (
                    "vndn-" + scenario + "-tkan-gym.py")
                controller_args = ["--port", str(args.gym_port),
                                   "--model-file", str(args.model_file), "--device", "cpu",
                                   "--decision-log", str(run / "raw/controller-decisions.jsonl")]
                if effective["require_formal_contract"]:
                    controller_args.append("--require-formal-contract")
                if effective["validation_only"]:
                    controller_args.append("--allow-validation-only")
                manifest["model"] = {
                    "path": str(args.model_file), "sha256": args.model_sha256}
            if not controller.is_file():
                raise ValueError("Controller not found: " + str(controller))
            commands.append(("controller", [args.python, str(controller)] + controller_args))
        simulation = [target, "--experiment-config=" + str(run / "experiment.json"),
                      "--rsu-forward-strategy=" + str(strategy),
                      "--open-gym-port=" + str(args.gym_port),
                      "--save-data=0", "--sumo-gui=0", "--pcap=0", "--log=0"]
        commands.append(("simulation", [str(root / "waf"),
                                        "--run-no-build" if args.no_build else "--run",
                                        shlex.join(simulation), "-j", "4"]))
        write_json(run / "manifest.json", manifest)
        records, error, elapsed = run_processes(
            commands, root, run, args.timeout, args.check_cancelled)
        manifest["processes"], manifest["elapsed_seconds"] = records, elapsed
        if error:
            raise ValueError(error)
        manifest["binary"] = binary_evidence(root, target)
        if args.no_build:
            before = dict(manifest["binary_before"])
            before.pop("captured", None)
            after = dict(manifest["binary"])
            after.pop("captured", None)
            if before != after:
                raise ValueError("Existing binary or linked dependencies changed during the run")
        verify_hashes(input_hashes, "Input")
        if manifest["model"]:
            verify_hashes({manifest["model"]["path"]: manifest["model"]["sha256"]}, "Model")
        if source_snapshot(root)["sha256"] != source["sha256"]:
            raise ValueError("Source changed during a run")
        if summary.sha256_file(run / "experiment.json") != manifest["config_sha256"]:
            raise ValueError("Effective config changed during a run")
        metrics = summary.summarize_run(run, require_manifest=False)
        metrics.update(block_id=args.block_id, strategy=strategy,
                       validation_only=effective["validation_only"])
        write_metrics(run, metrics)
        artifact_names = ["experiment.json", "run-metrics.json", "run-metrics.csv"]
        artifact_names += ["raw/" + name for name in summary.RAW_FILES]
        completion = summary.read_json(run / "raw/recorder-complete.json")
        artifact_names += validate_resource_outputs(run, effective, completion)
        if (run / "raw/data-rx.csv").is_file():
            artifact_names.append("raw/data-rx.csv")
        if effective["training_snapshots"]:
            # Required even for a valid zero-observation run. Its absence is a
            # collector failure, not evidence that all requests were unusable.
            for name in ("training-observations.jsonl", "face-roles.json"):
                if not (run / "raw" / name).is_file():
                    raise ValueError("Missing enabled training output: " + name)
                artifact_names.append("raw/" + name)
            with (run / "raw/training-observations.jsonl").open() as stream:
                rows = sum(1 for line in stream if line.strip())
            if (completion.get("training_snapshots") is not True or
                    completion.get("training_snapshot_rows") != rows or
                    completion.get("training_snapshot_eligible", -1) +
                    completion.get("training_snapshot_excluded", -1) != rows):
                raise ValueError("Training observation count does not match completion ledger")
        if "neural_decision_rows" in completion:
            path = run / "raw/neural-decisions.jsonl"
            if not path.is_file():
                raise ValueError("Missing C++ neural decision log")
            with path.open() as stream:
                rows = sum(1 for line in stream if line.strip())
            if completion["neural_decision_rows"] != rows:
                raise ValueError("Neural decision count does not match completion ledger")
            artifact_names.append("raw/neural-decisions.jsonl")
        if strategy == 3 and not args.test_controller:
            path = run / "raw/controller-decisions.jsonl"
            if not path.is_file():
                raise ValueError("Missing model controller decision log")
            with path.open() as stream:
                rows = sum(1 for line in stream if line.strip())
            expected = summary.integer(
                completion.get("neural_decision_rows"), "controller decision expected C++ count")
            if rows != expected:
                raise ValueError("Model controller decision count does not match C++ completion ledger")
            artifact_names.append("raw/controller-decisions.jsonl")
        artifact_names += [name + ".log" for name in records]
        manifest["artifact_hashes"] = {
            name: summary.sha256_file(run / name) for name in artifact_names}
        args.check_cancelled()
        manifest["status"] = "complete"
    except (OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error) or "Interrupted"
    manifest["finished_utc"] = utc_now()
    write_json(run / "manifest.json", manifest)
    print("{}: {} ({})".format(identifier, manifest["status"], manifest.get("error", "validated")),
          flush=True)
    return manifest["status"] == "complete"


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/experiments")
    parser.add_argument("--block-id", required=True)
    choices = parser.add_mutually_exclusive_group()
    choices.add_argument("--strategy", type=int, choices=range(4))
    choices.add_argument("--strategies", default="0,1,2,3")
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--model-file", type=Path)
    model.add_argument("--test-controller", action="store_true",
                       help="Validation-only uniform-probability Gym controller; not a trained model")
    parser.add_argument("--python", default="python3.8")
    parser.add_argument("--gym-port", type=int, default=5555)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--no-build", action="store_true",
                        help="Run the existing executable through waf --run-no-build")
    parser.add_argument("--training-snapshots", action="store_true",
                        help="Record the actual RSU decision inputs without changing forwarding")
    parser.add_argument("--validation-only", action="store_true",
                        help="Mark every strategy as development/pilot evidence")
    parser.add_argument("--require-formal-contract", action="store_true",
                        help="Reject legacy, mismatched or temporary neural model metadata")
    return parser.parse_args(argv)


def _run_block(argv, root, check_cancelled):
    args = parse_arguments(argv)
    args.check_cancelled = check_cancelled
    root = Path(root).resolve() if root is not None else ROOT
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not 1 <= args.gym_port <= 65535 or not args.block_id.strip():
            raise ValueError("Invalid Gym port or block id")
        strategies = [args.strategy] if args.strategy is not None else [
            int(value) for value in args.strategies.split(",")]
        if not strategies or any(value not in range(4) for value in strategies) or (
                len(strategies) != len(set(strategies))):
            raise ValueError("strategies must be distinct values from 0,1,2,3")
        if 3 in strategies and not args.test_controller and args.model_file is None:
            raise ValueError("Neural strategy requires --model-file or --test-controller")
        if args.model_file is not None:
            args.model_file = args.model_file.expanduser().resolve()
            if not args.model_file.is_file():
                raise ValueError("Model file does not exist")
            args.model_sha256 = summary.sha256_file(args.model_file)
        args.output_root = args.output_root.expanduser().resolve()
        # Never write experiment evidence to a legacy training/date/model directory.
        protected = (root / "data/models", root / "data/circle-simple",
                     root / "data/grid-vanet-test", root / "data/fgfxf-spider-map",
                     root.parent / "ns-3_old")
        if any(args.output_root == path or path in args.output_root.parents for path in protected):
            raise ValueError("output-root overlaps protected data/models/legacy paths")
        template, hashes = prepare_inputs(args.config)
        (root / "build").mkdir(exist_ok=True)
        with (root / "build/experiment-run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another experiment runner owns this project's serial lock")
            source = source_snapshot(root)
            for strategy in strategies:
                check_cancelled()
                if not execute_run(args, root, template, hashes, strategy, source):
                    return 1
        return 0
    except (OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print("Experiment block failed: " + (str(error) or "Interrupted"), file=sys.stderr)
        return 1


def main(argv=None, root=None):
    # A flag avoids raising between Popen's child creation and its registration
    # for cleanup. Repeated SIGTERM cannot interrupt the finally/reaping path.
    interrupted = []
    previous = signal.getsignal(signal.SIGTERM)

    def request_stop(signum, frame):
        if not interrupted:
            interrupted.append(signal.Signals(signum).name)

    def check_cancelled():
        if interrupted:
            raise KeyboardInterrupt("Interrupted by " + interrupted[0])

    signal.signal(signal.SIGTERM, request_stop)
    try:
        return _run_block(argv, root, check_cancelled)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
