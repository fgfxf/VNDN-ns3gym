"""Behavioral coverage for opt-in period/resource experiment recording."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fixture_module = load("followup_runner_fixture", HERE / "test_run_experiment.py")
runner = fixture_module.runner
generator = load("followup_generator", HERE.parent / "generate_inputs.py")

class FollowupInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.RunExperimentTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def configure(self, **values):
        config = json.loads(self.fixture.config.read_text())
        config.update(values)
        self.fixture.config.write_text(json.dumps(config))

    def test_period_rejects_invalid_types_and_overflow_before_launch(self):
        for value in (0, -1, True, 20.5, "20", 2147483648):
            with self.subTest(value=value):
                self.configure(hello_interval_ms=value)
                with self.assertRaisesRegex(ValueError, "hello_interval_ms"):
                    runner.prepare_inputs(self.fixture.config)

    def test_resource_switch_rejects_non_boolean_before_launch(self):
        for value in (1, "false", None):
            with self.subTest(value=value):
                self.configure(resource_observations=value)
                with self.assertRaisesRegex(ValueError, "resource_observations"):
                    runner.prepare_inputs(self.fixture.config)

    def test_missing_enabled_resource_files_cannot_complete(self):
        self.configure(resource_observations=True)
        self.assertNotEqual(self.fixture.invoke("--strategy", "0"), 0)

    def add_resources(self, *, rows=1, period=40, reported=1):
        original = runner.run_processes
        def simulate(*args, **kwargs):
            result = original(*args, **kwargs)
            raw = args[2] / "raw"
            (raw / "rsu-state.csv").write_text(
                "time_ns,event,rsu_id,present_vehicles,cache_vehicle_entries,cache_name_entries,cache_edges,reverse_cache_edges,mac_entries,next_rsu_entries,history_vehicles,history_records,history_timestamp_records\n" +
                "0,START,0,0,0,0,0,0,0,0,0,0,0\n" * rows)
            (raw / "hello-payloads.csv").write_text(
                "time_ns,obu_node_id,rsu_id,category,content_bytes,wire_bytes,cache_items,added_items,removed_items\n" +
                "1,2,0,registration,40,70,0,0,0\n" * rows)
            marker = json.loads((raw / "recorder-complete.json").read_text())
            marker.update(resource_observations=True, rsu_state_rows=reported, hello_payload_rows=reported)
            (raw / "recorder-complete.json").write_text(json.dumps(marker))
            effective = json.loads((raw / "effective-experiment-config.json").read_text())
            effective.update(resource_observations=True, hello_interval_ms=period,
                             rsu_timeout_ms=period * 2, obu_neighbor_timeout_ms=2000)
            (raw / "effective-experiment-config.json").write_text(json.dumps(effective))
            return result
        return patch.object(runner, "run_processes", side_effect=simulate)

    def test_resource_artifacts_are_sealed_when_valid(self):
        self.configure(resource_observations=True, hello_interval_ms=40)
        with self.add_resources():
            self.assertEqual(self.fixture.invoke("--strategy", "0"), 0)
        manifest = json.loads(self.fixture.manifests()[0].read_text())
        self.assertIn("raw/rsu-state.csv", manifest["artifact_hashes"])
        self.assertIn("raw/hello-payloads.csv", manifest["artifact_hashes"])

    def test_resource_count_mismatch_cannot_complete(self):
        self.configure(resource_observations=True, hello_interval_ms=40)
        with self.add_resources(reported=2):
            self.assertNotEqual(self.fixture.invoke("--strategy", "0"), 0)

    def test_cpp_period_mismatch_cannot_complete(self):
        self.configure(resource_observations=True, hello_interval_ms=80)
        with self.add_resources(period=40):
            self.assertNotEqual(self.fixture.invoke("--strategy", "0"), 0)


class FollowupGeneratorTests(unittest.TestCase):
    def test_period_is_opt_in_and_preserves_paired_mobility_and_requests(self):
        for scenario in ("circle", "grid", "spidermap"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                outputs = []
                for period in (None, 20, 40, 80, 160):
                    output = Path(temp) / str(period)
                    generator.generate_inputs(scenario=scenario, output_dir=output, vehicles=5,
                        speed_kmh=30, requests=30, measurement_start=20, measurement_duration=120,
                        seed=84001, hello_interval_ms=period,
                        resource_observations=None if period is None else True)
                    config = json.loads((output / "experiment-template.json").read_text())
                    info = json.loads((output / "input-summary.json").read_text())
                    if period is None:
                        self.assertNotIn("hello_interval_ms", config)
                        self.assertNotIn("resource_observations", config)
                    else:
                        self.assertEqual(config["hello_interval_ms"], period)
                        self.assertTrue(config["resource_observations"])
                        self.assertEqual(info["rsu_timeout_ms"], 2 * period)
                        self.assertEqual(info["obu_neighbor_timeout_ms"], 2000)
                    outputs.append(output)
                for name in ("network.net.xml", "routes.rou.xml", "simulation.sumocfg", "request-plan.json"):
                    self.assertEqual(len({(output / name).read_bytes() for output in outputs}), 1)

    def test_generator_rejects_invalid_deployment_before_creating_files(self):
        with tempfile.TemporaryDirectory() as temp:
            for index, options in enumerate((dict(hello_interval_ms=True), dict(hello_interval_ms=0),
                    dict(hello_interval_ms=2147483648), dict(resource_observations="true"))):
                output = Path(temp) / str(index)
                with self.assertRaises(ValueError):
                    generator.generate_inputs(scenario="circle", output_dir=output, vehicles=5,
                                              speed_kmh=30, requests=30, **options)
                self.assertFalse(output.exists())

if __name__ == "__main__":
    unittest.main()
