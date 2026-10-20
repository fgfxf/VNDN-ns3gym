#!/usr/bin/env python3.8
"""Run one serial comparison block; never configure, train, or overwrite old data.

The input template defines one fixed seed tuple and request/mobility input.
Repeat this command with a separately generated input/seed block for independent
replications. A zero process exit alone never certifies a valid experiment.
"""
import argparse
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


def run_processes(commands, root, run, timeout):
    processes, handles, records = {}, {}, {}
    environment = os.environ.copy()
    environment.update(JOBS="4", VNDN_EXPERIMENT_RUN_DIR=str(run))
    # Shared simulation ports are protected by the project-level runner lock.
    started = time.monotonic()
    error = None
    try:
        for name, command in commands:
            handles[name] = (run / (name + ".log")).open("w", encoding="utf-8")
            records[name] = {"command": command, "returncode": None, "cwd": str(root),
                             "log": name + ".log", "JOBS": "4"}
            handles[name].write("JOBS=4\ncommand: " + shlex.join(command) + "\n\n")
            handles[name].flush()
            processes[name] = subprocess.Popen(
                command, cwd=str(root), env=environment, stdout=handles[name],
                stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            for name, process in processes.items():
                code = process.poll()
                records[name]["returncode"] = code
                if code is not None and code != 0:
                    raise RuntimeError("{} exited with {}".format(name, code))
            if all(process.poll() is not None for process in processes.values()):
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


def binary_evidence(root, target):
    binary = root / "build/scratch" / target / target
    if not binary.is_file():
        raise ValueError("Simulator executable missing after waf run: " + str(binary))
    evidence = {"path": str(binary), "sha256": summary.sha256_file(binary),
                "captured": "after successful waf run", "shared_libraries": {}}
    for library in sorted((root / "build").glob("*.so")):
        if any(part in library.name for part in ("ndnSIM", "vndn", "traci", "opengym")):
            evidence["shared_libraries"][str(library)] = summary.sha256_file(library)
    cache = root / "build/c4che/_cache.py"
    evidence["build_cache_sha256"] = summary.sha256_file(cache) if cache.is_file() else None
    return evidence


def execute_run(args, root, template, input_hashes, strategy, source):
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    run = args.output_root / identifier
    run.mkdir(parents=True, exist_ok=False)
    (run / "raw").mkdir()
    effective = dict(template, run_id=identifier, output_dir=str(run / "raw"))
    effective["strategy"] = strategy
    effective["block_id"] = args.block_id
    effective["validation_only"] = bool(args.test_controller)
    write_json(run / "experiment.json", effective)
    manifest = {
        "schema_version": 1, "run_id": identifier, "block_id": args.block_id,
        "scenario": effective["scenario"], "strategy": strategy,
        "status": "running", "validation_only": bool(args.test_controller),
        "started_utc": utc_now(), "input_hashes": input_hashes, "source": source,
        "config_sha256": summary.sha256_file(run / "experiment.json"),
        "model": None, "processes": {}, "measurement_scope": summary.MEASUREMENT_SCOPE,
        "timeout_seconds": args.timeout,
    }
    try:
        verify_hashes(input_hashes, "Input")
        if args.model_file is not None:
            verify_hashes({str(args.model_file): args.model_sha256}, "Model")
        if source_snapshot(root)["sha256"] != source["sha256"]:
            raise ValueError("Source changed before a run in the comparison block")
        commands = []
        scenario = effective["scenario"]
        if strategy == 3:
            if args.test_controller:
                controller = root / "tools/experiments/test_controller.py"
                controller_args = ["--port", str(args.gym_port)]
            else:
                controller = root / "scratch" / ("vndn-" + scenario + "-simulator") / (
                    "vndn-" + scenario + "-tkan-gym.py")
                controller_args = ["--port", str(args.gym_port),
                                   "--model-file", str(args.model_file), "--device", "cpu"]
                manifest["model"] = {
                    "path": str(args.model_file), "sha256": args.model_sha256}
            if not controller.is_file():
                raise ValueError("Controller not found: " + str(controller))
            commands.append(("controller", [args.python, str(controller)] + controller_args))
        target = "vndn-" + scenario + "-simulator"
        simulation = [target, "--experiment-config=" + str(run / "experiment.json"),
                      "--rsu-forward-strategy=" + str(strategy),
                      "--open-gym-port=" + str(args.gym_port),
                      "--save-data=0", "--sumo-gui=0", "--pcap=0", "--log=0"]
        commands.append(("simulation", [str(root / "waf"), "--run",
                                        shlex.join(simulation), "-j", "4"]))
        write_json(run / "manifest.json", manifest)
        records, error, elapsed = run_processes(commands, root, run, args.timeout)
        manifest["processes"], manifest["elapsed_seconds"] = records, elapsed
        if error:
            raise ValueError(error)
        manifest["binary"] = binary_evidence(root, target)
        verify_hashes(input_hashes, "Input")
        if manifest["model"]:
            verify_hashes({manifest["model"]["path"]: manifest["model"]["sha256"]}, "Model")
        if source_snapshot(root)["sha256"] != source["sha256"]:
            raise ValueError("Source changed during a run")
        if summary.sha256_file(run / "experiment.json") != manifest["config_sha256"]:
            raise ValueError("Effective config changed during a run")
        metrics = summary.summarize_run(run, require_manifest=False)
        metrics.update(block_id=args.block_id, strategy=strategy,
                       validation_only=bool(args.test_controller))
        write_metrics(run, metrics)
        artifact_names = ["experiment.json", "run-metrics.json", "run-metrics.csv"]
        artifact_names += ["raw/" + name for name in summary.RAW_FILES]
        if (run / "raw/data-rx.csv").is_file():
            artifact_names.append("raw/data-rx.csv")
        artifact_names += [name + ".log" for name in records]
        manifest["artifact_hashes"] = {
            name: summary.sha256_file(run / name) for name in artifact_names}
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
    return parser.parse_args(argv)


def main(argv=None, root=None):
    args = parse_arguments(argv)
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
                if not execute_run(args, root, template, hashes, strategy, source):
                    return 1
        return 0
    except (OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print("Experiment block failed: " + (str(error) or "Interrupted"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
