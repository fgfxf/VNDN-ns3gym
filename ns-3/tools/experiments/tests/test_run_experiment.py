import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "experiment_runner", Path(__file__).resolve().parents[1] / "run_experiment.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class RunExperimentTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.outputs = self.root / "results"
        for name in ("network.net.xml", "routes.rou.xml", "simulation.sumocfg"):
            (self.inputs / name).write_text("<root/>")
        (self.inputs / "simulation.sumocfg").write_text(
            '<configuration><input><net-file value="network.net.xml"/>'
            '<route-files value="routes.rou.xml"/></input></configuration>')
        requests = [{"vehicle_id": "veh0", "sequence": i,
                     "send_time_ns": 1000000000 + i * 10000000} for i in range(1, 5)]
        (self.inputs / "request-plan.json").write_text(json.dumps({
            "schema_version": 1, "requests": requests}))
        self.config = self.inputs / "experiment-template.json"
        self.config.write_text(json.dumps({
            "schema_version": 1, "scenario": "circle", "run_id": "template",
            "sumo_config": "simulation.sumocfg", "route_file": "routes.rou.xml",
            "request_plan": "request-plan.json", "output_dir": "unused",
            "measurement_start_s": 1, "measurement_end_s": 2, "drain_end_s": 5.5,
            "seeds": {"rng_seed": 1, "rng_run": 2, "sumo_seed": 3, "srand_seed": 4},
            "input_files": ["network.net.xml", "routes.rou.xml",
                            "simulation.sumocfg", "request-plan.json"],
        }))
        self.state = self.root / "state.json"
        self.state.write_text("{}")
        cache = self.root / "build/c4che/_cache.py"
        cache.parent.mkdir(parents=True)
        cache.write_text("NS3_MODULE_PATH = []\n")
        helper_dir = str(Path(__file__).resolve().parent)
        fake_waf = """#!{python}
import json, os, pathlib, shlex, shutil, signal, subprocess, sys, time
sys.path.insert(0, {helper_dir!r})
from experiment_test_support import valid_run
root=pathlib.Path.cwd()
state=json.loads((root/'state.json').read_text())
args=shlex.split(sys.argv[sys.argv.index('--run')+1])
config=pathlib.Path(next(x.split('=',1)[1] for x in args if x.startswith('--experiment-config=')))
run=config.parent
with (root/'calls.jsonl').open('a') as output:
 output.write(json.dumps({{'args':sys.argv[1:],'jobs':os.environ.get('JOBS'),'run':str(run)}})+'\\n')
if state.get('spawn_descendant'):
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
 signal.signal(signal.SIGTERM, signal.SIG_IGN)
 (root/'process-ids.json').write_text(json.dumps({{'leader':os.getpid(),'child':child.pid}}))
if state.get('sleep'): time.sleep(state['sleep'])
valid_run(run,preserve_config=True)
if state.get('no_marker'): (run/'raw/recorder-complete.json').unlink()
if state.get('rx_log'): (run/'raw/data-rx.csv').write_text('opaque receive diagnostics\\n')
if state.get('training_files'):
 (run/'raw/training-observations.jsonl').write_text('{{"schema_version":1}}\\n')
 (run/'raw/face-roles.json').write_text('{{"schema_version":1,"nodes":[],"faces":[]}}\\n')
 marker=json.loads((run/'raw/recorder-complete.json').read_text())
 marker.update(training_snapshots=True,training_snapshot_rows=99 if state.get('bad_training_count') else 1,training_snapshot_eligible=1,training_snapshot_excluded=0)
 (run/'raw/recorder-complete.json').write_text(json.dumps(marker))
if state.get('decision_marker') or '--rsu-forward-strategy=3' in args:
 marker=json.loads((run/'raw/recorder-complete.json').read_text())
 marker['neural_decision_rows']=state.get('cpp_decision_rows',0)
 (run/'raw/recorder-complete.json').write_text(json.dumps(marker))
if state.get('decision_log') or '--rsu-forward-strategy=3' in args:
 (run/'raw/neural-decisions.jsonl').write_text('{{}}\\n'*state.get('cpp_decision_rows',0))
(run/'controller-stop').write_text('done')
binary=root/'build/scratch'/args[0]/args[0]
binary.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(sys.executable,binary)
print('fake simulation finished',flush=True)
sys.exit(state.get('simulation_rc',0))
""".format(python=sys.executable, helper_dir=helper_dir)
        (self.root / "waf").write_text(fake_waf)
        (self.root / "waf").chmod(0o755)
        controller = self.root / "scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py"
        controller.parent.mkdir(parents=True)
        controller.write_text("""import json, os, pathlib, sys, time
root=pathlib.Path.cwd()
state=json.loads((root/'state.json').read_text())
if state.get('spawn_descendant'): (root/'controller-pid').write_text(str(os.getpid()))
if state.get('controller_rc'): sys.exit(state['controller_rc'])
run=pathlib.Path(os.environ['VNDN_EXPERIMENT_RUN_DIR'])
while not (run/'controller-stop').exists(): time.sleep(.01)
if '--decision-log' in sys.argv and not state.get('missing_controller_decisions'):
 path=pathlib.Path(sys.argv[sys.argv.index('--decision-log')+1])
 with path.open('x') as stream:
  stream.write('{}\\n'*state.get('controller_decision_rows',state.get('cpp_decision_rows',0)))
print('Done / 完成，共 4 次决策')
""")
        self.model = self.root / "test-model.pt"
        self.model.write_bytes(b"test fixture: never deserialize")

    def invoke(self, *extra):
        args = ["--config", str(self.config), "--output-root", str(self.outputs),
                "--block-id", "block-1", "--python", sys.executable, "--timeout", "3"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return runner.main(args + list(extra), root=self.root)

    def manifests(self):
        return sorted(self.outputs.glob("*/manifest.json"))

    def test_serial_strategies_leave_hashes_metrics_and_completion(self):
        code = self.invoke("--strategies", "0,1,2,3", "--model-file", str(self.model))
        self.assertEqual(code, 0)
        manifests = self.manifests()
        self.assertEqual(len(manifests), 4)
        for path in manifests:
            value = json.loads(path.read_text())
            self.assertEqual(value["status"], "complete")
            self.assertEqual(value["block_id"], "block-1")
            self.assertEqual(value["processes"]["simulation"]["returncode"], 0)
            self.assertTrue(value["input_hashes"])
            self.assertTrue(value["source"]["sha256"])
            self.assertTrue(value.get("binary", {}).get("sha256"))
            self.assertTrue(value["artifact_hashes"])
            self.assertEqual(json.loads((path.parent / "run-metrics.json").read_text())["generated"], 4)
            effective = json.loads((path.parent / "experiment.json").read_text())
            self.assertEqual(effective["output_dir"], str(path.parent / "raw"))
            self.assertTrue(Path(effective["sumo_config"]).is_absolute())
            if value["strategy"] == 3:
                self.assertEqual(value["processes"]["controller"]["returncode"], 0)
                self.assertTrue(value["model"]["sha256"])
        calls = [json.loads(x) for x in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(x["jobs"] == "4" for x in calls))
        self.assertTrue(all("configure" not in x["args"] for x in calls))

    def test_failure_is_nonzero_stops_block_and_never_marks_complete(self):
        self.state.write_text(json.dumps({"simulation_rc": 7}))
        self.assertNotEqual(self.invoke("--strategies", "0,1"), 0)
        self.assertEqual(len(self.manifests()), 1)
        value = json.loads(self.manifests()[0].read_text())
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["processes"]["simulation"]["returncode"], 7)
        self.assertFalse((self.manifests()[0].parent / "run-metrics.json").exists())

    def test_zero_exit_without_recorder_marker_fails(self):
        self.state.write_text(json.dumps({"no_marker": True}))
        self.assertNotEqual(self.invoke("--strategy", "0"), 0)
        self.assertEqual(json.loads(self.manifests()[0].read_text())["status"], "failed")

    def test_controller_failure_and_timeout_propagate(self):
        self.state.write_text(json.dumps({"controller_rc": 9, "sleep": 10}))
        self.assertNotEqual(self.invoke("--strategy", "3", "--model-file", str(self.model)), 0)
        value = json.loads(self.manifests()[0].read_text())
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["processes"]["controller"]["returncode"], 9)
        self.state.write_text(json.dumps({"sleep": 10}))
        self.assertNotEqual(self.invoke("--strategy", "0", "--timeout", ".15"), 0)
        self.assertEqual(json.loads(self.manifests()[-1].read_text())["status"], "failed")

    def test_same_block_rerun_preserves_previous_artifacts(self):
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        original = {str(p): p.read_bytes() for p in self.outputs.rglob("*") if p.is_file()}
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        self.assertEqual(len(self.manifests()), 2)
        for name, contents in original.items():
            self.assertEqual(Path(name).read_bytes(), contents)

    def test_neural_requires_explicit_model_or_test_controller(self):
        self.assertNotEqual(self.invoke("--strategy", "3"), 0)
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_completed_manifest_detects_later_log_changes(self):
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        path = self.manifests()[0].parent
        metrics = runner.summary.summarize_run(path)
        self.assertEqual(metrics["generated"], 4)
        with (path / "raw/packet-l3.csv").open("a") as stream:
            stream.write("corrupt\n")
        with self.assertRaisesRegex(ValueError, "hash"):
            runner.summary.summarize_run(path)

    def test_legacy_output_is_protected_and_seeded_inputs_are_unchanged(self):
        initial = {str(p): p.read_bytes() for p in self.inputs.iterdir()}
        self.assertNotEqual(self.invoke("--strategy", "0", "--output-root",
                                        str(self.root / "data/models/new")), 0)
        self.assertFalse((self.root / "calls.jsonl").exists())
        self.assertEqual(initial, {str(p): p.read_bytes() for p in self.inputs.iterdir()})

    def test_sumo_referenced_inputs_cannot_be_omitted_from_hash_contract(self):
        config = json.loads(self.config.read_text())
        config["input_files"].remove("network.net.xml")
        self.config.write_text(json.dumps(config))
        self.assertNotEqual(self.invoke("--strategy", "0"), 0)
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_optional_receive_diagnostics_are_hashed_when_present(self):
        self.state.write_text(json.dumps({"rx_log": True}))
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        manifest = json.loads(self.manifests()[0].read_text())
        self.assertIn("raw/data-rx.csv", manifest["artifact_hashes"])

    def test_enabled_training_logs_are_required_and_sealed(self):
        config = json.loads(self.config.read_text())
        config["training_snapshots"] = True
        self.config.write_text(json.dumps(config))
        self.state.write_text(json.dumps({"training_files": True}))
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        value = json.loads(self.manifests()[0].read_text())
        self.assertIn("raw/training-observations.jsonl", value["artifact_hashes"])
        self.assertIn("raw/face-roles.json", value["artifact_hashes"])
        self.state.write_text("{}")
        self.assertNotEqual(self.invoke("--strategy", "0"), 0,
                            "An enabled collector without its output cannot certify completion")

    def test_validation_only_scope_survives_without_uniform_controller(self):
        config = json.loads(self.config.read_text())
        config["validation_only"] = True
        self.config.write_text(json.dumps(config))
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        value = json.loads(self.manifests()[0].read_text())
        self.assertTrue(value["validation_only"],
                        "Pilot scope belongs to all strategies, not only uniform Gym")

    def test_formal_contract_option_reaches_the_model_controller(self):
        config = json.loads(self.config.read_text())
        config["require_formal_contract"] = True
        self.config.write_text(json.dumps(config))
        self.assertEqual(self.invoke("--strategy", "3", "--model-file", str(self.model)), 0)
        manifest = json.loads(self.manifests()[0].read_text())
        self.assertIn("--require-formal-contract",
                      manifest["processes"]["controller"]["command"])

    def test_snapshot_switch_rejects_non_boolean_before_launch(self):
        config = json.loads(self.config.read_text())
        config["training_snapshots"] = "false"
        self.config.write_text(json.dumps(config))
        self.assertNotEqual(self.invoke("--strategy", "0"), 0)
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_new_decision_marker_requires_a_hashed_log_even_when_empty(self):
        self.state.write_text(json.dumps({"decision_marker": True}))
        self.assertNotEqual(self.invoke("--strategy", "0"), 0)
        self.state.write_text(json.dumps({"decision_marker": True, "decision_log": True}))
        self.assertEqual(self.invoke("--strategy", "0"), 0)
        manifest = json.loads(self.manifests()[-1].read_text())
        self.assertIn("raw/neural-decisions.jsonl", manifest["artifact_hashes"])

    def test_training_completion_counts_must_match_the_sealed_rows(self):
        config = json.loads(self.config.read_text())
        config["training_snapshots"] = True
        self.config.write_text(json.dumps(config))
        self.state.write_text(json.dumps({"training_files": True, "bad_training_count": True}))
        self.assertNotEqual(self.invoke("--strategy", "0"), 0)

    def test_model_controller_decisions_are_requested_sealed_and_counted(self):
        for count in (0, 2):
            with self.subTest(count=count):
                self.state.write_text(json.dumps({"cpp_decision_rows": count}))
                self.assertEqual(self.invoke("--strategy", "3", "--model-file", str(self.model)), 0)
                manifest = json.loads(self.manifests()[-1].read_text())
                command = manifest["processes"]["controller"]["command"]
                self.assertIn("--decision-log", command)
                path = Path(command[command.index("--decision-log") + 1])
                run = self.manifests()[-1].parent
                self.assertEqual(path, run / "raw/controller-decisions.jsonl")
                self.assertEqual(len(path.read_text().splitlines()), count)
                self.assertEqual(manifest["artifact_hashes"]["raw/controller-decisions.jsonl"],
                                 runner.summary.sha256_file(path))

    def test_model_controller_missing_or_mismatched_decisions_cannot_complete(self):
        for changes in ({"missing_controller_decisions": True},
                        {"cpp_decision_rows": 2, "controller_decision_rows": 1}):
            with self.subTest(changes=changes):
                self.state.write_text(json.dumps(changes))
                self.assertNotEqual(self.invoke("--strategy", "3", "--model-file", str(self.model)), 0)
                manifest = json.loads(self.manifests()[-1].read_text())
                self.assertEqual(manifest["status"], "failed")
                self.assertIn("controller decision", manifest["error"].lower())

    def test_uniform_controller_does_not_receive_model_decision_log_option(self):
        fixture = self.root / "scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py"
        controller = self.root / "tools/experiments/test_controller.py"
        controller.parent.mkdir(parents=True)
        controller.write_text(fixture.read_text() +
                              "\nif '--decision-log' in sys.argv: sys.exit(99)\n")
        self.assertEqual(self.invoke("--strategy", "3", "--test-controller"), 0)
        manifest = json.loads(self.manifests()[-1].read_text())
        self.assertNotIn("--decision-log", manifest["processes"]["controller"]["command"])
        self.assertNotIn("raw/controller-decisions.jsonl", manifest["artifact_hashes"])

    def test_sigterm_seals_failure_and_kills_only_owned_process_groups(self):
        self.state.write_text(json.dumps({"sleep": 30, "spawn_descendant": True}))
        script = (
            "import importlib.util, pathlib, sys; "
            "spec=importlib.util.spec_from_file_location('runner', sys.argv[1]); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "sys.exit(module.main(sys.argv[3:], root=pathlib.Path(sys.argv[2])))")
        command = [sys.executable, "-c", script, str(Path(runner.__file__)),
                   str(self.root), "--config", str(self.config),
                   "--output-root", str(self.outputs), "--block-id", "interrupted",
                   "--strategy", "3", "--model-file", str(self.model),
                   "--python", sys.executable, "--timeout", "60"]
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        identities = None
        try:
            deadline = time.monotonic() + 5
            identity_path = self.root / "process-ids.json"
            while not identity_path.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(identity_path.exists(), "The fake simulation must actually start")
            identities = json.loads(identity_path.read_text())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1, (stdout, stderr))
            manifest = json.loads(self.manifests()[0].read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("SIGTERM", manifest["error"])
            self.assertEqual(set(manifest["processes"]), {"controller", "simulation"})
            self.assertTrue(all(record["returncode"] is not None
                                for record in manifest["processes"].values()))
            self.assertIsNone(unrelated.poll(), "Unrelated processes must survive cancellation")
            for pid in identities.values():
                stat = Path("/proc") / str(pid) / "stat"
                self.assertTrue(not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z",
                                "An owned simulation descendant survived SIGTERM cleanup")
        finally:
            # Also reap the intentionally orphaned fixture when testing the old runner.
            if identities is not None:
                try:
                    os.killpg(identities["leader"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            controller_pid = self.root / "controller-pid"
            if controller_pid.exists():
                try:
                    os.killpg(int(controller_pid.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            runner.stop_group(process)
            runner.stop_group(unrelated)
            process.stdout.close()
            process.stderr.close()

    def test_source_snapshot_freezes_trace_configuration_dependencies(self):
        traces = self.root / "contrib/vndn-nn-rd/traces"
        for relative in ("circle-simple/settings.xml",
                         "grid-vanet-test/settings.xml",
                         "fgfxf-spider-map/settings.xml",
                         "grid-vanet-test/sim.sumocfg",
                         "circle-simple/circle.sumo.cfg"):
            with self.subTest(relative=relative):
                dependency = traces / relative
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_text("<configuration version='1'/>")
                before = runner.source_snapshot(self.root)["sha256"]
                dependency.write_text("<configuration version='2'/>")
                self.assertNotEqual(
                    before, runner.source_snapshot(self.root)["sha256"],
                    "Actual trace configuration changes must invalidate the source snapshot")
        before = runner.source_snapshot(self.root)["sha256"]
        (traces / "circle-simple/plot.png").write_bytes(b"not a runtime dependency")
        self.assertEqual(before, runner.source_snapshot(self.root)["sha256"])


class BinaryEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = "vndn-circle-simulator"
        binary = self.root / "build/scratch" / self.target / self.target
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"fixture executable")
        self.module = self.root / "build/lib/libns3-dev-vndn-nn-rd-debug.so"
        self.module.parent.mkdir()
        self.module.write_bytes(b"research module version 1")
        self.unused = self.module.with_name("libns3-dev-ndnSIM-unused.so")
        self.unused.write_bytes(b"unreferenced, must not be claimed as loaded")
        self.dependency = self.root / "system library/libdependency.so.1"
        self.dependency.parent.mkdir()
        self.dependency.write_bytes(b"transitive dependency")
        self.alias = self.module.with_name("module-alias.so")
        self.alias.symlink_to(self.module)
        cache = self.root / "build/c4che/_cache.py"
        cache.parent.mkdir()
        cache.write_text("NS3_MODULE_PATH = {!r}\n".format([str(self.module.parent)]))

    def output(self):
        return (
            "\tlinux-vdso.so.1 (0x000001)\n"
            "\tlibns3-dev-vndn-nn-rd-debug.so => {} (0x000002)\n"
            "\tlibdependency.so.1 => {} (0x000003)\n"
        ).format(self.alias, self.dependency)

    def test_actual_resolved_dependencies_are_sealed_and_follow_symlinks(self):
        result = subprocess.CompletedProcess(["ldd"], 0, self.output(), "")
        with mock.patch.object(runner.subprocess, "run", return_value=result) as probe, \
                mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/inherited/lib"}):
            first = runner.binary_evidence(self.root, self.target)
            expected = {str(path): runner.summary.sha256_file(path)
                        for path in (self.module, self.dependency)}
            self.assertEqual(first["shared_libraries"], expected,
                             "Hash actual ldd dependencies, including build/lib and transitive libraries")
            environment = probe.call_args.kwargs["env"]
            self.assertEqual(environment["LD_LIBRARY_PATH"],
                             str(self.module.parent) + os.pathsep + "/inherited/lib")
            self.assertEqual(environment["LC_ALL"], "C")
            self.module.write_bytes(b"research module version 2")
            second = runner.binary_evidence(self.root, self.target)
            self.assertNotEqual(first["shared_libraries"], second["shared_libraries"])

    def test_missing_or_unusable_ldd_evidence_cannot_certify_a_run(self):
        for output, code in (
                ("\tlibns3-dev-vndn-nn-rd-debug.so => not found\n", 0),
                ("", 0), ("not a dynamic executable\n", 1)):
            with self.subTest(output=output), mock.patch.object(
                    runner.subprocess, "run",
                    return_value=subprocess.CompletedProcess(["ldd"], code, output, "")):
                with self.assertRaisesRegex(ValueError, "ldd|dependenc"):
                    runner.binary_evidence(self.root, self.target)


if __name__ == "__main__":
    unittest.main()
