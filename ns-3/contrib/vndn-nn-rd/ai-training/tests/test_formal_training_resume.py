"""Epoch replay uses tiny synthetic CPU data, shuffle, dropout and all RNGs."""
import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

AI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import formal_data as data
import formal_training as training
from formal_test_support import fixture_spec


class DropoutModel(torch.nn.Module):
    def __init__(self, inputs, hidden, classes, grid, spline, dropout):
        super().__init__()
        self.layers = torch.nn.Sequential(torch.nn.Flatten(), torch.nn.Linear(inputs * 10, hidden),
                                          torch.nn.ReLU(), torch.nn.Dropout(dropout),
                                          torch.nn.Linear(hidden, classes))

    def forward(self, values):
        values = self.layers(values)
        if self.training:
            values = values * (1 + .01 * (random.random() + np.random.random()))
        return values


class ResumeTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data.build_dataset(fixture_spec(self.root), self.root / "dataset")
        self.argv = ["--dataset-manifest", str(self.root / "dataset/dataset-manifest.json"),
                     "--output-root", str(self.root / "models"), "--epochs", "4",
                     "--hidden-size", "4", "--batch-size", "1", "--dropout", ".4",
                     "--patience", "0", "--initialization-seeds", "11",
                     "--allow-validation-only", "--threads", "1"]

    def run_session(self, name, extra=None):
        # Inject the future optional setting for the first behavioral red test;
        # the old trainer ignores it and incorrectly retrains a complete run.
        args = training.formal_arguments(self.argv + (extra or []))
        args.session_dir = self.root / name
        with patch.object(training, "formal_arguments", return_value=args):
            return training.train(self.argv, "circle", DropoutModel)

    def state(self, name):
        pointer = json.loads((self.root / name / "resume-11.json").read_text())
        return torch.load(self.root / name / pointer["path"], map_location="cpu", weights_only=False)

    def assert_nested_equal(self, a, b):
        if torch.is_tensor(a):
            self.assertTrue(torch.equal(a, b))
        elif isinstance(a, np.ndarray):
            np.testing.assert_array_equal(a, b)
        elif isinstance(a, dict):
            self.assertEqual(set(a), set(b))
            for key in a:
                self.assert_nested_equal(a[key], b[key])
        elif isinstance(a, (list, tuple)):
            self.assertEqual(len(a), len(b))
            for x, y in zip(a, b):
                self.assert_nested_equal(x, y)
        else:
            self.assertEqual(a, b)

    def test_completed_session_does_not_construct_or_train_a_candidate_again(self):
        first = self.run_session("completed")
        with patch.object(DropoutModel, "__init__", side_effect=AssertionError("candidate retrained")):
            second = self.run_session("completed")
        self.assertEqual(first, second)

    def test_interrupted_cpu_shuffle_dropout_trajectory_matches_continuous(self):
        continuous = self.run_session("continuous")
        save = training._save_epoch
        def interrupt(output, seed, state):
            value = save(output, seed, state)
            if state["epoch"] == 2:
                raise KeyboardInterrupt("test: complete epoch committed")
            return value
        with patch.object(training, "_save_epoch", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_session("resumed")
        self.assertEqual(self.state("resumed")["epoch"], 2)
        resumed = self.run_session("resumed")
        a, b = self.state("continuous"), self.state("resumed")
        for key in ("current_state", "best_checkpoint", "optimizer", "rng", "history", "stalled", "stop_reason"):
            self.assert_nested_equal(a[key], b[key])
        self.assertEqual(Path(continuous["candidates"][0]["history_path"]).read_text(),
                         Path(resumed["candidates"][0]["history_path"]).read_text())
        a_current = a["current_state"]
        a_best = a["best_checkpoint"]["state_dict"]
        for key in a_current:
            self.assertNotEqual(a_current[key].data_ptr(), a_best[key].data_ptr())

    def test_changed_configuration_is_rejected_without_overwrite(self):
        self.run_session("config")
        before = (self.root / "config/training-session.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "identity|configuration"):
            self.run_session("config", ["--learning-rate", ".002"])
        self.assertEqual((self.root / "config/training-session.json").read_bytes(), before)

    def test_corrupt_committed_epoch_is_rejected(self):
        self.run_session("corrupt")
        pointer = json.loads((self.root / "corrupt/resume-11.json").read_text())
        state_path = self.root / "corrupt" / pointer["path"]
        state_path.write_bytes(state_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.run_session("corrupt")

    def test_session_option_is_accepted_by_cli_parser(self):
        args = training.formal_arguments(self.argv + ["--session-dir", str(self.root / "cli")])
        self.assertEqual(args.session_dir, self.root / "cli")


if __name__ == "__main__":
    unittest.main()
