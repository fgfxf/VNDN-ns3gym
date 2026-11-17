"""Power configuration must reach the simulator and be verified on real PHYs."""
import json
import shlex
import unittest

import test_run_experiment as fixtures

runner = fixtures.runner


class SpiderPowerTests(unittest.TestCase):
    setUp = fixtures.RunExperimentTest.setUp
    invoke = fixtures.RunExperimentTest.invoke
    manifests = fixtures.RunExperimentTest.manifests

    def configure(self, value=19.5, scene='spidermap'):
        config = json.loads(self.config.read_text())
        config.update(scenario=scene, wifi_tx_power_dbm=value)
        self.config.write_text(json.dumps(config))

    def radio_fixture(self, value=19.5, count=8):
        # Fixture has one OBU and Spider's seven RSUs. The logged power is
        # independent of the request so a mismatched observation is detectable.
        extra = """
radio = {'schema_version':1, 'scenario':'spidermap', 'requested_tx_power_dbm':VALUE,
 'rsu_count':7, 'obu_count':1, 'devices':[
 {'node_id':i, 'role':'rsu' if i<7 else 'obu', 'tx_power_start_dbm':VALUE,
  'tx_power_end_dbm':VALUE, 'tx_power_levels':1, 'rx_sensitivity_dbm':-69.8}
 for i in range(COUNT)]}
(run/'raw/radio-config.json').write_text(json.dumps(radio))
""".replace('VALUE', repr(value)).replace('COUNT', str(count))
        path = self.root/'waf'
        path.write_text(path.read_text().replace("print('fake simulation finished'", extra+"\nprint('fake simulation finished'"))

    def test_invalid_power_rejected_before_any_process(self):
        for value in (True, '19', None, -1, 31, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.configure(value)
                self.assertNotEqual(self.invoke('--strategy', '0'), 0)
                self.assertFalse((self.root/'calls.jsonl').exists())

    def test_power_override_is_spider_only(self):
        for scene in ('circle', 'grid'):
            with self.subTest(scene=scene):
                self.configure(scene=scene)
                self.assertNotEqual(self.invoke('--strategy', '0'), 0)
                self.assertFalse((self.root/'calls.jsonl').exists())

    def test_valid_power_forwarded_and_observed_devices_sealed(self):
        self.configure()
        self.radio_fixture()
        self.assertEqual(self.invoke('--strategy', '0'), 0)
        manifest = json.loads(self.manifests()[0].read_text())
        command = manifest['processes']['simulation']['command']
        self.assertIn('--wifi-tx-power-dbm=19.5', shlex.split(command[command.index('--run')+1]))
        self.assertIn('raw/radio-config.json', manifest['artifact_hashes'])

    def test_missing_device_observation_cannot_complete(self):
        self.configure()
        self.assertNotEqual(self.invoke('--strategy', '0'), 0)
        self.assertIn('radio-config', json.loads(self.manifests()[0].read_text())['error'])

    def test_mismatched_power_cannot_complete(self):
        self.configure()
        self.radio_fixture(value=13)
        self.assertNotEqual(self.invoke('--strategy', '0'), 0)
        self.assertIn('power', json.loads(self.manifests()[0].read_text())['error'])

    def test_partial_device_observation_cannot_complete(self):
        self.configure()
        self.radio_fixture(count=7)
        self.assertNotEqual(self.invoke('--strategy', '0'), 0)
        self.assertIn('device', json.loads(self.manifests()[0].read_text())['error'])


if __name__ == '__main__':
    unittest.main()
