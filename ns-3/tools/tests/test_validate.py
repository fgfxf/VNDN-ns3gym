"""Acceptance tests for the gate; all builds and C++ suites use temporary fakes."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "validate.py"
SPEC = importlib.util.spec_from_file_location("project_validate", MODULE_PATH)
validate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate)


class ValidationGateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        cache = self.root / "build/c4che/_cache.py"
        cache.parent.mkdir(parents=True)
        cache.write_text("ENABLE_TESTS = True\n", encoding="utf-8")
        (self.root / "state.json").write_text("{}", encoding="utf-8")
        waf = self.root / "waf"
        waf.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, pathlib, sys\n"
            "p = pathlib.Path.cwd()\n"
            "(p / 'build-call.json').write_text(json.dumps({"
            "'argv': sys.argv[1:], 'jobs': os.environ.get('JOBS'), 'cwd': str(p)}))\n"
            "sys.exit(json.loads((p / 'state.json').read_text()).get('build_rc', 0))\n",
            encoding="utf-8",
        )
        waf.chmod(0o755)
        (self.root / "test.py").write_text(
            "import json, pathlib, sys\n"
            "from xml.etree.ElementTree import Element, SubElement, ElementTree\n"
            "p = pathlib.Path.cwd()\n"
            "state = json.loads((p / 'state.json').read_text())\n"
            "assert '--nowaf' in sys.argv\n"
            "suite = next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--suite='))\n"
            "state.update(state.get('suites', {}).get(suite, {}))\n"
            "out = next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--xml='))\n"
            "tree = Element('Results')\n"
            "if state.get('xml') != 'empty':\n"
            "    test = SubElement(tree, 'Test')\n"
            "    SubElement(test, 'Name').text = state.get('suite', suite)\n"
            "    SubElement(test, 'Result').text = state.get('result', 'PASS')\n"
            "    if state.get('xml') != 'no-cases':\n"
            "        case = SubElement(test, 'Test')\n"
            "        SubElement(case, 'Name').text = 'a real case'\n"
            "        SubElement(case, 'Result').text = state.get('case_result', 'PASS')\n"
            "if state.get('xml') != 'missing':\n"
            "    ElementTree(tree).write(out + '.xml')\n"
            "sys.exit(state.get('cpp_rc', 0))\n",
            encoding="utf-8",
        )
        self.python_suites = {
            "circle-python": ("contrib/vndn-nn-rd/ai-training/circle/tests", "test_sample.py"),
            "grid-python": ("contrib/vndn-nn-rd/ai-training/grid/tests", "test_sample.py"),
            "spidermap-python": ("contrib/vndn-nn-rd/ai-training/spidermap/tests", "test_sample.py"),
            "inference-python": ("contrib/vndn-nn-rd/ai-training/tests", "test_tkan_inference.py"),
            "experiments-python": ("tools/experiments/tests", "test_sample.py"),
        }
        for name in self.python_suites:
            self.write_python_fixture(name)
        self.python_tests = self.root / self.python_suites["circle-python"][0]

    def write_python_fixture(self, name):
        directory, filename = self.python_suites[name]
        path = self.root / directory
        path.mkdir(parents=True, exist_ok=True)
        # Every suite imports a different module with the same name, as real trainers do.
        (path.parent / "train_tkan_lstm.py").write_text(
            "SCENARIO = {!r}\n".format(name), encoding="utf-8")
        (path / filename).write_text(
            "import json, os, pathlib, sys, unittest\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n"
            "import train_tkan_lstm\n"
            "class Sample(unittest.TestCase):\n"
            "    def test_jobs(self):\n"
            "        self.assertEqual(os.environ['JOBS'], '4')\n"
            "        self.assertEqual(train_tkan_lstm.SCENARIO, {!r})\n"
            "        with open('python-calls.jsonl', 'a') as output:\n"
            "            output.write(json.dumps(dict(name={!r}, pid=os.getpid())) + '\\n')\n".format(name, name),
            encoding="utf-8",
        )

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            code = validate.main(["--python", sys.executable] + list(args), root=self.root)
        reports = sorted((self.root / "build/validation").glob("*/report.json"))
        self.assertTrue(reports, "Every attempted validation must leave a report")
        return code, json.loads(reports[-1].read_text(encoding="utf-8"))

    def state(self, **values):
        (self.root / "state.json").write_text(json.dumps(values), encoding="utf-8")

    def test_success_runs_all_gates_from_unrelated_cwd_with_four_jobs(self):
        before = Path.cwd()
        old_jobs = os.environ.get("JOBS")
        try:
            os.chdir(self.root.parent)
            os.environ["JOBS"] = "99"
            code, report = self.invoke()
        finally:
            os.chdir(before)
            if old_jobs is None:
                os.environ.pop("JOBS", None)
            else:
                os.environ["JOBS"] = old_jobs
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["steps"]), 15)
        call = json.loads((self.root / "build-call.json").read_text())
        self.assertEqual(call, {"argv": ["build", "-j", "4", "--targets=test-runner"], "jobs": "4", "cwd": str(self.root)})
        for step in report["steps"]:
            self.assertEqual(step["status"], "passed")
            self.assertEqual(step["returncode"], 0)
            self.assertEqual(step["cwd"], str(self.root))
            self.assertGreaterEqual(step["duration_seconds"], 0)
            self.assertTrue(Path(step["log"]).is_file())

    def test_experiment_suites_are_mandatory_parts_of_the_gate(self):
        code, report = self.invoke()
        self.assertEqual(code, 0)
        names = {step["name"] for step in report["steps"]}
        self.assertTrue({
            "vndn-experiment-config", "vndn-experiment-recorder",
            "vndn-l3-experiment-tracer", "experiments-python",
        }.issubset(names), "The old unit gate does not exercise the new measurement contract")

    def test_neural_delivery_suites_are_mandatory_parts_of_the_gate(self):
        code, report = self.invoke()
        self.assertEqual(code, 0)
        names = [step["name"] for step in report["steps"]]
        for suite in ("vndn-router-neural-pit", "vndn-fragment-destination",
                      "vndn-rsu-neural-return-buffer"):
            with self.subTest(suite=suite):
                self.assertEqual(names.count(suite), 1,
                                 "Delivery regressions must execute exactly once")
                step = next(step for step in report["steps"] if step["name"] == suite)
                self.assertEqual(step["evidence"]["suite"], suite)
                self.assertGreater(step["evidence"]["test_nodes"], 0)

    def test_training_snapshot_and_formal_training_are_required(self):
        code, report = self.invoke()
        self.assertEqual(code, 0)
        names = [step["name"] for step in report["steps"]]
        self.assertEqual(names.count("vndn-training-snapshot"), 1)
        shared = next(step for step in report["steps"] if step["name"] == "inference-python")
        self.assertEqual(shared["command"][-1], "test_*.py",
                         "The shared training directory must include the formal contract tests")

    def test_neural_delivery_suite_evidence_is_required(self):
        for suite in ("vndn-router-neural-pit", "vndn-fragment-destination",
                      "vndn-rsu-neural-return-buffer"):
            for evidence in ({"xml": "empty"}, {"case_result": "SKIP"}, {"cpp_rc": 3}):
                with self.subTest(suite=suite, evidence=evidence):
                    self.state(suites={suite: evidence})
                    code, report = self.invoke("--skip-build")
                    self.assertNotEqual(code, 0,
                                        "Missing, skipped or failed delivery tests must reject the run")
                    self.assertEqual(report["steps"][-1]["name"], suite)
                    self.assertEqual(report["steps"][-1]["status"], "failed")

    def test_neural_delivery_tests_are_registered_for_the_module_build(self):
        class RecordingBuild:
            env = SimpleNamespace(ENABLE_EXAMPLES=False)

            def create_ns3_module(self, name, dependencies):
                return SimpleNamespace(use=[])

            def __call__(self, **kwargs):
                return SimpleNamespace()

            def create_ns3_module_test_library(self, name):
                self.test_library = SimpleNamespace()
                return self.test_library

        build = RecordingBuild()
        wscript = MODULE_PATH.parents[1] / "contrib/vndn-nn-rd/wscript"
        runpy.run_path(str(wscript))["build"](build)
        for source in ("test/vndn-router-neural-pit-test.cc",
                       "test/vndn-fragment-destination-test.cc",
                       "test/vndn-rsu-neural-return-buffer-test.cc"):
            with self.subTest(source=source):
                self.assertEqual(build.test_library.source.count(source), 1,
                                 "The test-runner must link each delivery regression")

    def test_missing_or_disabled_configuration_fails_without_building(self):
        cache = self.root / "build/c4che/_cache.py"
        for contents in (None, "ENABLE_TESTS = False\n", "ENABLE_TESTS = 1\n"):
            with self.subTest(contents=contents):
                if contents is None:
                    cache.unlink()
                else:
                    cache.write_text(contents, encoding="utf-8")
                code, report = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertEqual(report["status"], "failed")
                self.assertIn("ENABLE_TESTS", report["error"])
                self.assertFalse((self.root / "build-call.json").exists())

    def test_failed_build_stops_before_tests(self):
        self.state(build_rc=7)
        code, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertEqual(len(report["steps"]), 1)
        self.assertEqual(report["steps"][0]["returncode"], 7)

    def test_zero_exit_cannot_hide_missing_skipped_or_wrong_cpp_tests(self):
        for state in ({"xml": "missing"}, {"xml": "empty"}, {"xml": "no-cases"},
                      {"suite": "other-suite"}, {"result": "SKIP"},
                      {"case_result": "SKIP"}, {"case_result": "FAIL"}):
            with self.subTest(state=state):
                self.state(**state)
                code, report = self.invoke("--skip-build")
                self.assertNotEqual(code, 0)
                self.assertEqual(report["steps"][-1]["status"], "failed")

    def test_nonzero_cpp_exit_fails_even_with_passing_xml(self):
        self.state(cpp_rc=3)
        code, report = self.invoke("--skip-build")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["steps"][-1]["returncode"], 3)

    def test_empty_python_discovery_is_failure(self):
        (self.python_tests / "test_sample.py").unlink()
        code, report = self.invoke("--skip-build")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["steps"][-1]["name"], "circle-python")

    def test_skipped_python_test_is_failure(self):
        (self.python_tests / "test_sample.py").write_text(
            "import unittest\nclass Sample(unittest.TestCase):\n"
            "    @unittest.skip('missing dependency')\n"
            "    def test_skipped(self): pass\n", encoding="utf-8")
        code, report = self.invoke("--skip-build")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["steps"][-1]["status"], "failed")

    def test_python_assertion_failure_is_failure(self):
        (self.python_tests / "test_sample.py").write_text(
            "import unittest\nclass Sample(unittest.TestCase):\n"
            "    def test_failure(self): self.fail('regression')\n", encoding="utf-8")
        code, report = self.invoke("--skip-build")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["steps"][-1]["status"], "failed")

    def test_missing_new_python_suite_is_failure(self):
        for name, (directory, _) in self.python_suites.items():
            if name == "circle-python":
                continue
            with self.subTest(suite=name):
                shutil.rmtree(self.root / directory)
                try:
                    code, report = self.invoke("--skip-build")
                    self.assertNotEqual(code, 0)
                    self.assertEqual(report["steps"][-1]["name"], name)
                    self.assertEqual(report["steps"][-1]["status"], "failed")
                finally:
                    self.write_python_fixture(name)

    def test_empty_new_python_suite_is_failure(self):
        for name, (directory, filename) in self.python_suites.items():
            if name == "circle-python":
                continue
            with self.subTest(suite=name):
                (self.root / directory / filename).unlink()
                try:
                    code, report = self.invoke("--skip-build")
                    self.assertNotEqual(code, 0)
                    self.assertEqual(report["steps"][-1]["name"], name)
                    self.assertIn("at least one test", report["error"])
                finally:
                    self.write_python_fixture(name)

    def test_skipped_new_python_suite_is_failure(self):
        for name, (directory, filename) in self.python_suites.items():
            if name == "circle-python":
                continue
            with self.subTest(suite=name):
                (self.root / directory / filename).write_text(
                    "import unittest\nclass Sample(unittest.TestCase):\n"
                    "    @unittest.skip('missing dependency')\n"
                    "    def test_skipped(self): pass\n", encoding="utf-8")
                try:
                    code, report = self.invoke("--skip-build")
                    self.assertNotEqual(code, 0)
                    self.assertEqual(report["steps"][-1]["name"], name)
                    self.assertIn("without skips", report["error"])
                finally:
                    self.write_python_fixture(name)

    def test_failed_new_python_suite_is_failure(self):
        for name, (directory, filename) in self.python_suites.items():
            if name == "circle-python":
                continue
            with self.subTest(suite=name):
                (self.root / directory / filename).write_text(
                    "import unittest\nclass Sample(unittest.TestCase):\n"
                    "    def test_failure(self): self.fail('new scenario regression')\n",
                    encoding="utf-8")
                try:
                    code, report = self.invoke("--skip-build")
                    self.assertNotEqual(code, 0)
                    self.assertEqual(report["steps"][-1]["name"], name)
                    self.assertEqual(report["steps"][-1]["status"], "failed")
                    self.assertNotEqual(report["steps"][-1]["returncode"], 0)
                finally:
                    self.write_python_fixture(name)

    def test_python_suites_have_separate_processes_logs_and_evidence(self):
        # The shared gate discovers test_*.py, not arbitrary helper modules.
        inference_directory = self.root / self.python_suites["inference-python"][0]
        (inference_directory / "unrelated_helper.py").write_text(
            "raise RuntimeError('a non-test helper must not run')\n", encoding="utf-8")
        code, report = self.invoke("--skip-build")
        self.assertEqual(code, 0)
        steps = [step for step in report["steps"] if step["name"] in self.python_suites]
        self.assertEqual([step["name"] for step in steps], list(self.python_suites))
        calls = [json.loads(line) for line in (self.root / "python-calls.jsonl").read_text().splitlines()]
        self.assertEqual([call["name"] for call in calls], list(self.python_suites))
        self.assertEqual(len({call["pid"] for call in calls}), len(self.python_suites))
        for step in steps:
            self.assertEqual(step["evidence"]["tests_run"], 1)
            self.assertEqual(step["evidence"]["skipped"], 0)
            self.assertEqual(Path(step["log"]).name, step["name"] + ".log")
            summary = Path(step["log"]).with_suffix(".json")
            self.assertEqual(json.loads(summary.read_text()), step["evidence"])

    def test_formal_training_failure_cannot_be_ignored_by_shared_gate(self):
        directory = self.root / self.python_suites["inference-python"][0]
        (directory / "test_formal_training.py").write_text(
            "import unittest\nclass Formal(unittest.TestCase):\n"
            "    def test_contract(self): self.fail('formal training contract regression')\n")
        code, report = self.invoke("--skip-build")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["steps"][-1]["name"], "inference-python")
        self.assertEqual(report["steps"][-1]["status"], "failed")

    def test_skip_build_is_explicit_and_reports_are_unique(self):
        self.assertEqual(self.invoke("--skip-build")[0], 0)
        code, report = self.invoke("--skip-build")
        self.assertEqual(code, 0)
        self.assertTrue(report["build_skipped"])
        self.assertEqual(len(list((self.root / "build/validation").glob("*/report.json"))), 2)
        self.assertFalse((self.root / "build-call.json").exists())

    def test_missing_interpreter_is_failure(self):
        code, report = self.invoke("--skip-build", "--python", str(self.root / "missing-python"))
        self.assertNotEqual(code, 0)
        self.assertEqual(report["steps"][-1]["status"], "missing")

    def test_timeout_kills_process_group_and_records_timeout(self):
        logdir = self.root / "timeout-log"
        logdir.mkdir()
        child_pid = self.root / "child.pid"
        child_code = (
            "import os, pathlib, signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "pathlib.Path({!r}).write_text(str(os.getpid())); time.sleep(30)"
        ).format(str(child_pid))
        command = [sys.executable, "-c",
                   "import subprocess, sys, time; "
                   "subprocess.Popen([sys.executable, '-c', {!r}]); "
                   "time.sleep(30)".format(child_code)]
        step = validate.run_step("timeout", command, self.root, logdir, 0.5)
        self.assertEqual(step["status"], "timeout")
        self.assertIsNotNone(step["returncode"])
        self.assertLess(step["duration_seconds"], 4)
        self.assertTrue(child_pid.exists(), "The descendant must have started before timeout")
        status_file = Path("/proc") / child_pid.read_text() / "status"
        deadline = time.monotonic() + 1
        while status_file.exists() and time.monotonic() < deadline:
            try:
                if "State:\tZ" in status_file.read_text():
                    break  # Exited; the container's init may not have reaped it yet.
            except (FileNotFoundError, ProcessLookupError):
                break
            time.sleep(0.01)
        else:
            self.assertFalse(status_file.exists(), "A SIGTERM-resistant descendant survived timeout")


if __name__ == "__main__":
    unittest.main()
