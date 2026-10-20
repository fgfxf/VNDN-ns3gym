#!/usr/bin/env python3.8
"""Run the project's focused unit regressions, not scenario or scientific validation.

No configure, production training, SUMO simulation, or sampling script is invoked here.
The configured test-runner target is built before the strategy/experiment C++
suites, training, inference and experiment-tool tests. Each Python suite runs in a fresh process
so same-named trainer modules cannot leak between scenarios. Every subprocess
inherits JOBS=4, including nested waf.
"""

import argparse
import ast
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
import uuid
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
CPP_SUITES = ("vndn-rsu-forwarding-policy", "vndn-neural-return-selection",
              "vndn-experiment-config", "vndn-experiment-recorder",
              "vndn-l3-experiment-tracer", "vndn-router-neural-pit",
              "vndn-fragment-destination")
PYTHON_SUITES = (
    ("circle-python", "contrib/vndn-nn-rd/ai-training/circle/tests", "test_*.py"),
    ("grid-python", "contrib/vndn-nn-rd/ai-training/grid/tests", "test_*.py"),
    ("spidermap-python", "contrib/vndn-nn-rd/ai-training/spidermap/tests", "test_*.py"),
    ("inference-python", "contrib/vndn-nn-rd/ai-training/tests", "test_tkan_inference.py"),
    ("experiments-python", "tools/experiments/tests", "test_*.py"),
)
PYTHON_RUNNER = """
import json, sys, unittest
suite = unittest.defaultTestLoader.discover(sys.argv[1], pattern=sys.argv[3])
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = dict(tests_run=result.testsRun, failures=len(result.failures),
               errors=len(result.errors), skipped=len(result.skipped),
               expected_failures=len(result.expectedFailures),
               unexpected_successes=len(result.unexpectedSuccesses))
with open(sys.argv[2], 'w', encoding='utf-8') as output:
    json.dump(summary, output)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite number greater than zero")
    return seconds


def stop_process_group(process):
    """Terminate descendants too, even when the group leader exits first."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_step(name, command, root, output, timeout):
    log_path = output / (name + ".log")
    step = dict(name=name, command=[str(arg) for arg in command], cwd=str(root),
                returncode=None, duration_seconds=0, status="failed", log=str(log_path),
                timeout_seconds=timeout)
    environment = os.environ.copy()
    environment["JOBS"] = "4"
    started = time.monotonic()
    print("[{}] {}\n  log: {}".format(name, shlex.join(step["command"]), log_path), flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("cwd: {}\nJOBS=4\ncommand: {}\n\n".format(root, shlex.join(step["command"])))
        log.flush()
        try:
            process = subprocess.Popen(step["command"], cwd=str(root), env=environment,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                step["returncode"] = process.wait(timeout=timeout)
                step["status"] = "passed" if step["returncode"] == 0 else "failed"
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                stop_process_group(process)
                step["returncode"] = process.returncode
                step["status"] = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "interrupted"
                step["error"] = "Process group stopped: " + step["status"]
        except OSError as error:
            step["status"] = "missing" if isinstance(error, FileNotFoundError) else "failed"
            step["error"] = str(error)
        step["duration_seconds"] = round(time.monotonic() - started, 6)
        log.write("\nvalidation status: {}\n".format(step["status"]))
        if "error" in step:
            log.write(step["error"] + "\n")
    return step


def check_configuration(root):
    cache = root / "build/c4che/_cache.py"
    try:
        parsed = ast.parse(cache.read_text(encoding="utf-8"), filename=str(cache))
        enabled = None
        for node in parsed.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "ENABLE_TESTS"
                    for target in node.targets):
                enabled = ast.literal_eval(node.value)
        if enabled is True:
            return
    except (OSError, SyntaxError, ValueError, TypeError):
        pass
    raise ValueError("ENABLE_TESTS must be True in {}. Preserve the existing waf "
                     "configuration and enable tests explicitly; this gate never "
                     "runs configure automatically.".format(cache))


def verify_cpp(path, suite):
    results = ElementTree.parse(str(path)).getroot()
    matches = [node for node in results.findall("Test") if node.findtext("Name") == suite]
    if len(matches) != 1:
        raise ValueError("Expected exactly one executed C++ suite: " + suite)
    selected = matches[0]
    cases = selected.findall(".//Test")
    if not cases or any(node.findtext("Result") != "PASS" for node in [selected] + cases):
        raise ValueError("C++ suite must contain executed cases, all PASS (no SKIP): " + suite)
    return {"suite": suite, "test_nodes": len(cases), "xml": str(path)}


def verify_python(path):
    summary = json.loads(path.read_text(encoding="utf-8"))
    count = summary.get("tests_run")
    if type(count) is not int or count <= 0:
        raise ValueError("Python discovery must execute at least one test")
    for key in ("failures", "errors", "skipped", "expected_failures", "unexpected_successes"):
        if summary.get(key) != 0:
            raise ValueError("Python tests must all pass without skips: " + key)
    return summary


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="python3.8", help="Python interpreter for test runners")
    parser.add_argument("--skip-build", action="store_true",
                        help="explicitly reuse existing binaries; caller must ensure they match sources")
    parser.add_argument("--timeout", type=positive_seconds, default=600,
                        help="per-test-step wall-clock timeout in seconds (default: 600)")
    parser.add_argument("--build-timeout", type=positive_seconds, default=1800,
                        help="build wall-clock timeout in seconds (default: 1800)")
    args = parser.parse_args(argv)
    root = Path(root).resolve() if root is not None else ROOT
    started = datetime.now(timezone.utc)
    output = root / "build/validation" / (started.strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    report_path = output / "report.json"
    report = dict(schema_version=1, scope="focused unit regressions; not scenario/end-to-end validation",
                  started_at=started.isoformat(), root=str(root), jobs=4,
                  build_skipped=args.skip_build, status="running", steps=[])

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    print("Report: {}".format(report_path), flush=True)
    if args.skip_build:
        print("BUILD SKIPPED explicitly: existing binaries may be stale.", flush=True)
    try:
        check_configuration(root)
        steps = []
        if not args.skip_build:
            steps.append(("build", [str(root / "waf"), "build", "-j", "4", "--targets=test-runner"],
                          args.build_timeout, None))
        for suite in CPP_SUITES:
            xml_path = output / (suite + ".xml")
            steps.append((suite, [args.python, str(root / "test.py"), "--nowaf", "--suite=" + suite,
                                  "--xml=" + str(output / suite)], args.timeout,
                          lambda path=xml_path, name=suite: verify_cpp(path, name)))
        for name, directory, pattern in PYTHON_SUITES:
            python_summary = output / (name + ".json")
            steps.append((name, [args.python, "-c", PYTHON_RUNNER,
                                 str(root / directory), str(python_summary), pattern], args.timeout,
                          lambda path=python_summary: verify_python(path)))
        for name, command, timeout, verify in steps:
            step = run_step(name, command, root, output, timeout)
            report["steps"].append(step)
            if step["status"] == "passed" and verify is not None:
                try:
                    step["evidence"] = verify()
                except (OSError, ValueError, TypeError, ElementTree.ParseError) as error:
                    step["status"] = "failed"
                    step["error"] = "Test evidence rejected: " + str(error)
                    with Path(step["log"]).open("a", encoding="utf-8") as log:
                        log.write(step["error"] + "\nfinal validation status: failed\n")
            save()
            print("[{}] {}".format(name, step["status"]), flush=True)
            if step["status"] != "passed":
                raise ValueError("{}: {} (see {})".format(name, step.get("error", step["status"]), step["log"]))
        report["status"] = "passed"
    except (OSError, ValueError, KeyboardInterrupt) as error:
        report["status"] = "failed"
        report["error"] = str(error) or "Interrupted"
        print(report["error"], flush=True)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    print("Validation {}. Report: {}".format(report["status"], report_path), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
