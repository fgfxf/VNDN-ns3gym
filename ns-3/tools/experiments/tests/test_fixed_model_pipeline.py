"""Fixed historical models go directly to paired comparisons and figures."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixed_pipeline', HERE / 'run_campaign_pipeline.py')
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)
PROFILE = 'quick-fixed-model-v1'


class FixedModelPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'plan').mkdir()
        self.source = self.root / 'historical'
        self.source.mkdir()
        self.plan = dict(design_profile=PROFILE, status='candidate-unfrozen',
                         timeouts={}, source_sha256=None, models={})
        self.save()
        self.settings = dict(profile=PROFILE, model_source=str(self.source),
                             training_config=None, run_timeout=900,
                             stage_timeout=7200, python='python3.8')

    def save(self):
        (self.root / 'plan/design.json').write_text(json.dumps(self.plan))

    def invoke(self, action, fail_binding=False, fail_stage=None):
        self.calls = []

        def bind(root, source, timeout):
            self.calls.append('bind')
            if fail_binding:
                raise ValueError('historical checkpoint changed')
            self.assertEqual(Path(source), self.source)
            self.assertEqual(timeout, 900)
            self.plan.update(status='formal-frozen', source_sha256='current-source',
                             timeouts={'default': 900}, models={scene: {'path': scene + '.pt',
                             'sha256': scene} for scene in pipeline.SCENES},
                             external_models={'source_root': str(self.source)})
            self.save()

        def checked(plan):
            self.calls.append('check')
            self.assertEqual(plan['status'], 'formal-frozen')
            return {}

        def run(command, *args):
            self.calls.append(command)
            if fail_stage and fail_stage in command:
                raise RuntimeError('stage failed')

        with mock.patch.object(pipeline, 'active_children', return_value=[]), \
                mock.patch.object(pipeline, 'seal_source'), \
                mock.patch.object(pipeline, 'prepare_campaign', side_effect=AssertionError('training called')), \
                mock.patch.object(pipeline, 'completed_product', side_effect=AssertionError('local training required')), \
                mock.patch.object(pipeline.campaign, 'bind_external_models', side_effect=bind, create=True), \
                mock.patch.object(pipeline.campaign, 'check_external_models', side_effect=checked, create=True), \
                mock.patch.object(pipeline, 'run_command', side_effect=run):
            return pipeline.execute(self.root, action, self.settings)

    def test_all_binds_existing_models_and_runs_only_test_then_figures(self):
        result = self.invoke('all')
        self.assertEqual(result['status'], 'complete')
        commands = [c for c in self.calls if isinstance(c, list)]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][commands[0].index('--split') + 1], 'test')
        self.assertIn('--no-build', commands[0])
        self.assertEqual(commands[1][2], 'figures')
        self.assertEqual(self.calls[0], 'bind')
        self.assertIn('check', self.calls)

    def test_prepare_only_binds_models(self):
        result = self.invoke('prepare')
        self.assertEqual(result['status'], 'ready-for-formal')
        self.assertFalse(any(isinstance(c, list) for c in self.calls))

    def test_invalid_historical_model_prevents_all_simulation(self):
        with self.assertRaisesRegex(ValueError, 'checkpoint changed'):
            self.invoke('all', fail_binding=True)
        self.assertEqual(self.calls, ['bind'])

    def test_formal_can_use_bound_models_without_local_training_products(self):
        self.invoke('prepare')
        result = self.invoke('formal')
        self.assertEqual(result['status'], 'formal-complete')
        commands = [c for c in self.calls if isinstance(c, list)]
        self.assertEqual(len(commands), 1)
        self.assertIn('--no-build', commands[0])

    def test_failed_simulation_prevents_figures_and_preserves_failure_state(self):
        with self.assertRaisesRegex(RuntimeError, 'stage failed'):
            self.invoke('all', fail_stage='test')
        state = pipeline.read_json(self.root / 'plan/pipeline-state.json')
        self.assertEqual(state['status'], 'failed')
        commands = [c for c in self.calls if isinstance(c, list)]
        self.assertEqual(len(commands), 1)

    def test_progress_shows_model_reuse_and_skips_training(self):
        self.invoke('prepare')
        with mock.patch.object(pipeline, 'planned_jobs', return_value=[]):
            report = pipeline.progress(self.root)
        self.assertEqual(report.get('models_reused'), 3)
        self.assertTrue(report.get('training_skipped'))
        with contextlib.redirect_stdout(io.StringIO()) as text:
            pipeline.display(report)
        self.assertIn('模型: 3/3 已复用', text.getvalue())
        self.assertIn('采样、训练: 已跳过', text.getvalue())

    def test_cli_accepts_explicit_historical_model_source(self):
        with mock.patch.object(pipeline, 'execute', return_value={'status': 'complete'}) as execute, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = pipeline.main(['all', '--root', str(self.root), '--profile', PROFILE,
                                    '--model-source', str(self.source), '--run-timeout', '900'])
        self.assertEqual(result, 0)
        self.assertEqual(execute.call_args[0][2]['model_source'], str(self.source))


if __name__ == '__main__':
    unittest.main()
