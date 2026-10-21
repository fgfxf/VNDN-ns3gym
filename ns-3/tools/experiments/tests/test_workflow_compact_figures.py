"""The compact figure contract is explicit; rendered contents are tested separately."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_campaign_workflow import WORKFLOW


class CompactFigureContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.analysis, self.figures = self.root / 'analysis', self.root / 'figures'
        self.analysis.mkdir()
        self.figures.mkdir()
        self.manifest = self.root / 'campaign.json'
        self.manifest.write_text('{}')
        metrics = ('isr_percent', 'mean_success_rtt_ms', 'network_mbit',
                   'control_mbit', 'extra_data_app_attempts')
        scenes = ('circle', 'grid', 'spidermap')
        ids = ['F{:02d}-{}-{}'.format(1+i*5+j, axis, metric)
               for i, axis in enumerate(('interest', 'speed', 'vehicles'))
               for j, metric in enumerate(metrics)]
        ids += ['F{:02d}-{}-rtt-3d'.format(21+i, scene) for i, scene in enumerate(scenes)]
        ids += ['F{:02d}-{}-rtt-box'.format(24+i, scene) for i, scene in enumerate(scenes)]
        ids += ['F27-baseline-total-traffic']
        ids += ['F{:02d}-{}-confusion'.format(28+i, scene) for i, scene in enumerate(scenes)]
        self.plan = dict(campaign_id='fixture', validation_only=True,
                         design_profile='compact-exploratory-v1', figure_ids=ids,
                         scans={name: ['base'] for name in ('interest', 'speed', 'vehicles')})
        common = dict(schema_version=1, status='complete', campaign_id='fixture', validation_only=True)
        WORKFLOW.write_json(self.analysis / 'aggregate.json', dict(
            common, campaign_sha256=WORKFLOW.digest(self.manifest)))
        items = []
        for identity in ids:
            files = {}
            for ext in ('pdf', 'svg', 'png'):
                filename = identity + '.' + ext
                (self.figures / filename).write_bytes(b'contract-test-placeholder')
                files[ext] = filename
            items.append(dict(id=identity, files=files,
                              sha256={ext: WORKFLOW.digest(self.figures / name)
                                      for ext, name in files.items()}))
        self.index = dict(common, figures=items, diagnostics=[],
                          analysis_sha256=WORKFLOW.digest(self.analysis / 'aggregate.json'))

    def verify(self):
        WORKFLOW.write_json(self.figures / 'figure-index.json', self.index)
        WORKFLOW._figure_product(self.analysis, self.figures, self.manifest, self.plan)

    def test_declared_25_figures_are_accepted_without_fixed_k_scan(self):
        self.verify()

    def test_same_count_with_missing_required_id_is_rejected(self):
        self.index['figures'][0]['id'] = 'F16-invented-substitute'
        with self.assertRaises(ValueError):
            self.verify()

    def test_invented_declaration_cannot_hide_a_missing_required_figure(self):
        self.plan['figure_ids'] = copy.deepcopy(self.plan['figure_ids'])
        self.plan['figure_ids'][0] = 'F16-invented-substitute'
        self.index['figures'][0]['id'] = 'F16-invented-substitute'
        with self.assertRaises(ValueError):
            self.verify()

    def test_changed_artifact_is_rejected(self):
        (self.figures / self.index['figures'][0]['files']['svg']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.verify()


if __name__ == '__main__':
    unittest.main()
