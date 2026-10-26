"""Rendering contracts for the requested publication-only restyling."""
import importlib.util
from pathlib import Path
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex


DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("paper_figure_style", DIRECTORY / "paper_figure_style.py")
plot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plot)
draw_points = plot.draw_points


class DrawPointsContractTest(unittest.TestCase):
    def setUp(self):
        self.fig, self.ax = plt.subplots()
        self.addCleanup(plt.close, self.fig)
        self.points = [dict(estimate=10.0, run_sd=2.5, run_values=[7.5, 12.5]),
                       dict(estimate=20.0, run_sd=3.0, run_values=[17.0, 23.0])]

    def test_requested_grouped_bars_preserve_values(self):
        draw_points(self.ax, [1500, 12000], self.points, "3", descriptive=True)
        self.assertEqual([bar.get_height() for bar in self.ax.patches], [10.0, 20.0])
        self.assertEqual(to_hex(self.ax.patches[0].get_facecolor()), "#8e5aa9")
        self.assertEqual(self.ax.get_legend_handles_labels()[1], ["TKAN-PDF"])

    def test_groups_are_categorical_and_equally_spaced(self):
        draw_points(self.ax, [1500, 12000], self.points, "0", descriptive=True)
        self.assertEqual(len(self.ax.patches), 2)
        centers = [bar.get_x() + bar.get_width() / 2 for bar in self.ax.patches]
        self.assertAlmostEqual(centers[1] - centers[0], 1.0)

    def test_mean_and_sd_are_not_reestimated_or_replaced_by_confidence_intervals(self):
        points = [dict(estimate=17, run_sd=3.25, ci_low=4, ci_high=31,
                       run_values=[1, 1000]), dict(estimate=5, run_sd=None)]
        result = draw_points(self.ax, [1500, 3000], points, "2")
        self.assertEqual([bar.get_height() for bar in result["bars"]], [17, 5])
        segments = result["errors"].lines[2][0].get_segments()
        self.assertEqual(len(segments), 1)
        self.assertEqual(list(segments[0][:, 1]), [13.75, 20.25])

    def test_missing_estimates_leave_empty_slot_and_zero_is_a_real_bar(self):
        result = draw_points(self.ax, [1500, 3000],
                             [dict(estimate=None, run_sd=None),
                              dict(estimate=0, run_sd=0)], "1")
        self.assertEqual(result["valid_indices"], [1])
        self.assertEqual(result["missing_indices"], [0])
        self.assertEqual(len(result["bars"]), 1)
        self.assertEqual(result["bars"][0].get_height(), 0)
        self.assertEqual(result["missing"][0].get_text(), "N/A")

    def test_fixed_colors_labels_offsets_and_hatches_for_all_four_algorithms(self):
        expected = ["#808080", "#e69f00", "#009e73", "#8e5aa9"]
        centers = []
        for strategy in range(4):
            result = draw_points(self.ax, [1500, 12000], self.points, strategy)
            self.assertEqual(to_hex(result["bars"][0].get_facecolor()), expected[strategy])
            self.assertEqual(result["bars"][0].get_hatch(), plot.HATCHES[strategy])
            centers.append(result["positions"][0])
        self.assertEqual(self.ax.get_legend_handles_labels()[1], list(plot.ALGORITHMS))
        self.assertAlmostEqual(sum(centers), 0)
        self.assertTrue(all(a < b for a, b in zip(centers, centers[1:])))

    def test_legacy_xticks_are_restored_and_grid_is_disabled(self):
        draw_points(self.ax, [1500, 12000], self.points, "0")
        self.ax.set_xticks([1500, 12000])
        self.ax.grid(True)
        plot.finalize_axes(self.ax)
        self.assertEqual(list(self.ax.get_xticks()), [0, 1])
        self.assertEqual([x.get_text() for x in self.ax.get_xticklabels()], ["1500", "12000"])
        self.assertFalse(any(x.get_visible() for x in self.ax.get_xgridlines()))

    def test_invalid_dimensions_negative_sd_and_changed_groups_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "every group"):
            draw_points(self.ax, [1], self.points, 0)
        with self.assertRaisesRegex(ValueError, "negative"):
            draw_points(self.ax, [1], [dict(estimate=2, run_sd=-1)], 0)
        draw_points(self.ax, [1, 2], self.points, 0)
        with self.assertRaisesRegex(ValueError, "identical"):
            draw_points(self.ax, [3, 4], self.points, 1)

    def test_font_context_restores_global_settings_and_records_real_font(self):
        previous = list(matplotlib.rcParams["font.family"])
        with plot.paper_style() as metadata:
            self.assertTrue(Path(metadata["path"]).is_file())
            self.assertEqual(matplotlib.rcParams["font.family"], ["serif"])
            self.assertEqual(matplotlib.rcParams["pdf.fonttype"], 42)
            self.assertEqual(matplotlib.rcParams["font.serif"], [metadata["selected_family"]])
        self.assertEqual(matplotlib.rcParams["font.family"], previous)

    def test_existing_labels_are_replaced_without_changing_other_text(self):
        self.ax.set_title("Proposed (TKAN-LSTM)")
        self.ax.set_ylabel("Interest satisfaction rate (%)")
        plot.style_figure(self.fig)
        self.assertEqual(self.ax.get_title(), "TKAN-PDF")
        self.assertEqual(self.ax.get_ylabel(), "Interest satisfaction rate (%)")

    def test_fixed_tick_algorithm_labels_survive_canvas_draw_in_2d_and_3d(self):
        self.ax.set_xticks(range(4))
        self.ax.set_xticklabels(["Naive NDN", "VTDF", "RTVTDF", "Proposed (TKAN-LSTM)"])
        three_dimensional = self.fig.add_subplot(222, projection="3d")
        three_dimensional.set_yticks(range(4))
        three_dimensional.set_yticklabels(["Naive NDN", "VTDF", "RTVTDF", "Proposed"])
        plot.style_figure(self.fig)
        self.fig.canvas.draw()
        self.assertEqual(self.ax.get_xticklabels()[-1].get_text(), "TKAN-PDF")
        self.assertEqual(three_dimensional.get_yticklabels()[-1].get_text(), "TKAN-PDF")

    def test_shared_categorical_axes_preserve_labels_and_group_positions(self):
        fig, axes = plt.subplots(2, 1, sharex=True)
        self.addCleanup(plt.close, fig)
        for ax in axes:
            draw_points(ax, [1500, 12000], self.points, 3)
            ax.set_xticks([1500, 12000])
        plot.style_figure(fig)
        fig.canvas.draw()
        self.assertEqual(list(axes[0].get_xticks()), [0, 1])
        self.assertEqual([label.get_text() for label in axes[1].get_xticklabels()], ["1500", "12000"])


if __name__ == "__main__":
    unittest.main()
