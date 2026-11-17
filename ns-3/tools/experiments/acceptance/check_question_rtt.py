"""Explicit acceptance for the four standalone RTT figures in 问题图片.

Requires the preserved experiment records; never invokes waf or simulation.
RTT_LEGACY_PROBE=1 applies selected new assertions to the old plotting behavior
to record a behavioral RED before implementation (not a missing-file failure).
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
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'docs/ai/问题图片'
ORIGINAL = ROOT / 'docs/ai/仿真图填充/05_三场景RTT时间变化.py'
SEEDS = {'circle': (23001,), 'grid': (23009,), 'spidermap': tuple(range(93001, 93006))}
NAMES = ('01_成功RTT_三维', '02_成功RTT_折线',
         '03_平均RTT_三维', '04_平均RTT_折线')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def literal(path, key):
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == key for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('Missing embedded literal: ' + key)


def candidate(index):
    return ORIGINAL if os.environ.get('RTT_LEGACY_PROBE') == '1' else PACKAGE / (NAMES[index] + '.py')


def source_data():
    """Reconstruct mixed-source, request-weighted statistics from sealed events."""
    index = ROOT / 'data/experiments/quick-fixed-model-20261022/workflow/figures/all/attempt-001/analysis/run-details.json'
    records = json.loads(index.read_text())['runs']
    campaign = ROOT / 'data/experiments/spider-power-20261103/analysis/results.json'
    seal = json.loads((campaign.parent.parent / 'plan/completion.json').read_text())
    assert sha(campaign) == seal['artifact_hashes']['analysis/results.json']
    power_runs = json.loads(campaign.read_text())['runs']
    original = literal(ORIGINAL, 'DATA')
    success, inclusive, counts = {}, {}, {}
    sources, bin_rows = [], []
    for scene, seeds in SEEDS.items():
        success[scene], inclusive[scene], counts[scene] = [], [], []
        for strategy in range(4):
            pooled = [dict(success_ns=[], timeout_ns=[]) for _ in range(24)]
            for seed in seeds:
                if scene == 'spidermap':
                    selected = [r for r in power_runs if r['stage'] == 'confirmation'
                                and r['power_dbm'] == 16.5 and r['seed'] == seed
                                and r['strategy'] == strategy]
                    assert len(selected) == 1
                    record = selected[0]
                    run = Path(record['path'])
                else:
                    selected = [r for r in records if r['scene'] == scene and r['condition_id'] == 'baseline'
                                and int(r['strategy']) == strategy and r['seed_family'] == seed]
                    assert len(selected) == 1
                    record = selected[0]
                    run = Path(record['run_path'])
                assert sha(run / 'manifest.json') == record['manifest_sha256']
                manifest = json.loads((run / 'manifest.json').read_text())
                assert manifest['status'] == 'complete'
                assert manifest['scenario'] == scene and int(manifest['strategy']) == strategy
                path = run / 'raw/request-events.csv'
                assert sha(path) == manifest['artifact_hashes']['raw/request-events.csv']
                source = dict(scene=scene, seed=seed, strategy=strategy,
                    path=str(path.relative_to(ROOT)), sha256=sha(path),
                    manifest=str((run / 'manifest.json').relative_to(ROOT)),
                    manifest_sha256=record['manifest_sha256'])
                if scene == 'spidermap':
                    config_path = run / 'experiment.json'
                    assert sha(config_path) == manifest['artifact_hashes']['experiment.json']
                    config = json.loads(config_path.read_text())
                    assert config['wifi_tx_power_dbm'] == 16.5
                    assert config['seeds'] == dict(rng_seed=1, rng_run=seed,
                                                    srand_seed=seed, sumo_seed=seed)
                    assert not config['validation_only']
                    radio_path = run / 'raw/radio-config.json'
                    assert sha(radio_path) == manifest['artifact_hashes']['raw/radio-config.json']
                    radio = json.loads(radio_path.read_text())
                    assert radio['rsu_count'] == 7 and radio['obu_count'] == 10
                    assert len(radio['devices']) == 17
                    assert all(d['tx_power_start_dbm'] == 16.5 and d['tx_power_end_dbm'] == 16.5
                               for d in radio['devices'])
                    source.update(wifi_tx_power_dbm=16.5,
                        radio_config=str(radio_path.relative_to(ROOT)), radio_sha256=sha(radio_path))
                generated, terminal = {}, {}
                with path.open(newline='') as stream:
                    for row in csv.DictReader(stream):
                        request_id = row['request_id']
                        destination = generated if row['event'] == 'GENERATED' else terminal
                        assert row['event'] in ('GENERATED', 'DATA', 'TIMEOUT')
                        assert request_id not in destination
                        destination[request_id] = row
                assert generated.keys() == terminal.keys() and len(generated) == 6000
                buckets = [dict(success_ns=[], timeout_ns=[]) for _ in range(24)]
                for request_id, row in terminal.items():
                    sent, deadline, ended = (int(row[k]) for k in ('send_ns', 'deadline_ns', 'time_ns'))
                    start = generated[request_id]
                    assert sent == int(start['time_ns']) == int(start['send_ns'])
                    assert deadline == int(start['deadline_ns']) == sent + 3000000000
                    assert 20000000000 <= sent < 140000000000 and sent <= ended <= deadline
                    if row['event'] == 'TIMEOUT':
                        assert ended == deadline
                    bucket = buckets[(sent - 20000000000) // 5000000000]
                    bucket['success_ns' if row['event'] == 'DATA' else 'timeout_ns'].append(ended - sent)
                for b, bucket in enumerate(buckets):
                    successes, timeouts = bucket['success_ns'], bucket['timeout_ns']
                    assert len(successes) + len(timeouts) == 250
                    pooled[b]['success_ns'].extend(successes)
                    pooled[b]['timeout_ns'].extend(timeouts)
                    bin_rows.append(dict(scene=scene, seed=seed, strategy=strategy, bin_start_s=20 + b * 5,
                        bin_end_s=25 + b * 5, generated=250, success=len(successes), timeout=len(timeouts),
                        success_sum_ns=sum(successes), timeout_sum_ns=sum(timeouts),
                        mean_success_rtt_ms=sum(successes)/len(successes)/1e6 if successes else None,
                        mean_rtt_ms=(sum(successes)+sum(timeouts))/250/1e6))
                sources.append(source)
            xs, good, all_requests, supports = [], [], [], []
            for b, bucket in enumerate(pooled):
                successes, timeouts = bucket['success_ns'], bucket['timeout_ns']
                n = len(successes) + len(timeouts)
                assert n == 250 * len(seeds)
                xs.append(22.5 + b * 5)
                good.append(sum(successes) / len(successes) / 1e6 if successes else None)
                all_requests.append((sum(successes) + sum(timeouts)) / n / 1e6)
                supports.append(dict(generated=n, success=len(successes), timeout=len(timeouts)))
            if scene != 'spidermap':
                np.testing.assert_allclose(good, original[scene][strategy]['rtt_ms'], rtol=0, atol=1e-9)
            success[scene].append(dict(strategy=strategy, x=xs, rtt_ms=good))
            inclusive[scene].append(dict(strategy=strategy, x=xs, rtt_ms=all_requests))
            counts[scene].append(dict(strategy=strategy, bins=supports))
    assert len(sources) == 28 and len(bin_rows) == 672
    assert sum(r['generated'] for r in bin_rows) == 168000
    assert sum(r['success'] for r in bin_rows) == 71510
    assert sum(r['timeout'] for r in bin_rows) == 96490
    assert sum(r['success'] for r in bin_rows if r['scene'] == 'spidermap') == 34628
    assert sum(r['timeout'] for r in bin_rows if r['scene'] == 'spidermap') == 85372
    return dict(success=success, inclusive=inclusive, counts=counts, bins=bin_rows, sources=sources)


class QuestionRttAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = source_data()

    def test_success_values_match_288_independently_pooled_points(self):
        original = literal(ORIGINAL, 'DATA')
        for scene in SEEDS:
            for strategy in range(4):
                np.testing.assert_allclose(original[scene][strategy]['rtt_ms'],
                    self.evidence['success'][scene][strategy]['rtt_ms'], rtol=0, atol=1e-9)
        for index in (0, 1):
            self.assertEqual(literal(candidate(index), 'DATA'), original)

    def test_inclusive_means_include_all_168000_terminal_records(self):
        for index in (2, 3):
            data = literal(candidate(index), 'DATA')
            for scene in SEEDS:
                for strategy in range(4):
                    actual = data[scene][strategy]
                    expected = self.evidence['inclusive'][scene][strategy]
                    self.assertEqual(actual['x'], expected['x'])
                    np.testing.assert_allclose(actual['rtt_ms'], expected['rtt_ms'], rtol=0, atol=1e-9)

    def test_each_3d_axis_starts_at_its_own_data_minimum(self):
        for index in (0, 2):
            namespace = runpy.run_path(str(candidate(index)))
            figure = namespace['draw']()
            try:
                self.assertEqual(len(figure.axes), 3)
                for axis, scene in zip(figure.axes, SEEDS):
                    values = [v for series in namespace['DATA'][scene] for v in series['rtt_ms'] if v is not None]
                    self.assertEqual(axis.name, '3d')
                    self.assertAlmostEqual(axis.get_zlim()[0], min(values), places=9)
                    self.assertGreaterEqual(axis.get_zlim()[1], max(values))
            finally:
                plt.close(figure)

    def test_line_figures_have_three_scenes_and_four_real_curves(self):
        for index in (1, 3):
            namespace = runpy.run_path(str(candidate(index)))
            figure = namespace['draw']()
            try:
                self.assertEqual(len(figure.axes), 3)
                for axis, scene in zip(figure.axes, SEEDS):
                    self.assertEqual(axis.name, 'rectilinear')
                    self.assertEqual(len(axis.lines), 4)
                    self.assertEqual(axis.get_xlabel(), 'Interest generation time (s)')
                    self.assertEqual(axis.get_ylabel(), 'Mean RTT (ms)' if index == 3 else 'Average Satisfaction Delay (ms)')
                    for line, series in zip(axis.lines, namespace['DATA'][scene]):
                        np.testing.assert_allclose(line.get_xdata(), series['x'])
                        np.testing.assert_allclose(line.get_ydata(), series['rtt_ms'])
            finally:
                plt.close(figure)

    def test_3d_curves_keep_true_values_and_labels_fit_export(self):
        for index in (0, 2):
            namespace = runpy.run_path(str(candidate(index)))
            figure = namespace['draw']()
            try:
                figure.canvas.draw()
                renderer = figure.canvas.get_renderer()
                box = figure.get_tightbbox(renderer).transformed(figure.dpi_scale_trans)
                # get_tightbbox/get_yticklabels can reset 3D tick coordinates to
                # data space. Inspect the actual rendered artists after redraw.
                figure.canvas.draw()
                for axis, scene in zip(figure.axes, SEEDS):
                    self.assertEqual(len(axis.lines), 4)
                    for line, series in zip(axis.lines, namespace['DATA'][scene]):
                        x, y, z = line.get_data_3d()
                        np.testing.assert_allclose(x, series['x'])
                        np.testing.assert_allclose(y, [series['strategy']] * len(series['x']))
                        np.testing.assert_allclose(z, series['rtt_ms'])
                    expected = 'Mean RTT (ms)' if index == 2 else 'Average Satisfaction Delay (ms)'
                    self.assertEqual(sum(t.get_text() == expected for t in axis.texts), 1)
                    tick_labels = [tick.label1 for tick in axis.yaxis.majorTicks if tick.label1.get_visible()]
                    for text in list(axis.texts) + [axis.xaxis.label] + tick_labels:
                        extent = text.get_window_extent(renderer)
                        self.assertGreaterEqual(extent.x0, box.x0 - 12)
                        self.assertGreaterEqual(extent.y0, box.y0 - 12)
                        self.assertLessEqual(extent.x1, box.x1 + 12)
                        self.assertLessEqual(extent.y1, box.y1 + 12)
            finally:
                plt.close(figure)

    def test_imports_do_not_write_or_create_figures_and_counts_are_embedded(self):
        before = {p.name: sha(p) for p in PACKAGE.iterdir() if p.is_file()}
        for index in range(4):
            figures = plt.get_fignums()
            namespace = runpy.run_path(str(candidate(index)))
            self.assertEqual(plt.get_fignums(), figures)
            self.assertEqual(namespace['SAMPLE_COUNTS'], self.evidence['counts'])
            self.assertEqual(namespace['FIGURE_ID'], NAMES[index])
        self.assertEqual({p.name: sha(p) for p in PACKAGE.iterdir() if p.is_file()}, before)

    def test_each_script_runs_alone_twice_without_original_project_access(self):
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='standalone RTT ') as temporary:
                folder = Path(temporary)
                script = folder / (name + '.py')
                shutil.copyfile(PACKAGE / script.name, script)
                digest = sha(script)
                unrelated = folder / 'unrelated.txt'
                unrelated.write_text('keep me')
                cwd = folder / 'different cwd'
                cwd.mkdir()
                wrapper = ("import os,runpy,sys\n"
                    "root=os.path.abspath(sys.argv[1])+os.sep\n"
                    "def audit(event,args):\n"
                    " if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):\n"
                    "  p=os.path.abspath(os.fsdecode(args[0]))\n"
                    "  if p.startswith(root): raise RuntimeError('Original project access: '+p)\n"
                    "sys.addaudithook(audit)\n"
                    "runpy.run_path(sys.argv[2],run_name='__main__')\n")
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', MPLCONFIGDIR=str(folder / 'mpl-cache'))
                for _ in range(2):
                    result = subprocess.run([sys.executable, '-B', '-c', wrapper, str(ROOT), str(script)],
                        cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(sha(script), digest)
                    self.assertEqual(unrelated.read_text(), 'keep me')
                    self.assertEqual({p.suffix for p in folder.glob(name + '.*')}, {'.py', '.png', '.svg', '.pdf'})
                    self.assertGreater((folder / (name + '.png')).stat().st_size, 10000)
                    self.assertTrue((folder / (name + '.pdf')).read_bytes().startswith(b'%PDF-'))
                    self.assertTrue(ET.parse(str(folder / (name + '.svg'))).getroot().tag.endswith('svg'))

    def test_saved_csv_and_embedded_provenance_match_all_28_runs(self):
        with (PACKAGE / 'RTT分箱数据.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 672)
        for actual, expected in zip(rows, self.evidence['bins']):
            self.assertEqual(set(actual), set(expected))
            for key, value in expected.items():
                if value is None:
                    self.assertEqual(actual[key], '')
                elif isinstance(value, str):
                    self.assertEqual(actual[key], value)
                else:
                    self.assertAlmostEqual(float(actual[key]), value, delta=1e-9)
        for name in NAMES:
            provenance = literal(PACKAGE / (name + '.py'), 'PROVENANCE')
            self.assertEqual(provenance['sources'], self.evidence['sources'])
            self.assertEqual(provenance['seeds']['spidermap'], list(range(93001, 93006)))
            self.assertEqual(provenance['total_requests'], 168000)

    def test_final_files_and_markdown_references(self):
        markdown = (ROOT / 'docs/ai/问题.md').read_text(encoding='utf-8')
        for name in NAMES:
            self.assertIn('](问题图片/' + name + '.png)', markdown)
            self.assertIn('](问题图片/' + name + '.py)', markdown)
            for extension in ('png', 'svg', 'pdf'):
                self.assertGreater((PACKAGE / (name + '.' + extension)).stat().st_size, 1000)
        self.assertNotIn('](问题图片/image3.png)', markdown)
        self.assertIn('](问题图片/image4.png)', markdown)
        for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', markdown):
            self.assertTrue((ROOT / 'docs/ai' / link.split('#')[0]).exists(), link)
        provenance = json.loads((PACKAGE / 'RTT数据来源.json').read_text(encoding='utf-8'))
        self.assertEqual(provenance['sources'], self.evidence['sources'])
        self.assertEqual(provenance['total_requests'], 168000)
        self.assertEqual(provenance['successful_requests'], sum(r['success'] for r in self.evidence['bins']))
        self.assertEqual(provenance['timeouts'], sum(r['timeout'] for r in self.evidence['bins']))


if __name__ == '__main__':
    unittest.main()
