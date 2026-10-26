"""Re-layout keeps the original metric definitions, uncertainty and source data."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_fixed_model_figures import aggregate, tiny_manifest


def load():
    path = Path(__file__).resolve().parents[1] / 'followup_primary_figures.py'
    spec = importlib.util.spec_from_file_location('followup_primary_tested', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class PrimaryFiguresTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / 'old'
        self.directory = self.old / 'workflow/figures/all/attempt-001/analysis'
        self.source = tiny_manifest(self.root / 'fixture')
        self.result = aggregate.aggregate_campaign(self.source, self.directory)

    def test_five_metrics_keep_all_strategies_values_and_descriptive_uncertainty(self):
        mod = load()
        original = copy.deepcopy(self.result)
        points = mod.plot.lookup_points(self.result)
        calls = []
        def draw(ax, x, values, strategy, descriptive=False):
            calls.append((x, values, strategy, descriptive))
            ax.plot(x, [v['estimate'] for v in values], label=strategy)
        def save(fig, *args, **kwargs):
            self.assertEqual(len(fig.axes), 6)
            self.assertFalse(fig.axes[-1].axison)
            mod.plot.plt.close(fig)
            return {'id': args[1]}
        with patch.object(mod.plot, '_draw_points', side_effect=draw), patch.object(mod.plot, 'save_figure', side_effect=save):
            figures = mod.combined_metric_figures(self.result, self.root, points)
        self.assertEqual(len(figures), 9)
        self.assertEqual(len(calls), 3 * 3 * 5 * 4)
        self.assertTrue(all(call[3] for call in calls))
        self.assertEqual(self.result, original)
        self.assertEqual({call[2] for call in calls}, {'0', '1', '2', '3'})
        self.assertTrue(all(any(v is p for p in points.values()) for c in calls for v in c[1]))

    def test_complete_relayout_and_source_copies_keep_old_data_unchanged(self):
        mod = load()
        before = {str(p): mod.plot.summary.sha256_file(p) for p in self.old.rglob('*') if p.is_file()}
        output = self.root / 'output'; output.mkdir()
        progress = []
        with patch.object(mod.plot, 'load_analysis', wraps=mod.plot.load_analysis) as validate:
            report = mod.render_primary(self.old, output, progress.append)
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(len(report['figures']), 38)
        self.assertGreater(len(progress), 10)
        self.assertFalse(any('learning' in f['id'] or 'confusion' in f['id'] for f in report['figures']))
        for item in report['figures']:
            self.assertIn('探索', item['caption_zh'])
            if item.get('source_table'):
                self.assertTrue((output / item['source_table']).is_file(), item['source_table'])
            for ext in ('png', 'svg', 'pdf'):
                self.assertGreater((output / item['files'][ext]).stat().st_size, 100)
        self.assertEqual(mod.plot.summary.sha256_file(self.directory / 'aggregate.json'), report['old_analysis_sha256'])
        self.assertEqual(Path(report['old_analysis_path']), self.directory)
        self.assertIn('primary-figure-index.json', (output / 'index.html').read_text())
        self.assertIn('source-tables/plot-summary.csv', report['source_tables'])
        for name, digest in report['source_tables'].items():
            self.assertEqual(mod.plot.summary.sha256_file(output / name), digest)
        self.assertEqual(before, {str(p): mod.plot.summary.sha256_file(p) for p in self.old.rglob('*') if p.is_file()})
        with self.assertRaisesRegex(ValueError, 'already'):
            mod.render_primary(self.old, output)


if __name__ == '__main__':
    unittest.main()
