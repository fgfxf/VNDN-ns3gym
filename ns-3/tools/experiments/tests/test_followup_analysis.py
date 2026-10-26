"""Supplementary evaluation needs no training split or complete class coverage."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
AI = ROOT / 'contrib/vndn-nn-rd/ai-training'
sys.path.insert(0, str(AI))
sys.path.insert(0, str(AI / 'tests'))
import formal_data
from formal_test_support import fixture_run, reseal, sha, write_json


class EvaluationOnlyContract(unittest.TestCase):
    def test_evaluation_only_sources_do_not_require_training_or_all_classes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = fixture_run(root, 'evaluation')
            path = run / 'raw/data-rx.csv'
            path.write_text('\n'.join(path.read_text().splitlines()[:-1]) + '\n')
            reseal(run)
            spec = root / 'sources.json'
            write_json(spec, dict(schema_version=1, scenario='circle', validation_only=True,
                split_version='evaluation-only', runs=[dict(path=str(run), split='evaluation',
                seed_family=1, condition_id='baseline', manifest_sha256=sha(run / 'manifest.json'))]))
            # Before the adapter exists, exercise the existing real dataset entry:
            # it rejects this valid evaluation-only input for requiring training splits.
            module_path = ROOT / 'tools/experiments/followup_analysis.py'
            if module_path.exists():
                module_spec = importlib.util.spec_from_file_location('followup_test', module_path)
                module = importlib.util.module_from_spec(module_spec)
                module_spec.loader.exec_module(module)
                result = module.materialize_evaluation_run(run, root / 'dataset',
                    manifest_sha256=sha(run / 'manifest.json'), scenario='circle',
                    seed_family=1, condition_id='baseline', allow_validation_only=True)
                self.assertEqual(result['sample_count'], 1)
                self.assertEqual(result['excluded'], {'missing_return': 1})
                self.assertEqual(result['class_counts'], [1, 0])
            else:
                formal_data.build_dataset(spec, root / 'dataset')




def analysis_module():
    spec = importlib.util.spec_from_file_location('followup_test',
        ROOT / 'tools/experiments/followup_analysis.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplementaryAnalysisContracts(unittest.TestCase):
    def setUp(self):
        self.a = analysis_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def state(self, t, event, rsu, value):
        return dict(time_ns=t, event=event, rsu_id=rsu,
                    **{field: value for field in self.a.STATE_FIELDS})

    def test_event_time_weighting_and_simultaneous_network_peak(self):
        rows = [self.state(0, 'START', 0, 0), self.state(0, 'START', 1, 0),
                self.state(5, 'CHANGE', 0, 4), self.state(15, 'CHANGE', 0, 0),
                self.state(15, 'CHANGE', 1, 4), self.state(30, 'STOP', 0, 0),
                self.state(30, 'STOP', 1, 4)]
        result = self.a.state_statistics(rows, 10, 20, expected_rsus=[0, 1])
        network = [r for r in result if r['rsu_id'] == 'network'][0]
        self.assertEqual(network['present_vehicles_mean'], 4)
        self.assertEqual(network['present_vehicles_peak'], 4)
        individual = [r for r in result if r['rsu_id'] != 'network']
        self.assertEqual([r['present_vehicles_mean'] for r in individual], [2, 2])
        self.assertEqual(sum(r['present_vehicles_peak'] for r in individual), 8)

    def test_state_requires_start_stop_and_all_expected_rsus(self):
        rows = [self.state(0, 'START', 0, 0), self.state(15, 'CHANGE', 0, 1)]
        with self.assertRaisesRegex(ValueError, 'STOP|cover'):
            self.a.state_statistics(rows, 10, 20, expected_rsus=[0])
        rows.append(self.state(30, 'STOP', 0, 1))
        with self.assertRaisesRegex(ValueError, 'RSU|rsu'):
            self.a.state_statistics(rows, 10, 20, expected_rsus=[0, 1])

    def test_state_negative_count_or_unsorted_time_is_rejected(self):
        for rows in ([self.state(0, 'START', 0, 0), self.state(30, 'STOP', 0, -1)],
                     [self.state(0, 'START', 0, 0), self.state(25, 'CHANGE', 0, 1),
                      self.state(20, 'STOP', 0, 1)]):
            with self.assertRaises(ValueError):
                self.a.state_statistics(rows, 10, 20)

    def test_payload_phases_and_encoded_bytes_are_not_network_bytes(self):
        rows = [dict(time_ns=t, obu_node_id=2, rsu_id=0, category=category,
                     content_bytes=content, wire_bytes=content+30,
                     cache_items=1, added_items=0, removed_items=0)
                for t, category, content in [(1, 'registration', 40),
                    (10, 'unchanged', 10), (19, 'unchanged', 20), (20, 'delta', 30)]]
        result = self.a.payload_statistics(rows, 10, 20, 25)
        by_key = {(r['phase'], r['category']): r for r in result}
        self.assertEqual(by_key['startup', 'registration']['count'], 1)
        self.assertEqual(by_key['measurement', 'unchanged']['wire_bytes_total'], 90)
        self.assertEqual(by_key['measurement', 'unchanged']['content_bytes_mean'], 15)
        self.assertEqual(by_key['measurement', 'unchanged']['wire_bytes_p95'], 49.5)
        self.assertEqual(by_key['drain', 'delta']['count'], 1)
        self.assertIn('application', by_key['drain', 'delta']['scope'])
        rows[0]['wire_bytes'] = 1
        with self.assertRaisesRegex(ValueError, 'wire|content'):
            self.a.payload_statistics(rows, 10, 20, 25)

    def test_repeat_summary_retains_na_runs_and_uses_runs_not_packets(self):
        result = self.a.repeat_statistics([1, 3, None])
        self.assertEqual(result['n_runs'], 3)
        self.assertEqual(result['n_defined'], 2)
        self.assertEqual(result['mean'], 2)
        self.assertAlmostEqual(result['sd'], 2 ** .5)
        self.assertIsNone(self.a.repeat_statistics([None, None])['mean'])

    def test_histogram_quantiles_match_actual_linear_quantiles(self):
        result = self.a.histogram_statistics({1: 2, 3: 1, 9: 1})
        self.assertEqual(result['count'], 4)
        self.assertEqual(result['median'], 2)
        self.assertAlmostEqual(result['p95'], 8.1)
        self.assertEqual(result['total'], 14)

    def test_evaluation_adapter_checks_input_hashes(self):
        run = fixture_run(self.root, 'evaluation')
        digest = sha(run / 'manifest.json')
        with (run / 'raw/data-rx.csv').open('a') as stream:
            stream.write('999,0,258,/tampered\n')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.a.materialize_evaluation_run(run, self.root / 'out', digest, 'circle', 1,
                'baseline', allow_validation_only=True)

    def test_empty_evaluation_is_reported_not_training_rejected(self):
        run = fixture_run(self.root, 'evaluation')
        path = run / 'raw/data-rx.csv'
        path.write_text(path.read_text().splitlines()[0] + '\n')
        reseal(run)
        result = self.a.materialize_evaluation_run(run, self.root / 'out',
            sha(run / 'manifest.json'), 'circle', 1, 'baseline', allow_validation_only=True)
        self.assertEqual(result['sample_count'], 0)
        self.assertEqual(result['excluded'], {'missing_return': 2})

    def test_prediction_summary_preserves_label_order_and_short_history(self):
        result = self.a.prediction_statistics([[.9, .1], [.8, .2]], [1, 0],
            [dict(handover=True, actual_history_length=1, request_id='a'),
             dict(handover=False, actual_history_length=10, request_id='b')], [1, 0])
        self.assertEqual(result['accuracy_percent'], 50)
        self.assertEqual(result['handover_accuracy_percent'], 100)
        self.assertEqual(result['short_history_count'], 1)
        self.assertEqual(result['full_history_count'], 1)
        self.assertEqual(result['confusion_matrix'], [[0, 1], [0, 1]])
        empty = self.a.prediction_statistics([], [], [], [0, 1])
        self.assertIsNone(empty['accuracy_percent'])
        self.assertIsNone(empty['handover_accuracy_percent'])

    def test_benchmark_excludes_warmup_and_has_exact_timed_count(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('benchmark_test',
            ROOT / 'tools/experiments/followup_benchmark.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []
        ticks = iter([0, 1000, 3000, 7000, 8000, 17000])
        result = module.measure(lambda: calls.append(1), 2, 3, lambda: next(ticks))
        self.assertEqual(len(calls), 5)
        self.assertEqual(result, [1., 4., 9.])

    def test_control_wire_histogram_excludes_data_relay_and_startup(self):
        base = dict(time_ns=15, direction='OUT', packet_type='DATA',
                    semantic_class='hello', wire_bytes=40)
        rows = [base, dict(base, time_ns=1), dict(base, semantic_class='relay_data'),
                dict(base, direction='IN'), dict(base, packet_type='NACK')]
        stats = self.a.packet_statistics(rows, 10, 20)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['count'], 1)
        self.assertEqual(stats[0]['total'], 40)

    def test_partial_matrix_is_rejected_before_reading_any_run(self):
        with self.assertRaisesRegex(ValueError, '36 accuracy'):
            self.a.verified_tasks(self.root, dict(tasks=[]))

    def test_cached_shard_cannot_hide_modified_derived_features(self):
        run = fixture_run(self.root, 'evaluation')
        destination = self.root / 'out'
        digest = sha(run / 'manifest.json')
        result = self.a.materialize_evaluation_run(run, destination, digest, 'circle', 1,
            'baseline', allow_validation_only=True)
        with (destination / result['features']).open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.a.materialize_evaluation_run(run, destination, digest, 'circle', 1,
                'baseline', allow_validation_only=True)

    def test_all_na_curve_does_not_emit_fabricated_zero_values(self):
        import warnings
        spec = importlib.util.spec_from_file_location('followup_figure_test',
            ROOT / 'tools/experiments/followup_figures.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fig, ax = module.plt.subplots()
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            module.draw_runs(ax, [20, 40], [[None] * 3, [None] * 3], 'absent', 'black')
        self.assertFalse([w for w in seen if 'All-NaN' in str(w.message)])
        self.assertTrue(all(str(v) == 'nan' for v in ax.lines[0].get_ydata()))
        module.plt.close(fig)

    def test_effective_period_and_neighbor_expiry_must_match_planned_configuration(self):
        valid = dict(hello_interval_ms=80, rsu_timeout_ms=160,
                     obu_neighbor_timeout_ms=2000, resource_observations=True)
        self.a.validate_effective_period(valid, 80)
        for field, wrong in [('hello_interval_ms', 20), ('rsu_timeout_ms', 40),
                             ('obu_neighbor_timeout_ms', 300), ('resource_observations', False)]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, 'effective'):
                    self.a.validate_effective_period(dict(valid, **{field: wrong}), 80)

    def test_completed_figures_reject_changed_analysis_csv(self):
        spec = importlib.util.spec_from_file_location('followup_cache_test',
            ROOT / 'tools/experiments/followup_figures.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (self.root / 'plan').mkdir()
        (self.root / 'analysis').mkdir()
        (self.root / 'figures').mkdir()
        write_json(self.root / 'plan/followup-manifest.json', {})
        write_json(self.root / 'analysis/run-analysis.json', {})
        csv_file = self.root / 'analysis/accuracy-runs.csv'
        csv_file.write_text('value\n1\n')
        if hasattr(module, 'figure_identity'):
            identity = module.figure_identity(self.root)
        else:
            identity = dict(followup_manifest_sha256=sha(self.root / 'plan/followup-manifest.json'),
                plot_code_sha256=sha(ROOT / 'tools/experiments/followup_figures.py'),
                primary_code_sha256=sha(ROOT / 'tools/experiments/followup_primary_figures.py'))
        write_json(self.root / 'figures/figure-index.json', dict(identity=identity,
            artifact_hashes={}, figure_count=0))
        csv_file.write_text('value\n2\n')
        with self.assertRaisesRegex(ValueError, 'identity'):
            module.render_all(self.root, self.root / 'unused-old-root', [], [], [], [], [], [], lambda *args: None)


    def test_figure_identity_binds_analysis_code_but_not_later_outputs(self):
        spec = importlib.util.spec_from_file_location('followup_identity_test',
            ROOT / 'tools/experiments/followup_figures.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (self.root / 'plan').mkdir()
        (self.root / 'analysis').mkdir()
        write_json(self.root / 'plan/followup-manifest.json', {})
        write_json(self.root / 'analysis/run-analysis.json', {})
        initial = module.figure_identity(self.root)
        self.assertEqual(initial['analysis_code_sha256'], sha(ROOT / 'tools/experiments/followup_analysis.py'))
        (self.root / 'analysis/source-index.csv').write_text('later output')
        write_json(self.root / 'analysis/summary.json', {})
        self.assertEqual(initial, module.figure_identity(self.root))
        (self.root / 'analysis/inference-processes.csv').write_text('new latency data')
        self.assertNotEqual(initial, module.figure_identity(self.root))


if __name__ == '__main__':
    unittest.main()
