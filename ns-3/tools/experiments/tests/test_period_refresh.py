"""A period-only refresh must keep the approved matrix and avoid other experiments."""
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/experiments' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PeriodRefreshTests(unittest.TestCase):
    def test_period_matrix_is_checked_before_reading_runtime_evidence(self):
        campaign, analysis = module('followup_campaign'), module('followup_analysis')
        tasks = campaign.make_tasks('period-only')
        class EvidenceRead(Exception):
            pass
        with patch.object(analysis.data, 'read_json', side_effect=EvidenceRead):
            with self.assertRaises(EvidenceRead):
                analysis.verified_tasks(Path('/unused'), dict(profile='period-only', tasks=tasks))
            tasks[0]['hello_interval_ms'] = 40
            with self.assertRaisesRegex(ValueError, 'matrix'):
                analysis.verified_tasks(Path('/unused'), dict(profile='period-only', tasks=tasks))

    def test_resume_rejects_switching_a_frozen_historical_plan_to_period_only(self):
        campaign = module('followup_campaign')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan').mkdir()
            path = root / 'plan/followup-manifest.json'
            path.write_text(json.dumps(dict(run_timeout_seconds=900)))
            (root / 'plan/followup-manifest.sha256').write_text(campaign.sha(path) + '\n')
            with self.assertRaisesRegex(ValueError, 'Profile'):
                campaign.initialize(root, 900, 'period-only')

    def test_only_36_paired_accuracy_runs_with_four_wider_periods(self):
        campaign = module('followup_campaign')
        # Exercise the old real matrix before the profile exists, giving a
        # behavioral RED (99 unwanted runs), rather than an import/API error.
        tasks = (campaign.make_tasks('period-only') if 'profile' in
                 inspect.signature(campaign.make_tasks).parameters else campaign.make_tasks())
        self.assertEqual(len(tasks), 36)
        self.assertEqual({t['stage'] for t in tasks}, {'accuracy'})
        self.assertEqual({t['strategy'] for t in tasks}, {0})
        self.assertEqual({t['hello_interval_ms'] for t in tasks}, {20, 200, 1000, 2000})
        self.assertEqual(len({t['id'] for t in tasks}), 36)
        for scene in campaign.SCENES:
            for seed in (84001, 84002, 84003):
                group = [t for t in tasks if t['scene'] == scene and t['seed'] == seed]
                self.assertEqual({t['hello_interval_ms'] for t in group}, {20, 200, 1000, 2000})
                self.assertTrue(all(t['requests'] == 6000 and t['vehicles'] == 10 and
                                    t['speed_kmh'] == 30 and t['training_snapshots'] and
                                    t['rsu_timeout_ms'] == 2 * t['hello_interval_ms'] and
                                    t['obu_neighbor_timeout_ms'] == 2000 for t in group))

    def test_period_only_analysis_never_runs_cpu_benchmarks_or_historical_figures(self):
        analysis = module('followup_analysis')
        campaign = module('followup_campaign')
        tasks = campaign.make_tasks()[:36]
        models = {scene: dict(path='fixed-' + scene, sha256='model') for scene in campaign.SCENES}
        records = [(task, Path('/unused') / task['id'], {'artifact_hashes': {}}, {},
                    {'manifest_sha256': 'run'}) for task in tasks]
        result = dict(sample_count=1, accuracy_percent=90., handover_accuracy_percent=80.,
                      evaluable_observation_percent=100., evaluable_request_percent=100.,
                      short_history_count=1, empty_history_count=0, benchmark_input='unused')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan').mkdir()
            (root / 'plan/followup-manifest.json').write_text(json.dumps(dict(
                profile='period-only', tasks=tasks, models=models)))
            with patch.object(analysis, 'verified_tasks', return_value=records), \
                    patch.object(analysis.data, 'verify_hash'), \
                    patch.object(analysis, 'materialize_evaluation_run', return_value={}), \
                    patch.object(analysis, 'evaluate_shard', return_value=result), \
                    patch.object(analysis, 'run_benchmarks', side_effect=AssertionError('unwanted CPU benchmark')):
                report = analysis.analyze(root)
            self.assertEqual(report['counts'], dict(accuracy=36, online=0, cpu_processes=0))
            self.assertTrue((root / 'analysis/accuracy-summary.csv').is_file())
            self.assertFalse((root / 'analysis/benchmark').exists())
            self.assertFalse((root / 'figures').exists())


if __name__ == '__main__':
    unittest.main()
