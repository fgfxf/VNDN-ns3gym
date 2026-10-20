import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


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
        helper_dir = str(Path(__file__).resolve().parent)
        fake_waf = """#!{python}
import json, os, pathlib, shlex, sys, time
sys.path.insert(0, {helper_dir!r})
from experiment_test_support import valid_run
root=pathlib.Path.cwd()
state=json.loads((root/'state.json').read_text())
args=shlex.split(sys.argv[sys.argv.index('--run')+1])
config=pathlib.Path(next(x.split('=',1)[1] for x in args if x.startswith('--experiment-config=')))
run=config.parent
with (root/'calls.jsonl').open('a') as output:
 output.write(json.dumps({{'args':sys.argv[1:],'jobs':os.environ.get('JOBS'),'run':str(run)}})+'\\n')
if state.get('sleep'): time.sleep(state['sleep'])
valid_run(run,preserve_config=True)
if state.get('no_marker'): (run/'raw/recorder-complete.json').unlink()
if state.get('rx_log'): (run/'raw/data-rx.csv').write_text('opaque receive diagnostics\\n')
(run/'controller-stop').write_text('done')
binary=root/'build/scratch'/args[0]/args[0]
binary.parent.mkdir(parents=True,exist_ok=True)
binary.write_bytes(b'fake executable artifact')
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
if state.get('controller_rc'): sys.exit(state['controller_rc'])
run=pathlib.Path(os.environ['VNDN_EXPERIMENT_RUN_DIR'])
while not (run/'controller-stop').exists(): time.sleep(.01)
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


if __name__ == "__main__":
    unittest.main()
