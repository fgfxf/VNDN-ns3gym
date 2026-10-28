"""Acceptance checks for the 14 self-contained teacher-requested figures.

Run this explicit artifact acceptance entry from ns-3 with the preserved
2026-10-26 source tables available:
    python3.8 tools/experiments/acceptance/check_simulation_fill.py -v
It deliberately lives outside default unittest discovery: historical evidence
is a prerequisite for this task acceptance, not for a fresh source checkout.
This suite reads sealed evidence but never runs simulation, training or waf.
"""
import ast
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.text import Text


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'docs/ai/仿真图填充'
SOURCE = ROOT / 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026'
SCENES = ('circle', 'grid', 'spidermap')
SCENE_ZH = ('圆圈', '方阵', '蜘蛛网')
METRICS = ('extra_data_app_attempts', 'mean_success_rtt_ms', 'isr_percent', 'network_mbit')
PRIMARY = [(f'{6 + offset * 3 + index:02d}_{label}_{chinese}', scene, scan)
           for offset, (label, scan) in enumerate((('车速', 'speed'),
                                                   ('消费者数量', 'vehicles'),
                                                   ('请求速率', 'interest')))
           for index, (scene, chinese) in enumerate(zip(SCENES, SCENE_ZH))]
SUPPLEMENTS = ('01_信标周期预测准确率', '02_状态表规模', '03_注册与更新报文大小',
               '04_TKAN推理时延', '05_三场景RTT时间变化')
NAMES = SUPPLEMENTS + tuple(item[0] for item in PRIMARY)


