"""Existing-binary execution and the process-exit acceptance boundary."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import test_run_experiment as fixtures


runner = fixtures.runner


class NoBuildRunnerTests(unittest.TestCase):
    setUp = fixtures.RunExperimentTest.setUp
    invoke = fixtures.RunExperimentTest.invoke
    manifests = fixtures.RunExperimentTest.manifests

    def _existing_binary(self):
        binary = self.root / "build/scratch/vndn-circle-simulator/vndn-circle-simulator"
        binary.parent.mkdir(parents=True)
        shutil.copyfile(sys.executable, binary)
        binary.chmod(0o755)
        waf = self.root / "waf"
        waf.write_text(waf.read_text().replace(
            "sys.argv.index('--run')", "sys.argv.index('--run-no-build')"))
        return binary

    def test_no_build_uses_explicit_waf_mode_and_records_existing_binary(self):
        binary = self._existing_binary()
        before = runner.summary.sha256_file(binary)
        self.assertEqual(self.invoke("--strategy", "0", "--no-build"), 0)
        value = json.loads(self.manifests()[0].read_text())
        self.assertEqual(value["execution_mode"], "existing-binary")
        self.assertEqual(value["binary_before"]["sha256"], before)
        command = value["processes"]["simulation"]["command"]
        self.assertIn("--run-no-build", command)
        self.assertNotIn("--run", command)
        self.assertNotIn("configure", command)

    def test_no_build_missing_binary_fails_before_starting_simulation(self):
        self.assertNotEqual(self.invoke("--strategy", "0", "--no-build"), 0)
        self.assertFalse((self.root / "calls.jsonl").exists())
        record = json.loads(self.manifests()[0].read_text())
        self.assertEqual(record["status"], "failed")
        self.assertIn("existing executable", record["error"])

    def test_nonzero_exit_between_poll_checks_cannot_be_accepted(self):
        process = mock.Mock()
        process.poll.side_effect = [None, 7, 7]
        process.returncode = 7
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(runner.subprocess, "Popen", return_value=process), \
                    mock.patch.object(runner, "stop_group"), \
                    mock.patch.object(runner.time, "sleep"):
                records, error, _ = runner.run_processes(
                    [("simulation", ["fixture"])], root, root, 10)
        self.assertEqual(records["simulation"]["returncode"], 7)
        self.assertIsNotNone(error)
        self.assertIn("exited with 7", error)


if __name__ == "__main__":
    unittest.main()
