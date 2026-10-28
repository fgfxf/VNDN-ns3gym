"""可编辑主图的数据保真、坐标范围和组合图数据引用契约。"""
import ast
import importlib.util
import json
from pathlib import Path
import runpy
import tempfile
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('editable_primary', DIRECTORY / 'editable_primary.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
SCENES = ('circle', 'grid', 'spidermap')
METRICS = ('isr_percent', 'mean_success_rtt_ms', 'network_mbit',
           'control_mbit', 'extra_data_app_attempts')


def constant(script, name):
    """读取脚本公开的字面量，无需执行绘图或触发输出。"""
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('Missing editable constant: ' + name)


def source_fixture():
    conditions = [dict(id='i1', requests=1500, speed_kmh=30, vehicles=10),
                  dict(id='baseline', requests=6000, speed_kmh=30, vehicles=10),
                  dict(id='i2', requests=12000, speed_kmh=30, vehicles=10),
                  dict(id='v1', requests=6000, speed_kmh=15, vehicles=10),
                  dict(id='v2', requests=6000, speed_kmh=60, vehicles=10),
                  dict(id='n1', requests=3000, speed_kmh=30, vehicles=5),
                  dict(id='n2', requests=12000, speed_kmh=30, vehicles=20)]
    points = []
    for scene in SCENES:
        for condition in conditions:
            for strategy in range(4):
                for metric in METRICS:
                    estimate = 70.25 + strategy if metric == 'isr_percent' else 12.125 + strategy
                    sd = .875
                    if scene == 'grid' and metric == 'control_mbit':
                        estimate, sd = 144.131044, 1.9096917692318902
                    if scene == 'circle' and metric == 'mean_success_rtt_ms' and strategy == 3:
                        estimate, sd = 354.123456789, 17.987654321
                    if scene == 'spidermap' and metric == 'mean_success_rtt_ms' and strategy == 0:
                        estimate, sd = None, None
                    points.append(dict(scene=scene, condition_id=condition['id'], strategy=str(strategy),
                                       metric=metric, estimate=estimate, run_sd=sd,
                                       run_values=[1, 999], ci_low=2, ci_high=998))
    return dict(conditions=conditions, points=points,
                scans={'interest': ['i1', 'baseline', 'i2'],
                       'speed': ['v1', 'baseline', 'v2'],
                       'vehicles': ['n1', 'baseline', 'n2']})


class EditablePrimaryContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        (self.source / 'source-tables').mkdir()
        self.fixture = source_fixture()
        self.path = self.source / 'source-tables/aggregate.json'
        self.path.write_text(json.dumps(self.fixture), encoding='utf-8')
        self.original = self.path.read_bytes()
        self.scripts = module.generate(self.source)

    def test_exactly_fifteen_main_and_nine_combined_scripts(self):
        expected = {'F{:02d}-{}-{}'.format(5 * scan_index + metric_index + 1, scan, metric)
                    for scan_index, scan in enumerate(('interest', 'speed', 'vehicles'))
                    for metric_index, metric in enumerate(METRICS)}
        expected.update('C-{}-{}-five-metrics'.format(scene, scan)
                        for scene in SCENES for scan in ('interest', 'speed', 'vehicles'))
        self.assertEqual(set(self.scripts), expected)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_original_weighted_rtt_and_sd_are_literal_not_reestimated(self):
        data = constant(self.scripts['F02-interest-mean_success_rtt_ms'], 'DATA')
        self.assertEqual(data['xlabels'], [1500, 6000, 12000])
        points = data['scenes']['circle'][3]['points']
        self.assertEqual(points, [{'estimate': 354.123456789, 'run_sd': 17.987654321}] * 3)
        self.assertEqual(data['scenes']['spidermap'][0]['points'],
                         [{'estimate': None, 'run_sd': None}] * 3)

    def test_shared_axis_includes_larger_grid_mean_plus_sd(self):
        script = self.scripts['F09-speed-control_mbit']
        limits = constant(script, 'Y_LIM')
        self.assertEqual(limits, (0., 160.))
        self.assertGreater(limits[1], 144.131044 + 1.9096917692318902)
        ticks = constant(script, 'Y_TICKS')
        self.assertTrue(all(limits[0] <= x <= limits[1] for x in ticks))
        self.assertEqual(constant(script, 'X_LIM'), (-.6, 2.6))

    def test_all_main_scripts_preserve_all_scans_scenes_and_strategy_points(self):
        for number, scan in enumerate(('interest', 'speed', 'vehicles')):
            for ordinal, metric in enumerate(METRICS):
                data = constant(self.scripts['F{:02d}-{}-{}'.format(number * 5 + ordinal + 1,
                                                                   scan, metric)], 'DATA')
                for scene in SCENES:
                    for strategy, series in enumerate(data['scenes'][scene]):
                        self.assertEqual(int(series['strategy']), strategy)
                        for condition, actual in zip(self.fixture['scans'][scan], series['points']):
                            expected = next(p for p in self.fixture['points']
                                            if p['scene'] == scene and p['condition_id'] == condition
                                            and p['strategy'] == str(strategy) and p['metric'] == metric)
                            self.assertEqual(actual, {key: expected[key] for key in ('estimate', 'run_sd')})

    def test_combined_scripts_load_sibling_data_without_duplicate_means(self):
        for scene in SCENES:
            for ordinal, scan in enumerate(('interest', 'speed', 'vehicles')):
                script = self.scripts['C-{}-{}-five-metrics'.format(scene, scan)]
                sources = constant(script, 'SOURCES')
                expected = ['F{:02d}-{}-{}.py'.format(ordinal * 5 + k + 1, scan, metric)
                            for k, metric in enumerate(METRICS)]
                self.assertEqual(sources, expected)
                self.assertIn('load_plot(', script)
                self.assertNotIn('354.123456789', script)
                self.assertEqual(constant(script, 'SCENE'), scene)
                self.assertEqual(len(constant(script, 'Y_LIMS')), 5)

    def test_main_script_names_all_related_scene_combinations(self):
        for number, scan in enumerate(('interest', 'speed', 'vehicles')):
            for ordinal, metric in enumerate(METRICS):
                script = self.scripts['F{:02d}-{}-{}'.format(number * 5 + ordinal + 1, scan, metric)]
                for scene in SCENES:
                    self.assertIn('C-{}-{}-five-metrics'.format(scene, scan), script)

    def test_scripts_are_valid_python_and_do_not_read_original_tables(self):
        self.assertTrue(self.scripts, 'No scripts were generated')
        for name, script in self.scripts.items():
            compile(script, name + '.py', 'exec')
            self.assertNotIn('aggregate.json', script)
            self.assertNotIn('read_csv', script)
            self.assertNotIn(str(self.source), script)
            self.assertIn('def draw(', script)

    def test_import_has_no_image_side_effect_and_draw_preserves_larger_grid(self):
        path = self.source / 'F09-speed-control_mbit.py'
        path.write_text(self.scripts[path.stem], encoding='utf-8')
        before = set(plt.get_fignums())
        namespace = runpy.run_path(str(path))
        self.assertEqual(set(plt.get_fignums()), before)
        self.assertEqual(list(self.source.glob('*.png')), [])
        fig = namespace['draw']()
        self.addCleanup(plt.close, fig)
        self.assertEqual(len(fig.axes), 3)
        self.assertEqual(fig.axes[1].get_ylim(), (0., 160.))
        self.assertEqual([patch.get_height() for patch in fig.axes[1].patches],
                         [144.131044] * 12)

    def test_combination_reads_modified_single_figure_data_on_next_draw(self):
        for identifier, script in self.scripts.items():
            (self.source / (identifier + '.py')).write_text(script, encoding='utf-8')
        combined = runpy.run_path(str(self.source / 'C-circle-interest-five-metrics.py'))
        first = combined['draw']()
        self.addCleanup(plt.close, first)
        self.assertEqual(first.axes[1].patches[-1].get_height(), 354.123456789)
        path = self.source / 'F02-interest-mean_success_rtt_ms.py'
        path.write_text(path.read_text(encoding='utf-8').replace('354.123456789', '355.123456789'),
                        encoding='utf-8')
        second = combined['draw']()
        self.addCleanup(plt.close, second)
        self.assertEqual(second.axes[1].patches[-1].get_height(), 355.123456789)
        self.assertEqual(second.axes[0].patches[-1].get_height(), first.axes[0].patches[-1].get_height())


if __name__ == '__main__':
    unittest.main()
