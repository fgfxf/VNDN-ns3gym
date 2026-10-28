"""补充图固化数据契约；合成三次运行可检查均值、SD、缺项和参考线。"""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import editable_supplements as supplement


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        writer.writerows(rows)


def fixture(root):
    records = dict(accuracy=[], online=[], states=[], payloads=[], packets=[])
    states = ('present_vehicles', 'cache_vehicle_entries', 'cache_name_entries',
              'cache_edges', 'history_vehicles', 'history_records')
    for scene in ('circle', 'grid', 'spidermap'):
        for period in (20, 40, 80, 160):
            for seed, value in enumerate((2., 4., 6.)):
                row = dict(scenario=scene, hello_interval_ms=period, seed_family=seed,
                           task_id='{}-{}-{}'.format(scene, period, seed), stage='online')
                records['accuracy'].append(dict(row, accuracy_percent=value,
                    handover_accuracy_percent=None, evaluable_request_percent=90.,
                    evaluable_observation_percent=80., short_history_count=2,
                    empty_history_count=0, sample_count=10))
                records['online'].append(dict(row, isr_percent=value,
                    mean_success_rtt_ms=value, network_mbit=value,
                    control_mbit=value, extra_data_app_attempts=value))
                records['payloads'].append(dict(task_id=row['task_id'], phase='startup',
                    category='registration', wire_bytes_mean=value, count=10))
                records['packets'].append(dict(task_id=row['task_id'], semantic_class='hello', total=value * 125000))
        for vehicles in (5, 10, 15, 20):
            for seed, value in enumerate((2., 4., 6.)):
                row = dict(scenario=scene, hello_interval_ms=20, rsu_id='network',
                           vehicles=vehicles, seed_family=seed)
                for field in states:
                    row[field + '_mean'] = value
                    row[field + '_peak'] = value * 2
                records['states'].append(row)
    (root / 'analysis-source').mkdir()
    (root / 'analysis-source/run-analysis.json').write_text(json.dumps(records))
    benchmark, decomposition, mobility, speeds = [], [], [], []
    for scene in ('circle', 'grid', 'spidermap'):
        for operation in ('forward', 'controller_compute'):
            for seed in range(5):
                benchmark.append(dict(scenario=scene, operation=operation,
                    median_us=100 + seed, p95_us=200 + seed))
        for strategy in range(4):
            for kind in ('extra', 'control'):
                decomposition.append(dict(scene=scene, strategy=strategy, kind=kind,
                    category='test_category', mean=3., repetitions=2))
            for setting in (15, 30, 50, 60):
                for seed in (1, 2):
                    speeds.append(dict(scene=scene, strategy=strategy, seed_family=seed,
                        speed_setting_kmh=setting, vehicle_time_weighted_speed_kmh=setting / 2,
                        stopped_vehicle_time_fraction=.1))
        for scan, settings in [('speed', (15, 30, 50, 60)), ('vehicles', (5, 10, 15, 20))]:
            for setting in settings:
                for seed in (1, 2):
                    mobility.append(dict(scene=scene, scan=scan, setting=setting, seed_family=seed,
                        actual_mean_speed_kmh=setting / 2, handover_count=setting))
    for name, rows in [('inference-processes.csv', benchmark),
                       ('baseline-decomposition.csv', decomposition),
                       ('mobility-coverage.csv', mobility), ('historical-actual-speed.csv', speeds)]:
        write_csv(root / name, rows)


class EditableSupplementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        fixture(self.source)

    def test_equal_run_mean_sample_sd_and_missing(self):
        self.assertEqual(supplement.point([2., None, 4., 6.]), dict(estimate=4., run_sd=2.))
        self.assertEqual(supplement.point([None, None]), dict(estimate=None, run_sd=None))
        self.assertEqual(supplement.point([0., 0.]), dict(estimate=0., run_sd=0.))

    def test_all_seventeen_figures_keep_statistics_and_reference_lines(self):
        figures = supplement.collect(self.source)
        self.assertEqual(len(figures), 17)
        first = figures['S01-period-prediction-accuracy']['panels'][0]
        self.assertEqual(first['series'][0]['points'][0], dict(estimate=4., run_sd=2.))
        self.assertEqual(first['series'][1]['points'][0], dict(estimate=None, run_sd=None))
        payload = figures['S11-period-hello-size']['panels'][3]
        self.assertIsNone(payload['series'][0]['points'][0]['estimate'])
        self.assertTrue(figures['S11-period-hello-size'].get('shared_x', False))
        self.assertTrue(figures['S01-period-prediction-accuracy']['shared_y'])
        control = figures['S12-period-control-categories']['panels'][0]
        hello = next(s for s in control['series'] if s['label'] == 'hello')
        self.assertEqual(hello['points'][0], dict(estimate=4., run_sd=2.))
        speed = figures['S14-historical-actual-speed']['panels'][0]
        self.assertEqual(speed['reference'], [15., 30., 50., 60.])
        decomposition = figures['D04-extra-submission-decomposition']['panels'][0]
        self.assertIsNone(decomposition['series'][0]['points'][0]['run_sd'])

    def test_generated_scripts_are_static_python_with_explicit_axes(self):
        scripts = supplement.generate(self.source)
        self.assertEqual(len(scripts), 17)
        for name, text in scripts.items():
            with self.subTest(name=name):
                compile(text, name + '.py', 'exec')
                self.assertIn('Y_LIM', text)
                self.assertIn('X_LIM', text)
                self.assertIn('Y_TICKS', text)
                self.assertIn('DATA =', text)
                self.assertNotIn('read_csv', text)
                self.assertNotIn('run-analysis.json', text)
                self.assertNotIn(str(self.source), text)


if __name__ == '__main__':
    unittest.main()
