"""Quick draft design and honest two-run descriptive figures; no simulation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaign_test_support import create_campaign, digest, dump


DIRECTORY = Path(__file__).resolve().parents[1]
PROFILE = "quick-draft-v1"


def module(name):
    spec = importlib.util.spec_from_file_location("quick_figures_" + name,
                                                DIRECTORY / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


aggregate = module("aggregate_campaign")
plot = module("plot_campaign")


def formal_manifest():
    parameters = [(10, 30, 6000), (10, 30, 1500), (10, 30, 12000),
                  (10, 10, 6000), (10, 50, 6000), (5, 30, 3000),
                  (15, 30, 9000), (20, 30, 12000)]
    ids = {row: "baseline" if index == 0 else "condition-" + str(index)
           for index, row in enumerate(parameters)}
    scans = dict(interest=[ids[10, 30, k] for k in (1500, 6000, 12000)],
                 speed=[ids[10, v, 6000] for v in (10, 30, 50)],
                 vehicles=[ids[n, 30, n * 600] for n in (5, 10, 15, 20)])
    value = dict(schema_version=1, campaign_id="quick-test", validation_only=False,
                 source_sha256="a" * 64, design_profile=PROFILE,
                 repetitions=[52001, 52002], bootstrap=dict(resamples=10000, seed=61021),
                 baseline_condition_id="baseline", scans=scans,
                 figure_ids=aggregate.expected_figure_ids(scans),
                 conditions=[dict(id=ids[row], vehicles=row[0], speed_kmh=row[1],
                                  requests=row[2]) for row in parameters],
                 models={scene: {} for scene in aggregate.SCENARIOS},
                 model_evaluations={scene: {} for scene in aggregate.SCENARIOS}, blocks=[])
    for scene in aggregate.SCENARIOS:
        for cid in ids.values():
            for seed in value["repetitions"]:
                block_id = "{}-{}-{}".format(scene, cid, seed)
                value["blocks"].append(dict(scene=scene, condition_id=cid, seed_family=seed,
                    block_id=block_id, runs={str(strategy): dict(
                        path="/fixture/{}/{}".format(block_id, strategy),
                        manifest_sha256="b" * 64) for strategy in range(4)}))
    return value


class QuickDesignTest(unittest.TestCase):
    def test_real_two_seed_192_run_design_is_accepted(self):
        value = formal_manifest()
        conditions, blocks = aggregate.validate_campaign(value)
        self.assertFalse(value["validation_only"])
        self.assertEqual(len(conditions), 8)
        self.assertEqual(len(blocks), 48)
        self.assertEqual(sum(len(b["runs"]) for b in blocks.values()), 192)
        self.assertEqual(len(value["figure_ids"]), 25)

    def test_incomplete_wrong_seed_or_changed_factor_is_rejected(self):
        for mutate in (
                lambda v: v["blocks"].pop(),
                lambda v: v["blocks"][0]["runs"].pop("2"),
                lambda v: v.update(repetitions=[52001, 52003]),
                lambda v: v.update(repetitions=[52001]),
                lambda v: v["conditions"][-1].update(requests=30000),
                lambda v: v["bootstrap"].update(resamples=100),
                lambda v: v["figure_ids"].pop()):
            value = formal_manifest()
            mutate(value)
            with self.assertRaises(ValueError):
                aggregate.validate_campaign(value)

    def test_quick_matrix_cannot_relabel_the_full_or_compact_design(self):
        for profile in ("full", "compact-exploratory-v1"):
            value = formal_manifest()
            value["design_profile"] = profile
            with self.assertRaises(ValueError):
                aggregate.validate_campaign(value)

    def test_formal_run_must_use_the_declared_120_second_window(self):
        # Isolate run auditing from fixture generation: valid_run's event rows are
        # not claimed to represent a full formal campaign in this unit test.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = create_campaign(root / "input")
            campaign = json.loads(path.read_text())
            campaign.update(design_profile=PROFILE, validation_only=False)
            block = campaign["blocks"][0]
            run = Path(block["runs"]["0"]["path"])
            manifest = json.loads((run / "manifest.json").read_text())
            manifest["validation_only"] = False
            config = json.loads((run / "experiment.json").read_text())
            config.update(measurement_start_s=20, measurement_end_s=140, drain_end_s=143.5)
            network = root / "network.net.xml"
            network.write_text("auditing fixture", encoding="utf-8")
            manifest["input_hashes"][str(network)] = digest(network)
            inputs_path = Path(config["input_summary"])
            inputs = json.loads(inputs_path.read_text())
            for vehicle in inputs["vehicles"]:
                vehicle.update(source_route_index=0, route_family_index=0, route_start_offset=0)
            dump(inputs_path, inputs)
            manifest["input_hashes"][str(inputs_path)] = digest(inputs_path)
            metrics = json.loads((run / "run-metrics.json").read_text())
            arguments = (run, manifest, config, metrics, campaign, block,
                         campaign["conditions"][0], "0", root)
            self.assertEqual(aggregate.audit_run(*arguments)["window"], [20, 140, 143.5])
            for start, end, drain in ((20, 320, 323.5), (5, 125, 128.5), (20, 140, 144)):
                config.update(measurement_start_s=start, measurement_end_s=end, drain_end_s=drain)
                with self.assertRaisesRegex(ValueError, "quick.*window"):
                    aggregate.audit_run(*arguments)


class QuickFigureTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def analysis(self):
        manifest = create_campaign(self.root / "input")
        value = json.loads(manifest.read_text())
        value["design_profile"] = PROFILE
        del value["scans"]["vehicles_fixed_k"]
        value["figure_ids"] = aggregate.expected_figure_ids(value["scans"])
        dump(manifest, value)
        result = aggregate.aggregate_campaign(manifest, self.root / "analysis")
        return result

    def test_every_scan_uses_observed_runs_and_sd(self):
        result = self.analysis()
        points = plot.lookup_points(result)
        output = self.root / "inspected"
        output.mkdir()
        calls = []

        def draw(axis, x, records, strategy, descriptive=False):
            calls.append(descriptive)
            return original(axis, x, records, strategy, descriptive)

        def discard(figure, *args, **kwargs):
            plot.plt.close(figure)
            return {}

        original = plot._draw_points
        with patch.object(plot, "_draw_points", side_effect=draw), \
                patch.object(plot, "save_figure", side_effect=discard):
            plot.scan_figures(result, output, points)
        self.assertEqual(len(calls), 15 * 3 * 4)
        self.assertTrue(all(calls))

    def test_traffic_uses_raw_run_points_and_sd_instead_of_bootstrap_bars(self):
        result = self.analysis()
        points = plot.lookup_points(result)
        for value in points.values():
            if value["metric"] == "network_mbit":
                value.update(estimate=10., run_values=[8., 12.], run_sd=2.82842712474619,
                             ci_low=1., ci_high=19.)

        def inspect(figure, output, identifier, kind, data, english, chinese, metadata):
            self.assertIn("sample standard deviation", english)
            for axis in figure.axes:
                scatter = [c for c in axis.collections if isinstance(c, plot.matplotlib.collections.PathCollection)]
                self.assertEqual(len(scatter), 4)
                self.assertTrue(all(list(c.get_offsets()[:, 1]) == [8., 12.] for c in scatter))
                bars = [c for c in axis.collections if isinstance(c, plot.matplotlib.collections.LineCollection)]
                self.assertEqual(len(bars), 4)
                for bar in bars:
                    self.assertAlmostEqual(bar.get_segments()[0][0][1], 10 - 2.82842712474619)
                    self.assertAlmostEqual(bar.get_segments()[0][1][1], 10 + 2.82842712474619)
            plot.plt.close(figure)
            return {}

        with patch.object(plot, "save_figure", side_effect=inspect):
            plot.traffic_figure(result, self.root, points)

    def test_all_25_figures_render_with_two_run_draft_labels_and_readable_index(self):
        result = self.analysis()
        output = self.root / "figures"
        report = plot.plot_campaign(self.root / "analysis", output)
        self.assertEqual(report["design_profile"], PROFILE)
        self.assertTrue(report["validation_only"])
        self.assertEqual(len(report["figures"]), 25)
        self.assertEqual(sum(row["kind"] == "scan" for row in report["figures"]), 15)
        for row in report["figures"]:
            self.assertIn("Exploratory draft", row["caption_en"])
            self.assertIn("n=2", row["caption_en"])
            for suffix in ("pdf", "svg", "png"):
                self.assertGreater((output / row["files"][suffix]).stat().st_size, 100)
            svg = (output / row["files"]["svg"]).read_text()
            self.assertIn("EXPLORATORY DRAFT", svg)
            self.assertIn("n=2", svg)
            self.assertIn("VALIDATION ONLY", svg)
            if row["kind"] in ("scan", "traffic"):
                self.assertIn("sample standard deviation", row["caption_en"])
                self.assertIn("not a confidence interval", row["caption_en"])
        index = (output / "index.html").read_text()
        self.assertIn("Exploratory draft", index)
        self.assertIn("n=2", index)
        self.assertEqual(index.count('data-figure-id="'), 25)
        for row in report["figures"]:
            self.assertIn(row["files"]["png"], index)
            self.assertIn(row["files"]["pdf"], index)
        self.assertTrue(any("two" in note and "independent" in note for note in result["notes"]))


if __name__ == "__main__":
    unittest.main()
