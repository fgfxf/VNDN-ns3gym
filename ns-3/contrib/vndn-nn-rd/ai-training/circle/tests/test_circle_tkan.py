"""Lightweight tests for ordered circle data and TKAN-LSTM shapes."""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


MODULE_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIRECTORY))

from train_tkan_lstm import (  # noqa: E402
    CircleTKANLSTM,
    discover_sequences,
    make_windows,
    normalization_statistics,
    split_by_run,
)


class CircleDatasetTest(unittest.TestCase):
    def test_windows_keep_order_and_do_not_cross_runs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for run_index in range(2):
                run = root / "20260812-{:02d}".format(run_index)
                training = run / "ai-training"
                training.mkdir(parents=True)
                (run / "simulation-config.txt").write_text(
                    "RsuForwardStrategy=NoForward\n", encoding="utf-8"
                )
                rows = np.asarray(
                    [
                        [run_index * 100 + step, step, 1, 0, 90, 0, step % 2]
                        for step in range(5)
                    ],
                    dtype=np.float32,
                )
                np.savetxt(
                    str(training / "training-tag-2.csv"), rows, delimiter=","
                )
                (training / "training-tag-2-stats.txt").write_text(
                    "received=5\ntimeout=0\n", encoding="utf-8"
                )

            sequences = discover_sequences(root)
            train, validation = split_by_run(sequences, 0.5)
            self.assertEqual(len(train), 1)
            self.assertEqual(len(validation), 1)
            mean, standard_deviation = normalization_statistics(train)
            inputs, targets = make_windows(
                train, 3, 1, mean, standard_deviation, [0, 1]
            )
            self.assertEqual(inputs.shape, (3, 3, 6))
            self.assertEqual(targets.tolist(), [0, 1, 0])
            restored_x = inputs[0, :, 0] * standard_deviation[0] + mean[0]
            np.testing.assert_allclose(restored_x, [0, 1, 2], atol=1e-5)


class TKANModelTest(unittest.TestCase):
    def test_forward_shape_and_backward(self):
        model = CircleTKANLSTM(6, 8, 2, grid_size=3, spline_order=2)
        output = model(torch.randn(4, 5, 6))
        self.assertEqual(tuple(output.shape), (4, 2))
        output.sum().backward()
        self.assertIsNotNone(model.cell.gates.base_weight.grad)


if __name__ == "__main__":
    unittest.main()
