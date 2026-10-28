"""封存分布必须完整进入可编辑脚本，组合图只引用单图。"""
import ast
import csv
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

import numpy as np
from matplotlib.cbook import boxplot_stats

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
SCENES = ('circle', 'grid', 'spidermap')


def assignment(script, name):
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('缺少明确常量：' + name)


class EditableDistributionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        tables = self.source / 'source-tables'
        tables.mkdir()
        (tables / 'aggregate.json').write_text(json.dumps({'baseline_condition_id': 'baseline'}))
        requests, bins, summary = [], [], []
        for scene in SCENES:
            for strategy in range(4):
                values = [1., 1., 2., 3., 4., 100.] if strategy else [2., 2., 8.]
                for index, value in enumerate(values):
                    requests.append(dict(scene=scene, strategy=str(strategy), terminal='DATA',
                                         rtt_ms=value, common_handover=int(index % 2 == 0)))
                requests.append(dict(scene=scene, strategy=str(strategy), terminal='TIMEOUT',
                                     rtt_ms='', common_handover=1))
                for index, value in enumerate((4., '', 8.)):
                    bins.append(dict(scene=scene, strategy=str(strategy), bin_start_s=20 + index * 5,
                                     bin_end_s=25 + index * 5, mean_success_rtt_ms=value))
                summary.append(dict(scene=scene, strategy=str(strategy), condition_id='baseline',
                                    metric='network_mbit', estimate=10 + strategy, run_sd=2,
                                    run_values=json.dumps([8 + strategy, 12 + strategy])))
        self.write_csv(tables / 'baseline-requests.csv', requests)
        self.write_csv(self.source / 'time-bin-rtt.csv', bins)
        self.write_csv(tables / 'plot-summary.csv', summary)

    def write_csv(self, path, rows):
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def generate(self):
        path = HERE / 'editable_distributions.py'
        self.assertTrue(path.exists(), '缺少完整分布及单图联动脚本生成功能')
        spec = importlib.util.spec_from_file_location('editable_distributions', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.generate(self.source)

    def test_all_eleven_scripts_have_explicit_parameters(self):
        scripts = self.generate()
        self.assertEqual(len(scripts), 11)
        for script in scripts.values():
            self.assertIn('FIGSIZE = ', script)
            self.assertIn('LIM = ', script)
            compile(script, '<generated>', 'exec')

    def test_empty_3d_bins_remain_gaps_and_related_plot_is_declared(self):
        scripts = self.generate()
        script = scripts['F21-circle-rtt-3d']
        data = assignment(script, 'DATA')
        self.assertEqual(data[0]['x'], [22.5, 27.5, 32.5])
        self.assertEqual(data[0]['rtt_ms'], [4., None, 8.])
        self.assertIn('C-all-scenes-rtt-3d', script)

    def test_box_statistics_and_every_flier_are_preserved(self):
        data = assignment(self.generate()['F24-circle-rtt-box'], 'DATA')
        expected = boxplot_stats([1., 1., 2., 3., 4., 100.])[0]
        self.assertEqual(data['pooled_success_count'], 18)
        for actual in data['boxes']:
            for key in ('med', 'q1', 'q3', 'whislo', 'whishi', 'mean', 'cilo', 'cihi'):
                self.assertEqual(actual[key], expected[key])
            self.assertEqual(actual['fliers'], expected['fliers'].tolist())

    def test_ecdf_keeps_exact_tie_mass_and_handover_subset(self):
        data = assignment(self.generate()['D01-circle-rtt-ecdf'], 'DATA')
        self.assertEqual(data['all_success'][0]['x'], [2., 8.])
        self.assertEqual(data['all_success'][0]['cdf'], [2 / 3, 1.])
        self.assertEqual(data['all_success'][0]['count'], 3)
        subset = data['handover_success'][1]
        self.assertEqual(subset['x'], [1., 2., 4.])
        self.assertEqual(subset['cdf'], [1 / 3, 2 / 3, 1.])
        self.assertEqual(subset['count'], 3)

    def test_traffic_preserves_individual_runs_and_original_sd(self):
        data = assignment(self.generate()['F27-baseline-total-traffic'], 'DATA')
        self.assertEqual(data['circle'][3], dict(strategy=3, estimate=13., run_sd=2.,
                                               run_values=[11., 15.]))

    def test_combination_references_all_three_single_sources_without_copied_data(self):
        script = self.generate()['C-all-scenes-rtt-3d']
        for index, scene in enumerate(SCENES, 21):
            self.assertIn('F{}-{}-rtt-3d.py'.format(index, scene), script)
        self.assertIn('load_plot(', script)
        self.assertNotIn('DATA = ', script)

    def test_combination_draw_reads_edited_single_values(self):
        scripts = self.generate()
        output = self.source / 'editable'
        output.mkdir()
        for identifier, script in scripts.items():
            (output / (identifier + '.py')).write_text(script, encoding='utf-8')
        combined = runpy.run_path(str(output / 'C-all-scenes-rtt-3d.py'))
        figure = combined['draw']()
        self.addCleanup(combined['plt'].close, figure)
        self.assertEqual(figure.axes[0].lines[0].get_data_3d()[2][0], 4.)
        path = output / 'F21-circle-rtt-3d.py'
        script = path.read_text(encoding='utf-8')
        node = next(node for node in ast.parse(script).body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'DATA' for target in node.targets))
        data = ast.literal_eval(node.value)
        data[0]['rtt_ms'][0] = 40.
        script = script.replace(ast.get_source_segment(script, node), 'DATA = ' + repr(data))
        path.write_text(script, encoding='utf-8')
        redrawn = combined['draw']()
        self.addCleanup(combined['plt'].close, redrawn)
        self.assertEqual(redrawn.axes[0].lines[0].get_data_3d()[2][0], 40.)
        self.assertTrue(np.isnan(redrawn.axes[0].lines[0].get_data_3d()[2][1]))


if __name__ == '__main__':
    unittest.main()
