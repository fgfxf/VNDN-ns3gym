"""The approved fixed-model matrix and historical/current provenance boundary."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('fixed_campaign_tests', Path(__file__).resolve().parents[1] / 'campaign.py')
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)
PROFILE = 'quick-fixed-model-v1'
SEEDS = {'circle': [23001, 23002], 'grid': [23009, 23010], 'spidermap': [23017, 23018]}


class FixedModelCampaignTests(unittest.TestCase):
    def plan(self):
        return C.make_plan('fixed-test', profile=PROFILE)

    def test_approved_matrix_is_264_jobs_without_any_sampling(self):
        plan = self.plan()
        self.assertEqual((plan['measurement_start'], plan['measurement_duration'], plan['drain_seconds']), (20, 120, 3.5))
        self.assertEqual(len(plan['conditions']), 11)
        self.assertEqual(plan['test_seeds_by_scene'], SEEDS)
        byid = {r['id']: r for r in plan['conditions']}
        self.assertEqual([byid[c]['requests'] for c in plan['scans']['interest']], [1500, 3000, 6000, 9000, 12000])
        self.assertEqual([byid[c]['speed_kmh'] for c in plan['scans']['speed']], [15, 30, 50, 60])
        self.assertEqual([byid[c]['vehicles'] for c in plan['scans']['vehicles']], [5, 10, 15, 20])
        self.assertEqual(len(C.jobs_for(plan, 'test')), 264)
        for split in ('pilot', 'train', 'validation', 'evaluation'):
            self.assertEqual(C.jobs_for(plan, split), [])
        self.assertTrue(plan['training_reuse'])
        self.assertEqual(plan['seed_policy'], 'training-seed-reuse-exploratory')
        self.assertEqual(len(plan['figure_ids']), 22)
        self.assertFalse(any('confusion' in name for name in plan['figure_ids']))

    def test_cli_float_duration_preserves_integer_request_counts(self):
        plan = C.make_plan('float-time', duration=120.0, profile=PROFILE)
        for condition in plan['conditions']:
            self.assertIs(type(condition['requests']), int)

    def test_first_twelve_are_first_scene_seeds_baseline_four_strategies(self):
        jobs = C.jobs_for(self.plan(), 'test')
        self.assertEqual([(j['scene'], j['seed_family'], j['strategy'], j['condition_id']) for j in jobs[:12]],
                         [(s, SEEDS[s][0], a, 'baseline') for s in C.SCENES for a in range(4)])
        self.assertEqual(len({j['job_id'] for j in jobs}), 264)
        for scene in C.SCENES:
            subset = [j for j in jobs if j['scene'] == scene]
            self.assertEqual(len(subset), 88)
            self.assertEqual({j['seed_family'] for j in subset}, set(SEEDS[scene]))

    def test_profile_rejects_matrix_seed_window_or_sampling_changes(self):
        mutations = [lambda p: p['conditions'][0].update(requests=6001),
                     lambda p: p['test_seeds_by_scene']['grid'].__setitem__(0, 23001),
                     lambda p: p['seed_families']['test'].append(52001),
                     lambda p: p['seed_families']['train'].append(23001),
                     lambda p: p.update(measurement_duration=121),
                     lambda p: p.update(training_reuse=False),
                     lambda p: p['scans']['speed'].reverse(),
                     lambda p: p.update(pilot_conditions=['baseline'])]
        for mutate in mutations:
            plan = self.plan()
            mutate(plan)
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                C.validate_sampling_plan(plan)
        with self.assertRaises(ValueError):
            C.make_plan('wrong', duration=300, profile=PROFILE)

    def test_execution_identity_includes_per_scene_assignment_and_binding(self):
        plan = self.plan()
        changed = copy.deepcopy(plan)
        changed['test_seeds_by_scene']['circle'].reverse()
        self.assertNotEqual(C.execution_identity(plan, 'test'), C.execution_identity(changed, 'test'))
        changed = copy.deepcopy(plan)
        changed['external_models'] = {'source_root': '/changed'}
        self.assertNotEqual(C.execution_identity(plan, 'test'), C.execution_identity(changed, 'test'))

    def test_old_profiles_remain_distinct(self):
        self.plan()
        self.assertEqual(len(C.jobs_for(C.make_plan('old', profile=C.QUICK_PROFILE), 'test')), 192)
        self.assertEqual(len(C.jobs_for(C.make_plan('old', profile=C.COMPACT_PROFILE), 'test')), 480)
        self.assertEqual(len(C.jobs_for(C.make_plan('old'), 'test')), 4080)

    def fixture(self, temp):
        root, old = Path(temp) / 'new', Path(temp) / 'old'
        C.initialize(root, self.plan())
        old_plan = C.make_plan('old', profile=C.QUICK_PROFILE)
        old_plan.update(status='formal-frozen', source_sha256='a' * 64, models={})
        checkpoints = {}
        for scene in C.SCENES:
            d = old / scene
            d.mkdir(parents=True)
            checkpoint = d / 'checkpoint.pt'
            checkpoint.write_bytes(('model-' + scene).encode())
            spec = d / 'sources.json'
            spec.write_text('{}')
            dataset = d / 'dataset-manifest.json'
            data = dict(scenario=scene, validation_only=False, source_code_sha256='a' * 64,
                        observation_contract='rsu-hello-window-v1', label_contract='source-rsu-router-return-serving-rsu-v1',
                        sequence_length=10, feature_names=['x','y','speed','acceleration','angle','lane_index'],
                        label_values=list(range(2 if scene == 'circle' else 7)), split_version='v1',
                        source_specification=str(spec), source_specification_sha256=C.digest(spec),
                        splits={'train': {'seed_families': list(range(SEEDS[scene][0], SEEDS[scene][0] + 8))}})
            C.runner.write_json(dataset, data)
            contract = dict(source_code_sha256='a' * 64, dataset_manifest_sha256=C.digest(dataset),
                            observation_contract=data['observation_contract'], label_contract=data['label_contract'],
                            split_version='v1', threshold_gap=.1, threshold_min_second_probability=.1)
            checkpoints[scene] = dict(formal_contract=contract, scenario=scene, feature_names=data['feature_names'],
                                     label_values=data['label_values'], model_parameters={'sequence_length': 10})
            model = dict(path=str(checkpoint), sha256=C.digest(checkpoint))
            old_plan['models'][scene] = model
            C.runner.write_json(d / 'model-manifest.json', dict(scenario=scene, frozen=True, validation_only=False,
                checkpoint_path=str(checkpoint), checkpoint_sha256=model['sha256'],
                dataset_manifest=str(dataset), dataset_manifest_sha256=C.digest(dataset)))
        C.initialize(old, old_plan)
        return root, old, checkpoints

    def binding(self, root, old, checkpoints):
        module = C._module('fixed_models')
        original_module = C._module
        with patch.object(C, '_module', side_effect=lambda name: module if name == 'fixed_models' else original_module(name)), patch.object(module, 'load_checkpoint', side_effect=lambda path, scene: checkpoints[scene]), patch.object(C.runner, 'source_snapshot', return_value={'sha256': 'b' * 64}):
            return C.bind_external_models(root, old, 1800)

    def test_historical_model_binding_preserves_old_contract_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root, old, checkpoints = self.fixture(temp)
            before = {str(p): p.read_bytes() for p in old.rglob('*') if p.is_file()}
            plan = self.binding(root, old, checkpoints)
            self.assertEqual(plan['status'], 'formal-frozen')
            self.assertEqual(plan['source_sha256'], 'b' * 64)
            ext = plan['external_models']
            self.assertEqual(ext['source_root'], str(old.resolve()))
            self.assertEqual(ext['training_source_sha256'], 'a' * 64)
            self.assertEqual(ext['runtime_source_sha256'], 'b' * 64)
            self.assertTrue(C.check_external_models(plan))
            frozen = (root / 'plan/design.json').read_bytes()
            self.binding(root, old, checkpoints)
            self.assertEqual((root / 'plan/design.json').read_bytes(), frozen)
            self.assertEqual(before, {str(p): p.read_bytes() for p in old.rglob('*') if p.is_file()})
            with patch.object(C.runner, 'source_snapshot', return_value={'sha256': 'c' * 64}), self.assertRaisesRegex(ValueError, 'source'):
                C.bind_external_models(root, old, 1800)

    def test_binding_rejects_corrupt_model_or_wrong_training_seed_without_freezing(self):
        for invalid in ('model', 'seed', 'contract'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temp:
                root, old, checkpoints = self.fixture(temp)
                original = (root / 'plan/design.json').read_bytes()
                if invalid == 'model':
                    (old / 'circle/checkpoint.pt').write_bytes(b'corrupt')
                elif invalid == 'seed':
                    dataset = old / 'circle/dataset-manifest.json'
                    data = C.runner.summary.read_json(dataset)
                    data['splits']['train']['seed_families'] = [999]
                    C.runner.write_json(dataset, data)
                    manifest = old / 'circle/model-manifest.json'
                    md = C.runner.summary.read_json(manifest)
                    md['dataset_manifest_sha256'] = C.digest(dataset)
                    C.runner.write_json(manifest, md)
                    checkpoints['circle']['formal_contract']['dataset_manifest_sha256'] = C.digest(dataset)
                else:
                    checkpoints['circle']['formal_contract']['source_code_sha256'] = 'c' * 64
                with self.assertRaises(ValueError):
                    self.binding(root, old, checkpoints)
                self.assertEqual((root / 'plan/design.json').read_bytes(), original)

    def test_frozen_binding_detects_each_dependency_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root, old, checkpoints = self.fixture(temp)
            plan = self.binding(root, old, checkpoints)
            for name in C.check_external_models(plan):
                path = Path(name)
                before = path.read_bytes()
                path.write_bytes(before + b' ')
                with self.subTest(path=name), self.assertRaises(ValueError):
                    C.check_external_models(plan)
                path.write_bytes(before)

    def test_completed_fixed_job_is_reused_and_only_next_job_is_started(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan()
            plan.update(status='formal-frozen', source_sha256='runtime', models={})
            C.initialize(root, plan)
            calls = []
            def run(root, plan, job, number, *args, **kwargs):
                calls.append(job['job_id'])
                path = root / 'evidence' / job['job_id'] / 'manifest.json'
                path.parent.mkdir(parents=True)
                C.runner.write_json(path, dict(status='complete', block_id=job['block_id'], scenario=job['scene'],
                    strategy=job['strategy'], source={'sha256': 'runtime'}, validation_only=False, input_hashes={'input':'same'}))
                return dict(attempt=number, status='complete', manifest_path=str(path), manifest_sha256=C.digest(path))
            with patch.object(C.runner, 'source_snapshot', return_value={'sha256':'runtime'}), patch.object(C, 'check_external_models', return_value={}), patch.object(C, '_run_job', side_effect=run), patch.object(C, 'prepare_job_input', return_value=root/'input.json'), patch.object(C.runner, 'prepare_inputs', return_value=({}, {'input':'same'})), patch.object(C.runner.summary, 'summarize_run', return_value={}):
                C.execute(root, 'test', max_jobs=1, no_build=True)
                C.execute(root, 'test', max_jobs=1, no_build=True)
            expected = [j['job_id'] for j in C.jobs_for(plan, 'test')[:2]]
            self.assertEqual(calls, expected)
            state = C.runner.summary.read_json(root/'plan/state-test.json')
            self.assertEqual(sum(j['status']=='complete' for j in state['jobs'].values()), 2)


if __name__ == '__main__':
    unittest.main()
