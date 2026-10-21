import importlib.util
from collections import Counter
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

    def test_seven_rsu_routes_cover_roads_beyond_the_legacy_source_subset(self):
        for scene in ("grid", "spidermap"):
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as root:
                result = self.generate(Path(root) / "inputs", scene, vehicles=5)
                folder = Path(result["experiment_config"]).parent
                network = ET.parse(folder / "network.net.xml").getroot()
                normal = {e.attrib["id"] for e in network.findall("edge")
                          if e.attrib.get("function") != "internal"}
                cars = ET.parse(folder / "routes.rou.xml").getroot().findall("vehicle")
                for car in cars:
                    self.assertEqual(set(car.find("route").attrib["edges"].split()), normal,
                                     "Each coverage route must span the road graph, not only old routes")

    def test_coverage_tours_avoid_immediate_uturns_at_short_junctions(self):
        for scene in ("grid", "spidermap"):
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as root:
                result = self.generate(Path(root) / "inputs", scene, vehicles=40, requests=60000,
                                       speed_kmh=50, measurement_start=20, seed=10009)
                folder = Path(result["experiment_config"]).parent
                net = ET.parse(folder / "network.net.xml").getroot()
                turns = {(item.attrib["from"], item.attrib["to"]): item.attrib["dir"]
                         for item in net.findall("connection")}
                report = json.loads(Path(result["input_summary"]).read_text())
                for cycle in report["route_families"]:
                    for first, second in zip(cycle, cycle[1:] + cycle[:1]):
                        self.assertNotEqual(
                            turns[first, second], "t",
                            "Coverage tours must not force immediate reversals through narrow U-turns")
                self.assertEqual(report["route_policy"], "road-coverage-v2")

    def test_route_families_are_balanced_even_for_low_vehicle_counts(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.generate(Path(root) / "inputs", "spidermap", vehicles=5)
            report = json.loads(Path(result["input_summary"]).read_text())
            self.assertEqual(report.get("route_policy"), "road-coverage-v2")
            family_count = report["route_family_count"]
            counts = [sum(v["route_family_index"] == i for v in report["vehicles"])
                      for i in range(family_count)]
            self.assertLessEqual(max(counts) - min(counts), 1)
            self.assertGreaterEqual(family_count, 2)

    def test_circle_departures_use_one_physical_cycle_not_repeated_source_indices(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.generate(
                Path(root) / "inputs", "circle", vehicles=40, requests=60000,
                speed_kmh=50, measurement_start=20, seed=10009)
            report = json.loads(Path(result["input_summary"]).read_text())
            cycle = report["route_families"][0]
            self.assertEqual(len(cycle), 16,
                             "Six identical laps must not create 96 distinct insertion positions")
            self.assertEqual(report["route_policy"], "source-cycle-v2")
            vehicles = ET.parse(Path(result["experiment_config"]).parent /
                                "routes.rou.xml").getroot().findall("vehicle")
            starts = Counter(v.find("route").attrib["edges"].split()[0] for v in vehicles)
            self.assertEqual(set(starts), set(cycle))
            self.assertLessEqual(max(starts.values()), 4,
                                 "Forty vehicles must not alias onto seven starts on short e4")

    def test_cycle_reduction_preserves_nonperiodic_revisits_and_legal_turns(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            source = project / "contrib/vndn-nn-rd/traces/circle-simple"
            source.mkdir(parents=True)
            (source / "circle.net.xml").write_text(
                '<net><edge id="a"><lane length="100"/></edge>'
                '<edge id="b"><lane length="100"/></edge>'
                '<edge id="c"><lane length="100"/></edge>'
                '<connection from="a" to="b"/><connection from="b" to="a"/>'
                '<connection from="a" to="c"/><connection from="c" to="a"/></net>')
            for name, route in (("repeated", "a b a c a b a c"), ("one", "a b a c")):
                (source / "circle.rou.xml").write_text(
                    '<routes><route id="loop" edges="{}"/>'
                    '<vehicle id="original" route="loop"/></routes>'.format(route))
                result = self.generate(Path(root) / name, ns3_root=project)
                report = json.loads(Path(result["input_summary"]).read_text())
                self.assertEqual(report["route_families"], [["a", "b", "a", "c"]],
                                 "Reduce only whole repeated periods, never remove individual revisits")

    def test_speed_scan_reuses_exact_requests_and_route_prefixes(self):
        for scene in ("circle", "grid", "spidermap"):
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as root:
                paths = []
                for speed in (10, 50):
                    result = self.generate(Path(root) / str(speed), scene, speed_kmh=speed)
                    paths.append(Path(result["experiment_config"]).parent)
                self.assertEqual((paths[0] / "request-plan.json").read_bytes(),
                                 (paths[1] / "request-plan.json").read_bytes())
                cars = [ET.parse(p / "routes.rou.xml").getroot().findall("vehicle") for p in paths]
                for slow, fast in zip(*cars):
                    a, b = (c.find("route").attrib["edges"].split() for c in (slow, fast))
                    self.assertEqual(a, b[:len(a)])

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
