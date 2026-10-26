"""Saved-data-only rendering boundaries and original numeric semantics."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from matplotlib.colors import to_rgba

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import replot_paper_figures as redraw


class SavedDataRedrawTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_original_data_and_existing_outputs_cannot_be_overwritten(self):
        for folder in ('', 'figures', 'figures/sub', 'analysis', 'runs', 'plan', 'workflow'):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                redraw.safe_output(self.root, self.root / folder)
        output = self.root / 'new-figures'
        self.assertEqual(redraw.safe_output(self.root, output), output)
        output.mkdir()
        (output / 'keep').write_text('original')
        with self.assertRaisesRegex(ValueError, 'already'):
            redraw.safe_output(self.root, output)
        self.assertEqual((output / 'keep').read_text(), 'original')

    def test_sealed_inputs_detect_edit_without_requiring_raw_runs(self):
        (self.root / 'figures').mkdir()
        (self.root / 'analysis').mkdir()
        table = self.root / 'figures/points.csv'; table.write_text('value\n1\n')
        records = self.root / 'analysis/run-analysis.json'; records.write_text('{}')
        index = self.root / 'figures/figure-index.json'
        redraw.write_json(index, dict(status='complete', artifact_hashes={'points.csv': redraw.digest(table)},
            identity={'analysis_input_hashes': {'analysis/run-analysis.json': redraw.digest(records)}}))
        redraw.write_json(self.root / 'analysis/summary.json', dict(status='complete',
            artifact_hashes={'figures/figure-index.json': redraw.digest(index)}))
        value, checks = redraw.verify_sources(self.root)
        self.assertEqual(len(checks), 3)
        self.assertFalse((self.root / 'runs').exists())
        table.write_text('value\n2\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            redraw.verify_sources(self.root)

    def test_supplement_original_means_sd_missing_and_cpu_categories(self):
        fig, ax = redraw.plt.subplots()
        self.addCleanup(redraw.plt.close, fig)
        redraw.collect_runs(ax, [-.15, .85, 1.85], [[2., 4., 6.], [None, None], [0., 0.]],
                            'forward', redraw.PURPLES[0])
        redraw.collect_runs(ax, [.15, 1.15, 2.15], [[1., 2., 3.], [3.], [9., 9.]],
                            'controller compute', redraw.PURPLES[1])
        self.assertEqual(ax._paper_pending[0][1]['points'], [
            {'estimate': 4., 'run_sd': 2.}, {'estimate': None, 'run_sd': None},
            {'estimate': 0., 'run_sd': 0.}])
        ax.set_xticks([0, 1, 2], ['Circle', 'Grid', 'Spider'])
        redraw.prepare_figure(fig, 'S13-inference-cpu-cost')
        fig.canvas.draw()
        self.assertEqual([label.get_text() for label in ax.get_xticklabels()], ['Circle', 'Grid', 'Spider'])
        self.assertEqual([patch.get_height() for patch in ax.patches], [4., 0., 2., 3., 9.])
        self.assertTrue(any(item.get_text() == 'N/A' for item in ax.texts))

    def test_visible_captions_use_new_name_and_bar_semantics(self):
        value = redraw.clean_caption('Online proposed scheme; Proposed (TKAN-LSTM); '
            'faint symbols show individual run estimates and bars show one sample SD. 淡点为各run，误差线为SD。')
        self.assertNotIn('proposed', value.lower())
        self.assertIn('TKAN-PDF', value)
        self.assertNotIn('faint symbols', value)
        self.assertNotIn('淡点', value)

    def test_deferred_supplement_keeps_legend_colors_and_nonempty_y_range(self):
        fig, ax = redraw.plt.subplots()
        self.addCleanup(redraw.plt.close, fig)
        redraw.collect_runs(ax, [5, 10], [[100., 120.], [200., 220.]], 'Mean', redraw.PURPLES[0])
        redraw.collect_runs(ax, [5, 10], [[140., 160.], [250., 270.]], 'Peak', redraw.PURPLES[1])
        ax.set_ylim(bottom=0)  # Historical renderer freezes its initially empty range.
        handles, labels = ax.get_legend_handles_labels()
        legend = fig.legend(handles, labels)
        redraw.prepare_figure(fig, 'S08-circle-state-scale')
        fig.canvas.draw()
        self.assertGreater(ax.get_ylim()[1], 274.)
        self.assertEqual([handle.get_facecolor() for handle in legend.legendHandles],
                         [to_rgba(c) for c in redraw.PURPLES[:2]])
        self.assertEqual([handle.get_hatch() for handle in legend.legendHandles], ['xx', '///'])


if __name__ == '__main__':
    unittest.main()