def csv_rows(filename):
    with (SOURCE / filename).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def literal(path, name):
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('Missing literal {} in {}'.format(name, path.name))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SimulationFillAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aggregate = json.loads((SOURCE / 'source-tables/aggregate.json').read_text(encoding='utf-8'))
        cls.conditions = {row['id']: row for row in cls.aggregate['conditions']}
        cls.points = {(row['scene'], row['condition_id'], int(row['strategy']), row['metric']): row
                      for row in cls.aggregate['points']}

    def assertMeanSd(self, actual, samples, repetitions):
        self.assertEqual(len(samples), repetitions)
        self.assertAlmostEqual(actual['estimate'], statistics.mean(samples), places=10)
        self.assertAlmostEqual(actual['run_sd'], statistics.stdev(samples), places=10)
        self.assertEqual(actual['repetitions'], repetitions)

    def test_exactly_fourteen_scripts_and_fourteen_markdown_png_references(self):
        self.assertEqual({path.stem for path in PACKAGE.glob('*.py')}, set(NAMES))
        markdown = (PACKAGE / '仿真图.md').read_text(encoding='utf-8')
        references = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', markdown)
        self.assertEqual(len(references), 14)
        self.assertEqual({Path(name).name for name in references}, {name + '.png' for name in NAMES})
        for reference in references:
            self.assertNotIn('://', reference)
            self.assertTrue((PACKAGE / reference).is_file(), reference)
        for extension in ('png', 'svg', 'pdf'):
            self.assertEqual({path.stem for path in PACKAGE.glob('*.' + extension)}, set(NAMES))

    def test_scripts_have_static_embedded_data_and_side_effect_free_imports(self):
        before_files = {str(path.relative_to(PACKAGE)): digest(path)
                        for path in PACKAGE.rglob('*') if path.is_file()}
        for name in NAMES:
            with self.subTest(figure=name):
                path = PACKAGE / (name + '.py')
                self.assertIsInstance(literal(path, 'DATA'), dict)
                before_figures = set(plt.get_fignums())
                namespace = runpy.run_path(str(path))
                self.assertEqual(namespace['FIGURE_ID'], name)
                self.assertTrue(callable(namespace['draw']))
                self.assertEqual(set(plt.get_fignums()), before_figures)
        after_files = {str(path.relative_to(PACKAGE)): digest(path)
                       for path in PACKAGE.rglob('*') if path.is_file()}
        self.assertEqual(after_files, before_files)

    def test_nine_primary_figures_preserve_all_sealed_means_sd_and_rate_conversion(self):
        checked_points = 0
        for name, scene, scan in PRIMARY:
            with self.subTest(figure=name):
                data = literal(PACKAGE / (name + '.py'), 'DATA')
                self.assertEqual(data['scene'], scene)
                self.assertEqual(data['source_scan'], scan)
                self.assertEqual([panel['metric'] for panel in data['panels']], list(METRICS))
                field = {'interest': 'requests', 'speed': 'speed_kmh', 'vehicles': 'vehicles'}[scan]
                conditions = self.aggregate['scans'][scan]
                original_x = [self.conditions[condition][field] for condition in conditions]
                self.assertEqual(data['source_xlabels'], original_x)
                expected_x = [value / 120 for value in original_x] if scan == 'interest' else original_x
                self.assertEqual(data['xlabels'], expected_x)
                for panel in data['panels']:
                    self.assertEqual([int(series['strategy']) for series in panel['series']], [0, 1, 2, 3])
                    for series in panel['series']:
                        self.assertEqual(len(series['points']), len(conditions))
                        for condition, point in zip(conditions, series['points']):
                            source = self.points[scene, condition, int(series['strategy']), panel['metric']]
                            self.assertEqual(point, {key: source[key] for key in ('estimate', 'run_sd')})
                            checked_points += 1
        self.assertEqual(checked_points, 624)

    def test_primary_draw_has_four_panels_and_preserves_bar_heights_error_bars(self):
        for name, scene, scan in PRIMARY:
            with self.subTest(figure=name):
                namespace = runpy.run_path(str(PACKAGE / (name + '.py')))
                figure = namespace['draw']()
                try:
                    axes = [axis for axis in figure.axes if axis.axison]
                    self.assertEqual(len(axes), 4)
                    for axis, panel in zip(axes, namespace['DATA']['panels']):
                        points = [point for series in panel['series'] for point in series['points']]
                        expected_heights = [point['estimate'] for point in points if point['estimate'] is not None]
                        self.assertEqual([patch.get_height() for patch in axis.patches], expected_heights)
                        expected_intervals = [(point['estimate'] - point['run_sd'],
                                               point['estimate'] + point['run_sd'])
                                              for point in points if point['estimate'] is not None
                                              and point['run_sd'] is not None]
                        actual_intervals = [(float(segment[0][1]), float(segment[1][1]))
                                            for collection in axis.collections
                                            if hasattr(collection, 'get_segments')
                                            for segment in collection.get_segments() if len(segment) == 2]
                        self.assertEqual(actual_intervals, expected_intervals)
                        low, high = axis.get_ylim()
                        for lower, upper in expected_intervals:
                            self.assertLessEqual(low, lower)
                            self.assertGreaterEqual(high, upper)
                        self.assertEqual(len(axis.get_xticklabels()), len(namespace['DATA']['xlabels']))
                    for text in figure.findobj(match=Text):
                        self.assertIsNone(re.search(r'[\u3400-\u9fff]', text.get_text()), text.get_text())
                finally:
                    plt.close(figure)

    def test_three_dimensional_rtt_preserves_all_288_saved_bin_values(self):
        data = literal(PACKAGE / '05_三场景RTT时间变化.py', 'DATA')
        self.assertEqual(set(data), set(SCENES))
        rows = csv_rows('time-bin-rtt.csv')
        checked = 0
        for scene in SCENES:
            self.assertEqual([int(series['strategy']) for series in data[scene]], [0, 1, 2, 3])
            for series in data[scene]:
                source = sorted((row for row in rows if row['scene'] == scene
                                 and int(row['strategy']) == int(series['strategy'])),
                                key=lambda row: float(row['bin_start_s']))
                self.assertEqual(len(source), 24)
                self.assertEqual(series['x'], [(float(row['bin_start_s']) +
                                               float(row['bin_end_s'])) / 2 for row in source])
                self.assertEqual(series['rtt_ms'],
                                 [float(row['mean_success_rtt_ms'])
                                  if row['mean_success_rtt_ms'] else None for row in source])
                checked += len(source)
        self.assertEqual(checked, 288)
        namespace = runpy.run_path(str(PACKAGE / '05_三场景RTT时间变化.py'))
        figure = namespace['draw']()
        try:
            self.assertEqual(len(figure.axes), 3)
            for axis in figure.axes:
                self.assertEqual(axis.name, '3d')
        finally:
            plt.close(figure)

    def test_all_three_rtt_axis_labels_are_inside_the_exported_image(self):
        namespace = runpy.run_path(str(PACKAGE / '05_三场景RTT时间变化.py'))
        figure = namespace['draw']()
        try:
            figure.canvas.draw()
            renderer = figure.canvas.get_renderer()
            exported = figure.get_tightbbox(renderer).transformed(figure.dpi_scale_trans)
            padding = float(plt.rcParams['savefig.pad_inches']) * figure.dpi
            for axis in figure.axes:
                labels = [text for text in [axis.zaxis.label] + list(axis.texts)
                          if text.get_visible() and text.get_text() == 'Mean successful RTT (ms)']
                self.assertEqual(len(labels), 1)
                extent = labels[0].get_window_extent(renderer)
                self.assertGreaterEqual(extent.x0, exported.x0 - padding)
                self.assertLessEqual(extent.x1, exported.x1 + padding)
                self.assertGreaterEqual(extent.y0, exported.y0 - padding)
                self.assertLessEqual(extent.y1, exported.y1 + padding)
        finally:
            plt.close(figure)

    def test_period_accuracy_points_match_saved_three_seed_summaries(self):
        data = literal(PACKAGE / '01_信标周期预测准确率.py', 'DATA')
        rows = csv_rows('accuracy-summary.csv')
        lookup = {(row['scenario'], int(row['hello_interval_ms']), row['metric']): row
                  for row in rows}
        seen = set()
        for panel in data['panels']:
            self.assertEqual(panel['xlabels'], [20, 40, 80, 160])
            for series in panel['series']:
                for period, actual in zip(panel['xlabels'], series['points']):
                    key = (panel['scene'], period, series['field'])
                    row = lookup[key]
                    self.assertEqual(actual['estimate'], float(row['mean']))
                    self.assertEqual(actual['run_sd'], float(row['sd']))
                    self.assertEqual(actual['repetitions'], int(row['n_runs']))
                    self.assertEqual(actual['repetitions'], 3)
                    self.assertEqual(len(series['points']), 4)
                    self.assertNotIn(key, seen)
                    seen.add(key)
        self.assertEqual(seen, {(scene, period, metric) for scene in SCENES
                                for period in (20, 40, 80, 160)
                                for metric in ('accuracy_percent', 'handover_accuracy_percent')})

    def test_two_state_tables_preserve_time_means_and_network_peak_summaries(self):
        data = literal(PACKAGE / '02_状态表规模.py', 'DATA')
        lookup = {(row['scenario'], int(row['vehicles']), row['metric']): row
                  for row in csv_rows('state-summary.csv') if row['rsu_id'] == 'network'}
        seen = set()
        for panel in data['panels']:
            self.assertEqual(panel['xlabels'], [5, 10, 15, 20])
            for series in panel['series']:
                for vehicles, actual in zip(panel['xlabels'], series['points']):
                    key = (panel['scene'], vehicles, series['field'])
                    row = lookup[key]
                    self.assertEqual(actual['estimate'], float(row['mean']))
                    self.assertEqual(actual['run_sd'], float(row['sd']))
                    self.assertEqual(actual['repetitions'], int(row['n_runs']))
                    self.assertEqual(actual['repetitions'], 3)
                    self.assertEqual(len(series['points']), 4)
                    self.assertNotIn(key, seen)
                    seen.add(key)
        self.assertEqual(seen, {(scene, vehicles, field) for scene in SCENES
                                for vehicles in (5, 10, 15, 20)
                                for field in ('cache_vehicle_entries_mean', 'cache_vehicle_entries_peak',
                                              'cache_name_entries_mean', 'cache_name_entries_peak')})

    def test_registration_and_delta_use_only_default_period_and_correct_phases(self):
        data = literal(PACKAGE / '03_注册与更新报文大小.py', 'DATA')
        rows = csv_rows('hello-size-points.csv')
        self.assertEqual(len(data['panels']), 1)
        panel = data['panels'][0]
        self.assertEqual(panel['metric'], 'hello_wire_bytes')
        self.assertEqual(panel['xlabels'], ['Circle', 'Grid', 'Spider'])
        seen = set()
        for series in panel['series']:
            category = series['field']
            phase = {'registration': 'startup', 'delta': 'measurement'}[category]
            self.assertEqual(series['phase'], phase)
            self.assertEqual(len(series['points']), 3)
            for scene, actual in zip(SCENES, series['points']):
                selected = [row for row in rows if row['scenario'] == scene
                            and int(row['hello_interval_ms']) == 20
                            and row['category'] == category and row['phase'] == phase]
                self.assertEqual({int(row['seed_family']) for row in selected}, {84001, 84002, 84003})
                self.assertMeanSd(actual, [float(row['wire_bytes_mean']) for row in selected], 3)
                self.assertNotIn((scene, category), seen)
                seen.add((scene, category))
        self.assertEqual(seen, {(scene, category) for scene in SCENES
                                for category in ('registration', 'delta')})

    def test_inference_keeps_saved_five_process_statistics_and_microsecond_units(self):
        data = literal(PACKAGE / '04_TKAN推理时延.py', 'DATA')
        rows = csv_rows('inference-processes.csv')
        self.assertEqual(len(data['panels']), 2)
        unit_labels = [panel['ylabel'] for panel in data['panels'] if panel['ylabel']]
        self.assertTrue(unit_labels, 'A shared inference-time axis still requires a unit label.')
        for label in unit_labels:
            self.assertTrue('microseconds' in label or 'us' in label or 'μs' in label
                            or 'µs' in label or r'\mu' in label, label)
        seen = set()
        for panel in data['panels']:
            statistic = panel['metric']
            self.assertIn(statistic, ('median_us', 'p95_us'))
            self.assertEqual(panel['xlabels'], ['Circle', 'Grid', 'Spider'])
            for series in panel['series']:
                operation = series['field']
                self.assertEqual(series['statistic'], statistic)
                self.assertEqual(len(series['points']), 3)
                for scene, actual in zip(SCENES, series['points']):
                    selected = [row for row in rows if row['scenario'] == scene
                                and row['operation'] == operation]
                    self.assertEqual({int(row['repetition']) for row in selected}, {1, 2, 3, 4, 5})
                    self.assertMeanSd(actual, [float(row[statistic]) for row in selected], 5)
                    self.assertNotIn((scene, statistic, operation), seen)
                    seen.add((scene, statistic, operation))
        self.assertEqual(seen, {(scene, statistic, operation) for scene in SCENES
                                for statistic in ('median_us', 'p95_us')
                                for operation in ('forward', 'controller_compute')})

    def test_supplement_provenance_matches_the_sealed_table_hashes(self):
        for name, source in zip(SUPPLEMENTS[:4], ('accuracy-summary.csv', 'state-summary.csv',
                                                'hello-size-points.csv', 'inference-processes.csv')):
            provenance = literal(PACKAGE / (name + '.py'), 'PROVENANCE')
            self.assertEqual((ROOT / provenance['source_table']).resolve(), (SOURCE / source).resolve())
            self.assertEqual(provenance['source_sha256'], digest(SOURCE / source))

    def test_all_figure_text_is_english_and_all_legend_labels_are_final(self):
        for name in NAMES:
            with self.subTest(figure=name):
                namespace = runpy.run_path(str(PACKAGE / (name + '.py')))
                figure = namespace['draw']()
                try:
                    for text in figure.findobj(match=Text):
                        value = text.get_text()
                        self.assertIsNone(re.search(r'[\u3400-\u9fff]', value), value)
                        self.assertNotIn('Proposed', value)
                finally:
                    plt.close(figure)

    def test_all_figures_copy_individually_and_overwrite_only_own_three_images(self):
        # Audit hooks reject all original-project reads as well as writes.  Merely
        # changing cwd would not expose a hidden absolute-path data dependency.
        with tempfile.TemporaryDirectory(prefix='simulation-fill-independent-') as directory:
            temporary = Path(directory)
            guard = temporary / 'guard'
            guard.mkdir()
            (guard / 'sitecustomize.py').write_text(
                'import os, sys\n'
                'root = ' + repr(str(ROOT)) + '\n'
                'def audit(event, args):\n'
                '    if event != "open" or not args or isinstance(args[0], int):\n'
                '        return\n'
                '    path = os.path.realpath(os.fsdecode(args[0]))\n'
                '    if path == root or path.startswith(root + os.sep):\n'
                '        raise PermissionError("Original project access forbidden: " + path)\n'
                'sys.addaudithook(audit)\n', encoding='utf-8')
            unrelated = temporary / 'unrelated-working-directory'
            unrelated.mkdir()
            environment = dict(os.environ, PYTHONPATH=str(guard), PYTHONDONTWRITEBYTECODE='1',
                               MPLCONFIGDIR=str(temporary / 'matplotlib-cache'))
            for name in NAMES:
                with self.subTest(figure=name):
                    folder = temporary / name
                    folder.mkdir()
                    script = folder / (name + '.py')
                    shutil.copy2(PACKAGE / script.name, script)
                    sentinel = folder / 'another-figure.png'
                    sentinel.write_bytes(b'Unrelated user image must not change.\n')
                    initial = {script.name: digest(script), sentinel.name: digest(sentinel)}
                    expected = set(initial) | {name + '.' + extension for extension in ('png', 'svg', 'pdf')}
                    for repetition in range(2):
                        completed = subprocess.run([sys.executable, str(script)], cwd=str(unrelated),
                                                   env=environment, stdout=subprocess.PIPE,
                                                   stderr=subprocess.STDOUT, text=True, timeout=90)
                        self.assertEqual(completed.returncode, 0, completed.stdout)
                        self.assertEqual({path.name for path in folder.iterdir()}, expected)
                        self.assertEqual({key: digest(folder / key) for key in initial}, initial)
                        png = (folder / (name + '.png')).read_bytes()
                        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                        width, height = struct.unpack('>II', png[16:24])
                        self.assertGreater(width, 100)
                        self.assertGreater(height, 100)
                        self.assertTrue((folder / (name + '.pdf')).read_bytes().startswith(b'%PDF-'))
                        self.assertEqual(ET.parse(str(folder / (name + '.svg'))).getroot().tag,
                                         '{http://www.w3.org/2000/svg}svg')
                        for extension in ('png', 'svg', 'pdf'):
                            artifact = folder / (name + '.' + extension)
                            self.assertGreater(artifact.stat().st_mtime, 1)
                            if repetition == 0:
                                os.utime(str(artifact), (1, 1))
                    print('Isolated render twice: ' + name, flush=True)
            self.assertEqual(list(unrelated.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
