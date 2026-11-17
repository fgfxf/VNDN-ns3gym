"""Check the built map entries without launching SUMO or waf."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


class SpiderPowerCliTests(unittest.TestCase):
    def run_binary(self, scene, *args):
        binary = ROOT/'build/scratch'/('vndn-'+scene+'-simulator')/('vndn-'+scene+'-simulator')
        self.assertTrue(binary.is_file(), 'Build the scene entry before this acceptance check')
        return subprocess.run([str(binary)]+list(args), cwd=str(ROOT),
            env=dict(os.environ, JOBS='4', LD_LIBRARY_PATH=str(ROOT/'build/lib')),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)

    def test_spider_help_exposes_power_control(self):
        result = self.run_binary('spidermap', '--PrintHelp')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--wifi-tx-power-dbm', result.stdout)

    def test_invalid_power_rejected_before_sumo(self):
        for value in ('-1', '31', 'nan', 'inf', '19oops'):
            with self.subTest(value=value):
                result = self.run_binary('spidermap', '--wifi-tx-power-dbm='+value)
                self.assertEqual(result.returncode, 2)
                self.assertIn('finite number in [0, 30]', result.stdout)
                self.assertNotIn('Starting SUMO', result.stdout)

    def test_grid_rejects_spider_override(self):
        result = self.run_binary('grid', '--wifi-tx-power-dbm=19')
        self.assertEqual(result.returncode, 2)
        self.assertIn('spidermap only', result.stdout)


if __name__ == '__main__':
    unittest.main()
