"""Numerical mapping and real headless-rendering checks for the 30-figure set."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaign_test_support import create_campaign


DIRECTORY = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


aggregate = module("aggregate_campaign")
plot = module("plot_campaign")


class FigureTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        manifest = create_campaign(self.root / "input")
        self.analysis = self.root / "analysis"
        aggregate.aggregate_campaign(manifest, self.analysis)

    def test_full_set_renders_30_unique_numbered_figures_and_exports_all_formats(self):
        output = self.root / "figures"
        result = plot.plot_campaign(self.analysis, output)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["validation_only"])
        self.assertEqual(len(result["figures"]), 30)
        self.assertEqual(len({item["id"] for item in result["figures"]}), 30)
        for item in result["figures"]:
            with self.subTest(figure=item["id"]):
                for suffix in ("pdf", "svg", "png"):
                    artifact = output / item["files"][suffix]
                    self.assertTrue(artifact.is_file())
                    self.assertGreater(artifact.stat().st_size, 100)
                svg = (output / item["files"]["svg"]).read_text()
                self.assertIn("VALIDATION ONLY", svg)
                self.assertTrue(item["caption_en"])
                self.assertTrue(item["caption_zh"])
        self.assertEqual(sum(f["kind"] == "scan" for f in result["figures"]), 20)
        self.assertEqual(sum(f["kind"] == "legacy_3d" for f in result["figures"]), 3)
        self.assertEqual(sum(f["kind"] == "legacy_box" for f in result["figures"]), 3)
        self.assertEqual(sum(f["kind"] == "confusion" for f in result["figures"]), 3)
        self.assertEqual(sum(f["kind"] == "traffic" for f in result["figures"]), 1)
        self.assertEqual(sum(f["kind"] == "learning" for f in result["diagnostics"]), 3)
        self.assertEqual(sum(f["kind"] == "decomposition" for f in result["diagnostics"]), 2)
        self.assertEqual(sum(f["kind"] == "mobility" for f in result["diagnostics"]), 1)

    def test_tampered_table_and_incomplete_analysis_refuse_paper_output(self):
        with (self.analysis / "baseline-requests.csv").open("a") as stream:
            stream.write("tampered")
        with self.assertRaisesRegex(ValueError, "hash"):
            plot.plot_campaign(self.analysis, self.root / "out")

    def test_fixed_time_bins_keep_timeouts_out_of_rtt_and_preserve_empty_bins(self):
        data = [
            {"send_ns": "1000000000", "terminal": "DATA", "rtt_ms": "10"},
            {"send_ns": "1500000000", "terminal": "TIMEOUT", "rtt_ms": ""},
            {"send_ns": "3000000000", "terminal": "DATA", "rtt_ms": "30"},
        ]
        result = plot.time_bins(data, 1000000000, 4000000000, 1)
        self.assertEqual([r["successes"] for r in result], [1, 0, 1])
        self.assertEqual([r["failures"] for r in result], [1, 0, 0])
        self.assertEqual([r["mean_success_rtt_ms"] for r in result], [10, None, 30])

    def test_raw_sources_changed_after_aggregation_are_rejected_before_render(self):
        campaign = json.loads((self.root / "input/campaign.json").read_text())
        run = Path(campaign["blocks"][0]["runs"]["0"]["path"])
        with (run / "raw/request-events.csv").open("a") as stream:
            stream.write("tampered")
        with self.assertRaisesRegex(ValueError, "hash"):
            plot.load_analysis(self.analysis)

    def test_isolated_success_time_bin_remains_visible_in_3d_and_label_fits(self):
        result = plot.load_analysis(self.analysis)
        output = self.root / "inspected-3d"
        output.mkdir()
        checked = []

        def inspect(figure, *args, **kwargs):
            for axis in figure.axes:
                if getattr(axis, "name", "") != "3d":
                    continue
                self.assertEqual(len(axis.lines), 4)
                for line in axis.lines:
                    # One successful bin surrounded by missing bins has no
                    # drawable line segment: it needs a visible point marker.
                    self.assertNotIn(line.get_marker(), (None, "None", "", " "))
                    self.assertGreater(line.get_markersize(), 0)
                figure.canvas.draw()
                labels = [text for text in figure.texts if
                          text.get_text() == "Mean successful RTT (ms)"]
                labels += [axis.zaxis.label] if axis.zaxis.label.get_text() else []
                self.assertTrue(labels)
                for label in labels:
                    bounds = label.get_window_extent(figure.canvas.get_renderer())
                    self.assertGreaterEqual(bounds.x0, figure.bbox.x0)
                    self.assertLessEqual(bounds.x1, figure.bbox.x1)
                checked.append(True)
            plot.plt.close(figure)
            return {}

        with patch.object(plot, "save_figure", side_effect=inspect):
            plot.legacy_figures(result, self.analysis, output)
        self.assertEqual(len(checked), 3)


if __name__ == "__main__":
    unittest.main()
