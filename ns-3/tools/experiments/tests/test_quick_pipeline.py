"""Explicit quick-draft execution, keeping prepare separate from formal work."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('quick_pipeline', HERE / 'run_campaign_pipeline.py')
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class QuickPipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'plan').mkdir()
        self.plan = dict(design_profile='quick-draft-v1', status='development-frozen',
                         timeouts={'default':900}, source_sha256='test-source')
        (self.root/'plan/design.json').write_text(json.dumps(self.plan))
        self.config = self.root/'training.json'
        self.config.write_text(json.dumps(dict(epochs=30, initialization_seeds=[62021])))
        self.settings = dict(profile='quick-draft-v1', training_config=str(self.config),
                             run_timeout=900, stage_timeout=7200, python='python3.8')
        self.validator = mock.Mock()
        self.workflow = types.SimpleNamespace(_configuration=self.validator)

    def invoke(self, action, preparation=None):
        self.commands=[]
        def prepare(root, settings, step):
            self.commands.append('prepare')
            if preparation:
                preparation()
            return 'ready-for-formal'
        def run(command, *args):
            self.commands.append(command)
        with mock.patch.object(pipeline, 'active_children', return_value=[]), \
                mock.patch.object(pipeline, 'seal_source'), \
                mock.patch.object(pipeline, 'module', return_value=self.workflow), \
                mock.patch.object(pipeline, 'prepare_campaign', side_effect=prepare), \
                mock.patch.object(pipeline, 'completed_product', return_value={'status':'complete'}), \
                mock.patch.object(pipeline, 'run_command', side_effect=run):
            return pipeline.execute(self.root, action, self.settings)

    def test_explicit_all_runs_preparation_then_comparisons_then_figures(self):
        result=self.invoke('all')
        self.assertEqual(result['status'],'complete')
        self.assertEqual(self.commands[0],'prepare')
        self.assertEqual(len(self.commands),3)
        self.assertIn('--no-build',self.commands[1])
        self.assertEqual(self.commands[1][self.commands[1].index('--split')+1],'test')
        self.assertEqual(self.commands[2][2],'figures')
        self.validator.assert_called_once_with(self.config,profile='quick-draft-v1')

    def test_quick_prepare_alone_never_starts_comparisons(self):
        result=self.invoke('prepare')
        self.assertEqual(result['status'],'ready-for-formal')
        self.assertEqual(self.commands,['prepare'])

    def test_failed_preparation_prevents_comparisons_and_figures(self):
        def fail():
            raise RuntimeError('coverage is insufficient')
        with self.assertRaisesRegex(RuntimeError,'coverage is insufficient'):
            self.invoke('all',fail)
        self.assertEqual(self.commands,['prepare'])
        state=json.loads((self.root/'plan/pipeline-state.json').read_text())
        self.assertEqual(state['status'],'failed')

    def test_requested_profile_cannot_reinterpret_existing_design(self):
        self.settings['profile']='compact-exploratory-v1'
        with self.assertRaisesRegex(ValueError,'profile'):
            self.invoke('all')
        self.assertFalse(self.commands)


if __name__ == '__main__':
    unittest.main()
