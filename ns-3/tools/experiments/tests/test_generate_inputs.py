import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "generate_inputs.py"
SPEC = importlib.util.spec_from_file_location("generate_inputs", str(SCRIPT))
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
NS3 = SCRIPT.parents[2]


class GenerateInputsTests(unittest.TestCase):
    def generate(self, directory, scenario="circle", **overrides):
        options = dict(scenario=scenario, output_dir=directory, vehicles=3,
                       speed_kmh=30, requests=17, measurement_start=5,
                       measurement_duration=300, drain_seconds=3.5, seed=7,
                       ns3_root=NS3)
        options.update(overrides)
        return GENERATOR.generate_inputs(**options)

    def test_all_scenarios_have_exact_balanced_requests_and_connected_long_routes(self):
        for scenario in ("circle", "grid", "spidermap"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as root:
                output = Path(root) / "inputs"
                result = self.generate(output, scenario)
                self.assertIn("experiment_config", result,
                              "Generator must publish its experiment configuration")
                config_path = Path(result["experiment_config"])
                config = json.loads(config_path.read_text())
                routes_path = (config_path.parent / config["route_file"]).resolve()
                sumo_path = (config_path.parent / config["sumo_config"]).resolve()
                request_path = (config_path.parent / config["request_plan"]).resolve()
                routes = ET.parse(routes_path).getroot()
                cars = routes.findall("vehicle")
                self.assertEqual(len(cars), 3)
                ids = [car.attrib["id"] for car in cars]
                self.assertEqual(len(set(ids)), 3)
                plan = json.loads(request_path.read_text())["requests"]
                self.assertEqual(len(plan), 17)
                counts = {vehicle: 0 for vehicle in ids}
                seen = set()
                for request in plan:
                    self.assertIn(request["vehicle_id"], ids)
                    key = (request["vehicle_id"], request["sequence"])
                    self.assertNotIn(key, seen)
                    seen.add(key)
                    counts[request["vehicle_id"]] += 1
                    self.assertIsInstance(request["send_time_ns"], int)
                    self.assertGreaterEqual(request["send_time_ns"], 5_000_000_000)
                    self.assertLess(request["send_time_ns"], 305_000_000_000)
                self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
                sumo = ET.parse(sumo_path).getroot()
                referenced_route = (sumo_path.parent /
                                    sumo.find("input/route-files").attrib["value"]).resolve()
                self.assertEqual(referenced_route, routes_path)
                net_path = (sumo_path.parent / sumo.find("input/net-file").attrib["value"]).resolve()
                net = ET.parse(net_path).getroot()
                edges = {edge.attrib["id"]: edge for edge in net.findall("edge")
                         if edge.attrib.get("function") != "internal"}
                connections = {(item.attrib["from"], item.attrib["to"])
                               for item in net.findall("connection")}
                for car in cars:
                    route = car.find("route").attrib["edges"].split()
                    for first, second in zip(route, route[1:]):
                        self.assertIn((first, second), connections)
                    length = sum(float(edges[item].find("lane").attrib["length"])
                                 for item in route)
                    self.assertGreater(length, (30 / 3.6) * 308.5,
                                       "Even free-flow vehicles must remain until drain end")
                for vehicle_type in routes.findall("vType"):
                    self.assertAlmostEqual(float(vehicle_type.attrib["maxSpeed"]), 30 / 3.6)
                    self.assertEqual(vehicle_type.attrib["speedFactor"], "1")
                    self.assertEqual(vehicle_type.attrib["speedDev"], "0")

    def test_same_seed_reproduces_requests_and_vehicle_routes(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.generate(Path(root) / "first")
            second = self.generate(Path(root) / "second")
            self.assertIn("experiment_config", first)
            self.assertIn("experiment_config", second)
            paths = [Path(item["experiment_config"]) for item in (first, second)]
            configs = [json.loads(path.read_text()) for path in paths]
            for field in ("request_plan", "route_file"):
                contents = [(path.parent / config[field]).read_bytes()
                            for path, config in zip(paths, configs)]
                self.assertEqual(contents[0], contents[1])

    def test_remaining_route_survives_drain_after_free_departure_position(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            source = project / "contrib/vndn-nn-rd/traces/circle-simple"
            source.mkdir(parents=True)
            (source / "circle.net.xml").write_text(
                '<net><edge id="a"><lane length="100"/></edge>'
                '<edge id="b"><lane length="100"/></edge>'
                '<connection from="a" to="b"/><connection from="b" to="a"/></net>')
            (source / "circle.rou.xml").write_text(
                '<routes><route id="loop" edges="a b"/>'
                '<vehicle id="original" route="loop"/></routes>')
            result = self.generate(
                Path(root) / "inputs", vehicles=1, requests=1, speed_kmh=36,
                measurement_start=1, measurement_duration=13.5, drain_seconds=3.5,
                ns3_root=project)
            directory = Path(result["experiment_config"]).parent
            car = ET.parse(directory / "routes.rou.xml").getroot().find("vehicle")
            self.assertEqual(car.attrib["departPos"], "free")
            route = car.find("route").attrib["edges"].split()
            # A free insertion near the end of the first 100 m edge can skip
            # that edge. Remaining distance must exceed 10 m/s * 18 s.
            remaining_length = (len(route) - 1) * 100
            self.assertGreater(remaining_length, 180,
                               "Account for the skipped first edge at free insertion")

    def test_reject_existing_output_without_overwriting(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "inputs"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("keep")
            with self.assertRaises(FileExistsError):
                self.generate(output)
            self.assertEqual(sentinel.read_text(), "keep")

    def test_reject_invalid_budgets_and_time_windows_before_creating_output(self):
        for change in ({"vehicles": 0}, {"requests": 2}, {"speed_kmh": 0},
                       {"measurement_duration": 0}, {"drain_seconds": 2.9},
                       {"seed": 0}, {"speed_kmh": float("nan")}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                output = Path(root) / "inputs"
                with self.assertRaises(ValueError):
                    self.generate(output, **change)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
