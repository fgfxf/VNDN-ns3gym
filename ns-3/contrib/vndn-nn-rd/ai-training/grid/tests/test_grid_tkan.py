"""Dataset boundaries and a real CPU train/save/inference round trip."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import numpy as np
import torch


SCENARIO = "grid"
MODEL_CLASS = "GridTKANLSTM"
SCENARIO_DATA_DIRECTORY = "grid-vanet-test"
OTHER_SCENARIO_DATA_DIRECTORY = "fgfxf-spider-map"
AI_ROOT = Path(__file__).resolve().parents[2]
NS3_ROOT = Path(__file__).resolve().parents[5]
TRAINER_PATH = AI_ROOT / SCENARIO / "train_tkan_lstm.py"


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


trainer = import_file(SCENARIO + "_trainer_tests", TRAINER_PATH)


def rows(count, offset=0):
    return np.asarray(
        [[offset + step, step, 1, 0, 90, 0, step % 7] for step in range(count)],
        dtype=np.float64,
    )


def write_trace(root, run_name, values, obu=2, strategy="NoForward", complete=True):
    run = root / run_name
    training = run / "ai-training"
    training.mkdir(parents=True, exist_ok=True)
    (run / "simulation-config.txt").write_text(
        "RsuForwardStrategy={}\n".format(strategy), encoding="utf-8"
    )
    csv_path = training / "training-tag-{}.csv".format(obu)
    np.savetxt(str(csv_path), values, delimiter=",")
    if complete:
        csv_path.with_name(csv_path.stem + "-stats.txt").write_text(
            "received={}\ntimeout=0\n".format(len(values)), encoding="utf-8"
        )
    return csv_path


class DatasetTest(unittest.TestCase):
    def test_invalid_label_is_removed_without_joining_segments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = rows(7)
            values[3, -1] = -1
            csv_path = write_trace(root, "run-a", values)
            sequence = trainer.load_sequence_file(csv_path.parents[1], csv_path)
            self.assertEqual(len(sequence.values), 6)
            inputs, targets = trainer.make_windows(
                [sequence], 3, 1, np.zeros(6), np.ones(6), list(range(7))
            )
            self.assertEqual(inputs[:, :, 0].tolist(), [[0, 1, 2], [4, 5, 6]])
            self.assertEqual(targets.tolist(), [2, 6])

    def test_filters_strategy_rtt_empty_and_unfinished_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            accepted = write_trace(root, "run-a", rows(12))
            write_trace(root, "run-b", rows(12), strategy="VTDF")
            write_trace(root, "run-c", rows(12), complete=False)
            empty = write_trace(root, "run-a", rows(0), obu=3)
            self.assertEqual(empty.stat().st_size, 0)
            accepted.with_name("training-tag-2-rtt.csv").write_text("not,a,trace")
            report = {}
            sequences = trainer.discover_sequences(root, report=report)
            self.assertEqual([item.csv_path for item in sequences], [accepted])
            self.assertEqual(report["ignored_strategy_runs"], 1)
            self.assertEqual(report["ignored_rtt_files"], 1)
            self.assertEqual(report["ignored_empty_files"], 1)
            self.assertEqual(report["ignored_unfinished_files"], 1)

    def test_invalid_rows_are_counted_and_every_break_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = rows(15)
            values[3, 0] = np.nan
            values[7, -1] = np.inf
            values[11, -1] = 1.5
            values[12, -1] = 7
            csv_path = write_trace(root, "run-a", values)
            sequence = trainer.load_sequence_file(csv_path.parents[1], csv_path)
            inputs, _ = trainer.make_windows(
                [sequence], 3, 1, np.zeros(6), np.ones(6), list(range(7))
            )
            self.assertEqual(inputs[:, :, 0].tolist(), [[0, 1, 2], [4, 5, 6], [8, 9, 10]])
            summary = trainer.summarize_sequences([sequence], 3, 1)
            self.assertEqual(summary["row_count"], 15)
            self.assertEqual(summary["valid_row_count"], 11)
            self.assertEqual(summary["discarded_row_count"], 4)
            self.assertEqual(summary["discarded_by_reason"], {
                "nonfinite_feature": 1, "nonfinite_label": 1,
                "noninteger_label": 1, "out_of_range_label": 1,
            })
            self.assertEqual(summary["segment_count"], 4)
            self.assertEqual(summary["short_segment_count"], 1)
            self.assertEqual(summary["window_count"], 3)

    def test_raw_precision_does_not_round_invalid_labels_into_integers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = rows(12)
            values[5, -1] = 1.00000001
            csv_path = write_trace(root, "run-a", values)
            sequence = trainer.load_sequence_file(csv_path.parents[1], csv_path)
            self.assertEqual(len(sequence.values), 11)
            self.assertEqual(sequence.discarded_by_reason["noninteger_label"], 1)

    def test_unparseable_or_wrong_width_files_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = write_trace(root, "run-a", rows(12))
            for text in ("bad,0,0,0,0,0,1\n", "1,2,3,4,5,6\n", "1,2,3,4,5,6,0\n1,2\n"):
                with self.subTest(text=text):
                    csv_path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "training-tag-2.csv"):
                        trainer.load_sequence_file(csv_path.parents[1], csv_path)

    def test_empty_windows_fail_after_invalid_rows_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = rows(12)
            values[:, -1] = -1
            csv_path = write_trace(root, "run-a", values)
            sequence = trainer.load_sequence_file(csv_path.parents[1], csv_path)
            summary = trainer.summarize_sequences([sequence], 10, 2)
            self.assertEqual(summary["discarded_row_count"], 12)
            with self.assertRaisesRegex(ValueError, "no sequence window"):
                trainer.make_windows([sequence], 10, 2, np.zeros(6), np.ones(6), list(range(7)))

    def test_runs_vehicles_and_normalization_remain_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_trace(root, "run-a", rows(12, 0), obu=2)
            write_trace(root, "run-a", rows(12, 100), obu=3)
            write_trace(root, "run-b", rows(12, 10000), obu=2)
            sequences = trainer.discover_sequences(root)
            train, validation = trainer.split_by_run(sequences, 0.2)
            self.assertEqual({item.run_directory.name for item in train}, {"run-a"})
            self.assertEqual({item.run_directory.name for item in validation}, {"run-b"})
            mean, standard_deviation = trainer.normalization_statistics(train)
            self.assertAlmostEqual(float(mean[0]), 55.5)
            self.assertTrue(np.isfinite(standard_deviation).all())
            self.assertTrue((standard_deviation > 0).all())
            inputs, _ = trainer.make_windows(train, 10, 1, mean, standard_deviation, list(range(7)))
            restored = inputs[:, :, 0] * standard_deviation[0] + mean[0]
            self.assertEqual(len(inputs), 6)
            np.testing.assert_allclose(np.diff(restored, axis=1), 1, atol=1e-4)

    def test_split_requires_two_runs_and_nonempty_training_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_trace(root, "run-a", rows(20))
            with self.assertRaisesRegex(ValueError, "two completed runs"):
                trainer.split_by_run(trainer.discover_sequences(root), 0.2)
            write_trace(root, "run-b", rows(20))
            with self.assertRaisesRegex(ValueError, "validation-ratio"):
                trainer.split_by_run(trainer.discover_sequences(root), 0.99)

    def test_class_coverage_uses_window_targets_not_raw_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = rows(20)
            values[7:, -1] = 0
            csv_path = write_trace(root, "run-a", values)
            sequence = trainer.load_sequence_file(csv_path.parents[1], csv_path)
            self.assertEqual(trainer.label_values([sequence]), list(range(7)))
            _, targets = trainer.make_windows(
                [sequence], 10, 1, np.zeros(6), np.ones(6), list(range(7))
            )
            with self.assertRaisesRegex(ValueError, "missing.*1.*2.*3.*4.*5.*6"):
                trainer.class_weights_for_targets(targets, list(range(7)))

    def test_class_weights_are_finite_for_seven_classes(self):
        weights = trainer.class_weights_for_targets(np.arange(7), list(range(7)))
        np.testing.assert_allclose(weights, np.ones(7))


class TrainingTest(unittest.TestCase):
    def test_weighted_validation_loss_is_independent_of_batch_partition(self):
        logits = torch.tensor([[5.0, 0, 0, 0, 0, 0, 0]] * 4)
        targets = torch.tensor([0, 0, 0, 1])
        criterion = torch.nn.CrossEntropyLoss(weight=torch.tensor([1.0, 5, 1, 1, 1, 1, 1]))
        expected = float(criterion(logits, targets))
        for batch_size in (1, 2, 4):
            with self.subTest(batch_size=batch_size):
                loader = torch.utils.data.DataLoader(
                    torch.utils.data.TensorDataset(logits, targets), batch_size=batch_size)
                loss, accuracy = trainer.evaluate(torch.nn.Identity(), loader, criterion, torch.device("cpu"))
                self.assertAlmostEqual(loss, expected, places=6)
                self.assertAlmostEqual(accuracy, 0.75)

    def test_model_shape_and_finite_backward(self):
        model = getattr(trainer, MODEL_CLASS)(6, 8, 7, grid_size=3, spline_order=2)
        inputs = torch.randn(4, 10, 6)
        outputs = model(inputs)
        self.assertEqual(tuple(outputs.shape), (4, 7))
        loss = torch.nn.functional.cross_entropy(outputs, torch.tensor([0, 2, 4, 6]))
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertTrue(torch.isfinite(model.cell.gates.base_weight.grad).all())

    def test_checkpoint_preserves_scene_and_complete_inference_metadata(self):
        model = getattr(trainer, MODEL_CLASS)(6, 8, 7)
        arguments = Namespace(forward_strategy="NoForward", hidden_size=8,
                              grid_size=5, spline_order=3, dropout=0.1, sequence_length=10)
        checkpoint = trainer.checkpoint_payload(
            model, arguments, list(range(7)), np.zeros(6), np.ones(6), 1, 0.5
        )
        self.assertEqual(checkpoint["scenario"], SCENARIO)
        self.assertEqual(checkpoint["label_values"], list(range(7)))
        self.assertEqual(checkpoint["model_parameters"]["output_size"], 7)
        self.assertEqual(checkpoint["model_parameters"]["sequence_length"], 10)

    def test_cli_requires_explicit_data_root_and_gym_sequence_length(self):
        process = subprocess.run([sys.executable, str(TRAINER_PATH)], capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("--data-root", process.stderr)
        process = subprocess.run([sys.executable, str(TRAINER_PATH), "--data-root", "/unused",
                                  "--sequence-length", "9"], capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("sequence-length", process.stderr)

    def test_cli_rejects_other_canonical_scenario_before_data_loading(self):
        process = subprocess.run([sys.executable, str(TRAINER_PATH), "--data-root",
                                  str(NS3_ROOT / "data" / OTHER_SCENARIO_DATA_DIRECTORY / "20261018")],
                                 capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("scenario", process.stderr)

    def test_one_epoch_cpu_train_save_and_actual_controller_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "data" / "20261018"
            for index in range(2):
                values = rows(45, index * 100)
                values[20, -1] = -1
                write_trace(data_root, "run-{}".format(index), values)
            output_root = root / "models"
            process = subprocess.run([
                sys.executable, str(TRAINER_PATH), "--data-root", str(data_root),
                "--output-root", str(output_root), "--epochs", "1", "--batch-size", "8",
                "--hidden-size", "4", "--grid-size", "3", "--spline-order", "2",
                "--stride", "1", "--device", "cpu", "--seed", "20261018",
            ], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            checkpoints = list(output_root.glob("*/*.pt"))
            self.assertEqual(len(checkpoints), 1)
            checkpoint_path = checkpoints[0]
            summary = json.loads(checkpoint_path.with_name("training-summary.json").read_text())
            self.assertEqual(summary["scenario"], SCENARIO)
            self.assertEqual(summary["filtering"]["discarded_row_count"], 2)
            self.assertEqual(summary["train_class_counts"], {str(i): 5 if i == 2 else (4 if i in (3, 4, 5) else 3) for i in range(7)})
            self.assertEqual(summary["train_window_count"], 26)
            self.assertEqual(summary["validation_window_count"], 26)
            self.assertEqual(summary["train_runs"], [str(data_root / "run-0")])
            self.assertEqual(summary["validation_runs"], [str(data_root / "run-1")])
            self.assertEqual(summary["arguments"]["seed"], 20261018)
            self.assertEqual(len(checkpoint_path.with_name("training-history.csv").read_text().splitlines()), 2)
            controller_path = NS3_ROOT / "scratch" / ("vndn-" + SCENARIO + "-simulator") / ("vndn-" + SCENARIO + "-tkan-gym.py")
            controller = import_file(SCENARIO + "_inference_round_trip", controller_path)
            model, checkpoint, _ = controller.load_model(checkpoint_path, torch.device("cpu"))
            candidates = [6, 2, 0, 5, 1, 4, 3]
            observation = {"features": rows(10)[:, :-1].reshape(-1), "rsu_ids": candidates}
            probabilities = controller.probabilities_for_candidates(observation, model, checkpoint, torch.device("cpu"))
            self.assertEqual(probabilities.shape, (7,))
            self.assertTrue(np.isfinite(probabilities).all())
            self.assertTrue((probabilities >= 0).all())
            self.assertAlmostEqual(float(probabilities.sum()), 1.0, places=6)
            normalized = (rows(10)[:, :-1] - np.asarray(checkpoint["normalization_mean"])) / np.asarray(checkpoint["normalization_std"])
            with torch.no_grad():
                expected = torch.softmax(model(torch.from_numpy(normalized.astype(np.float32)).unsqueeze(0)), dim=1)[0].numpy()
            np.testing.assert_allclose(probabilities, expected[candidates], rtol=1e-5, atol=1e-7)


if __name__ == "__main__":
    unittest.main()
