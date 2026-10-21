"""Formal learning semantics: split isolation, real optimization and metadata."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch

AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import formal_data as data
import formal_training as training
from formal_test_support import fixture_run, fixture_spec, reseal, sha, write_csv, write_json

torch.set_num_threads(1)


def load_scene(scene):
    name = "_formal_test_" + scene
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / scene / "train_tkan_lstm.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return getattr(module, {"circle": "CircleTKANLSTM", "grid": "GridTKANLSTM",
                            "spidermap": "SpidermapTKANLSTM"}[scene])


class FormalTrainingTest(unittest.TestCase):
    def test_normalization_reads_only_training_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = fixture_spec(root)
            data.build_dataset(spec, root / "dataset")
            result = training.normalization_statistics(root / "dataset/dataset-manifest.json")
            self.assertIsInstance(result, tuple, "train-only normalization must be implemented")
            mean, std = result
            np.testing.assert_allclose(mean, [0.5, 0, 5, 0, 90, 0])
            np.testing.assert_allclose(std, [0.5, 1, 1, 1, 1, 1])

    def test_macro_f1_and_probabilistic_metrics_use_all_classes(self):
        result = training.classification_metrics(
            np.array([[.9, .1], [.8, .2], [.3, .7], [.6, .4]], dtype=np.float32),
            np.array([0, 0, 1, 1]))
        self.assertEqual(result.get("confusion_matrix"), [[2, 0], [1, 1]])
        self.assertAlmostEqual(result["macro_f1"], (0.8 + 2 / 3) / 2)
        self.assertAlmostEqual(result["balanced_accuracy"], .75)
        self.assertAlmostEqual(result["target_set_coverage"], 1.0)
        self.assertAlmostEqual(result["mean_candidate_count"], 2.0)
        self.assertTrue(np.isfinite(result["cross_entropy"]))

    def test_model_selection_prioritizes_macro_f1_before_cross_entropy(self):
        best = dict(macro_f1=.8, cross_entropy=.2, epoch=3, seed=2)
        self.assertTrue(training.is_better(
            dict(macro_f1=.81, cross_entropy=.9, epoch=8, seed=3), best))
        self.assertTrue(training.is_better(
            dict(macro_f1=.8, cross_entropy=.1, epoch=9, seed=3), best))
        self.assertTrue(training.is_better(
            dict(macro_f1=.8, cross_entropy=.2, epoch=2, seed=3), best))
        self.assertFalse(training.is_better(
            dict(macro_f1=.79, cross_entropy=.01, epoch=1, seed=1), best))

    def test_all_three_scenes_train_save_and_reload_formal_model(self):
        for scene in ("circle", "grid", "spidermap"):
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data.build_dataset(fixture_spec(root, scene), root / "dataset")
                result = training.train([
                    "--dataset-manifest", str(root / "dataset/dataset-manifest.json"),
                    "--output-root", str(root / "models"), "--epochs", "1",
                    "--hidden-size", "4", "--grid-size", "3", "--spline-order", "2",
                    "--batch-size", "2", "--initialization-seeds", "11", "12",
                    "--threads", "1", "--device", "cpu", "--allow-validation-only",
                ], scene, load_scene(scene))
                self.assertIsInstance(result, dict, "a trained, frozen model manifest is required")
                self.assertEqual(len(result["candidates"]), 2)
                checkpoint = torch.load(result["checkpoint_path"], weights_only=False)
                self.assertEqual(checkpoint["formal_contract"]["label_contract"], data.LABEL_CONTRACT)
                self.assertTrue(checkpoint["formal_contract"]["validation_only"])
                self.assertEqual(checkpoint["label_values"], data.SCENARIO_LABELS[scene])
                self.assertEqual(checkpoint["formal_contract"]["normalization_split"], "train")
                self.assertNotIn("evaluation_metrics", result)
                self.assertTrue(np.isfinite(checkpoint["normalization_mean"]).all())
                controller_path = AI_ROOT.parents[2] / "scratch" / (
                    "vndn-{}-simulator/vndn-{}-tkan-gym.py".format(scene, scene))
                spec = importlib.util.spec_from_file_location("_formal_roundtrip_" + scene, controller_path)
                controller = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(controller)
                with self.assertRaisesRegex(ValueError, "validation_only"):
                    controller.load_model(Path(result["checkpoint_path"]), torch.device("cpu"),
                                          require_formal=True)
                model, metadata, _ = controller.load_model(
                    Path(result["checkpoint_path"]), torch.device("cpu"),
                    require_formal=True, allow_validation_only=True)
                probs = controller.probabilities_for_candidates(
                    {"features": np.zeros((10, 6)), "rsu_ids": data.SCENARIO_LABELS[scene]},
                    model, metadata, torch.device("cpu"))
                self.assertEqual(probs.shape, (len(data.SCENARIO_LABELS[scene]),))
                self.assertTrue(np.isfinite(probs).all())
                self.assertAlmostEqual(float(probs.sum()), 1.0, places=6)

    def test_operational_selection_uses_actual_available_candidates(self):
        probabilities = np.array([[.8, .1, .05, .05]], dtype=np.float32)
        first, second, extra = training.selection_for_candidates(probabilities[0], [2, 3])
        self.assertEqual((first, second, extra), (2, 3, True))
        metrics = training.MetricAccumulator(4)
        metrics.update(probabilities, np.array([0]),
                       selections=(np.array([first]), np.array([second]), np.array([extra])))
        self.assertEqual(metrics.metrics()["accuracy"], 1)
        self.assertEqual(metrics.metrics()["target_set_coverage"], 0)

    def test_frozen_evaluation_uses_only_evaluation_and_emits_plot_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data.build_dataset(fixture_spec(root), root / "dataset")
            result = training.train([
                "--dataset-manifest", str(root / "dataset/dataset-manifest.json"),
                "--output-root", str(root / "models"), "--epochs", "1",
                "--hidden-size", "4", "--batch-size", "2",
                "--initialization-seeds", "11", "--allow-validation-only",
            ], "circle", load_scene("circle"))
            manifest_path = Path(result["checkpoint_path"]).with_name("model-manifest.json")
            evaluated = training.evaluate_frozen_model(
                manifest_path, root / "evaluation-output", allow_validation_only=True,
                bootstrap_repetitions=20)
            self.assertIsInstance(evaluated, dict, "explicit frozen evaluation is required")
            self.assertEqual(evaluated["split"], "evaluation")
            self.assertEqual(evaluated["model_sha256"], result["checkpoint_sha256"])
            self.assertEqual(evaluated["class_support"], [1, 1])
            self.assertEqual([row["run_id"] for row in evaluated["per_run"]], ["evaluation"])
            self.assertEqual(evaluated["subsets"]["short_history"]["sample_count"], 2)
            self.assertTrue(Path(evaluated["training_history"]["path"]).is_file())
            self.assertTrue((root / "evaluation-output/predictions.jsonl").is_file())
            with self.assertRaisesRegex(ValueError, "validation_only"):
                training.evaluate_frozen_model(manifest_path, root / "forbidden")

    def test_training_cannot_freeze_a_model_after_dataset_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = data.build_dataset(fixture_spec(root), root / "dataset")
            features_path = root / "dataset" / manifest["shards"][0]["features"]
            base = load_scene("circle")

            class MutatingModel(base):
                changed = False

                def forward(self, inputs):
                    if not self.changed:
                        self.changed = True
                        values = np.load(features_path, mmap_mode="r+")
                        values[0, 0, 0] += 42
                        values.flush()
                    return super().forward(inputs)

            with self.assertRaisesRegex(ValueError, "hash"):
                training.train([
                    "--dataset-manifest", str(root / "dataset/dataset-manifest.json"),
                    "--output-root", str(root / "models"), "--epochs", "1", "--hidden-size", "4",
                    "--batch-size", "2", "--initialization-seeds", "11",
                    "--allow-validation-only",
                ], "circle", MutatingModel)
            self.assertEqual(list((root / "models").glob("*/model-manifest.json")), [])

    def test_empty_evaluation_seed_is_retained_without_fabricating_bootstrap_ci(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specification_path = fixture_spec(root)
            empty = fixture_run(root, "empty-evaluation", seed=4)
            write_csv(empty / "raw/data-rx.csv",
                      ["time_ns", "node_id", "face_id", "name"], [])
            reseal(empty)
            specification = json.loads(specification_path.read_text())
            specification["runs"].append(dict(
                path=str(empty), split="evaluation", seed_family=4, condition_id="baseline",
                manifest_sha256=sha(empty / "manifest.json")))
            write_json(specification_path, specification)
            data.build_dataset(specification_path, root / "dataset")
            result = training.train([
                "--dataset-manifest", str(root / "dataset/dataset-manifest.json"),
                "--output-root", str(root / "models"), "--epochs", "1", "--hidden-size", "4",
                "--batch-size", "2", "--initialization-seeds", "11",
                "--allow-validation-only",
            ], "circle", load_scene("circle"))
            evaluated = training.evaluate_frozen_model(
                Path(result["checkpoint_path"]).with_name("model-manifest.json"),
                root / "evaluation-output", allow_validation_only=True,
                bootstrap_repetitions=100, analysis_seed=1)
            self.assertEqual(evaluated["bootstrap"]["independent_seed_count"], 2)
            self.assertGreater(evaluated["bootstrap"]["undefined_replicates"], 0)
            self.assertEqual(evaluated["per_seed"][1]["sample_count"], 0)
            self.assertTrue(all(value is None for value in
                                evaluated["bootstrap"]["confidence_intervals_95"].values()))
            self.assertEqual(evaluated["unknown_label_and_exclusion_counts"]["missing_return"], 2)


if __name__ == "__main__":
    unittest.main()
