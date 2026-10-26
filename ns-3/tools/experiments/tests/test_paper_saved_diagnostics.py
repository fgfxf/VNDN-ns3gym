"""Numeric and rendering contracts for diagnostics from frozen figure tables."""
import csv
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex

DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "paper_saved_diagnostics", DIRECTORY / "paper_saved_diagnostics.py")
plot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plot)


def write_rows(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class SavedDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.source.mkdir()
        self.output = Path(self.temp.name) / "output"
        self.output.mkdir()
        self.figures = {}
        self.decomposition, self.mobility, self.speeds = [], [], []
        for scene in plot.SCENES:
            for kind in ("extra", "control"):
                for category in ("absent", "ordinary"):
                    for strategy in range(4):
                        self.decomposition.append(dict(
                            scene=scene, strategy=strategy, kind=kind, category=category,
                            mean=0 if category == "absent" else strategy + .5,
                            repetitions=2,
                            unit="Mbit" if kind == "control" else "application submissions"))
            for setting in (15, 60):
                for seed, delta in ((1, -2), (2, 2)):
                    self.mobility.append(dict(scene=scene, scan="speed",
                        condition_id="s" + str(setting), seed_family=seed, setting=setting,
                        actual_mean_speed_kmh=setting + delta, handover_count=4 + seed))
                    for strategy in range(4):
                        self.speeds.append(dict(scene=scene, strategy=strategy,
                            condition_id="s" + str(setting), seed_family=seed,
                            speed_setting_kmh=setting,
                            vehicle_time_weighted_speed_kmh=setting + strategy + delta,
                            stopped_vehicle_time_fraction=.1 * seed))
            for setting in (5, 20):
                for seed in (1, 2):
                    self.mobility.append(dict(scene=scene, scan="vehicles",
                        condition_id="n" + str(setting), seed_family=seed, setting=setting,
                        actual_mean_speed_kmh=30, handover_count=setting * seed))
        self.write_tables()
        self.addCleanup(plt.close, "all")

    def write_tables(self):
        write_rows(self.source / "baseline-decomposition.csv", self.decomposition)
        write_rows(self.source / "mobility-coverage.csv", self.mobility)
        write_rows(self.source / "historical-actual-speed.csv", self.speeds)

    def save(self, fig, output, identifier, table, caption_zh, caption_en):
        self.figures[identifier] = fig
        self.assertEqual(output, self.output)
        self.assertTrue((self.source / table).is_file())
        return dict(id=identifier, source_table=table,
                    caption_zh=caption_zh, caption_en=caption_en)

    def render(self):
        return plot.render_diagnostics(self.source, self.output, self.save)

    def test_all_four_figures_use_only_saved_tables_and_do_not_modify_them(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        records = self.render()
        self.assertEqual([r["id"] for r in records], [
            "D04-extra-submission-decomposition", "D05-control-traffic-decomposition",
            "D06-mobility-coverage", "S14-historical-actual-speed"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertFalse((self.source / "run-details.json").exists())

    def test_decomposition_groups_categories_with_algorithm_colors_and_exact_means(self):
        self.render()
        ax = self.figures["D04-extra-submission-decomposition"].axes[0]
        self.assertEqual([p.get_height() for p in ax.patches],
                         [0, .5, 0, 1.5, 0, 2.5, 0, 3.5])
        self.assertEqual([to_hex(ax.patches[i * 2].get_facecolor()) for i in range(4)],
                         ["#808080", "#e69f00", "#009e73", "#8e5aa9"])
        self.assertEqual(ax.get_legend_handles_labels()[1],
                         ["Naive NDN", "VTDF", "RTVTDF", "TKAN-PDF"])
        self.assertTrue(all(p.get_y() == 0 for p in ax.patches))
        self.assertEqual(len(ax.collections), 0, "No unavailable SD may be invented")
        centers = [p.get_x() + p.get_width() / 2 for p in ax.patches[:2]]
        self.assertAlmostEqual(centers[1] - centers[0], 1)

    def test_speed_preserves_equal_run_means_sample_sd_and_categorical_reference(self):
        self.render()
        upper = self.figures["S14-historical-actual-speed"].axes[0]
        lower = self.figures["S14-historical-actual-speed"].axes[3]
        self.assertEqual([p.get_height() for p in upper.patches],
                         [15, 60, 16, 61, 17, 62, 18, 63])
        self.assertAlmostEqual(lower.patches[0].get_height(), 15)
        segments = upper.collections[0].get_segments()
        self.assertAlmostEqual(segments[0][1][1] - 15, math.sqrt(8))
        reference = [line for line in upper.lines if line.get_label() == "Speed setting"][0]
        self.assertEqual(list(reference.get_xdata()), [0, 1])
        self.assertEqual(list(reference.get_ydata()), [15, 60])
        self.assertEqual([t.get_text() for t in upper.get_xticklabels()], ["15", "60"])

    def test_mobility_counts_are_not_packet_weighted(self):
        self.render()
        axes = self.figures["D06-mobility-coverage"].axes
        self.assertEqual([p.get_height() for p in axes[0].patches], [15, 60])
        self.assertEqual([p.get_height() for p in axes[3].patches], [7.5, 30])
        self.assertEqual(to_hex(axes[3].patches[0].get_facecolor()), "#808080")

    def test_missing_category_row_is_rejected_not_assumed_zero(self):
        self.decomposition.pop(0)
        self.write_tables()
        with self.assertRaisesRegex(ValueError, "Missing decomposition"):
            self.render()

    def test_duplicate_category_row_is_rejected(self):
        self.decomposition.append(dict(self.decomposition[0]))
        self.write_tables()
        with self.assertRaisesRegex(ValueError, "Duplicate decomposition"):
            self.render()

    def test_missing_or_duplicate_seed_and_nonfinite_measurement_are_rejected(self):
        removed = self.speeds.pop(0)
        self.write_tables()
        with self.assertRaisesRegex(ValueError, "two distinct seeds"):
            self.render()
        self.speeds.append(dict(self.speeds[0]))
        self.write_tables()
        with self.assertRaisesRegex(ValueError, "two distinct seeds"):
            self.render()
        self.speeds = self.speeds[:-1]
        self.speeds.insert(0, dict(removed,
                                 vehicle_time_weighted_speed_kmh="nan"))
        self.write_tables()
        with self.assertRaisesRegex(ValueError, "finite"):
            self.render()


if __name__ == "__main__":
    unittest.main()
