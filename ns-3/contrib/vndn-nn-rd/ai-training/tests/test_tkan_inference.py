"""Pure-Python checkpoint and C++ candidate-interface regression tests."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import torch


SCRATCH = Path(__file__).resolve().parents[4] / "scratch"
FEATURE_NAMES = ["x", "y", "speed", "acceleration", "angle", "lane_index"]


def load_controller(scenario):
    path = SCRATCH / ("vndn-{}-simulator".format(scenario)) / (
        "vndn-{}-tkan-gym.py".format(scenario)
    )
    spec = importlib.util.spec_from_file_location("inference_" + scenario, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CIRCLE = load_controller("circle")


class InferenceContractTest(unittest.TestCase):
    def test_present_but_incomplete_formal_contract_is_rejected(self):
        checkpoint = self.checkpoint()
        checkpoint["formal_contract"] = {}
        with self.assertRaisesRegex(ValueError, "formal|contract"):
            self.saved_load(CIRCLE, checkpoint)

    def test_strict_formal_mode_rejects_legacy_before_gym(self):
        torch.save(self.checkpoint(), self.model_path)
        with self.assertRaisesRegex(ValueError, "formal"):
            CIRCLE.load_model(self.model_path, self.device, require_formal=True)

    def test_decision_log_captures_current_info_before_step(self):
        torch.save(self.checkpoint(), self.model_path)
        log = self.model_path.with_name("decisions.jsonl")
        observation = {"features": np.zeros((10, 6)), "rsu_ids": np.array([0, 1]),
                       "obu_id": np.array([2])}
        info = "sourceRsu=0,obu=2,name=/com/baidu/test,time_ns=100"

        class FakeEnvironment:
            def reset(self):
                return observation

            def get_state(self):
                return observation, 0, False, info

            def step(self, action):
                return observation, 0, True, "next observation info"

            def close(self):
                pass

        gym = SimpleNamespace(ns3env=SimpleNamespace(Ns3Env=lambda **kwargs: FakeEnvironment()))
        with patch.dict(sys.modules, {"ns3gym": gym}):
            CIRCLE.main(["--model-file", str(self.model_path), "--device", "cpu",
                         "--decision-log", str(log)])
        record = json.loads(log.read_text())
        self.assertEqual(record["extra_info"], info)
        self.assertEqual(record["model_sha256"], CIRCLE.sha256_file(self.model_path))
        self.assertEqual(record["candidate_rsu_ids"], [0, 1])

    def test_nonfinite_online_observation_is_rejected(self):
        checkpoint = self.checkpoint()
        model, metadata, _ = self.saved_load(CIRCLE, checkpoint)
        values = np.zeros((10, 6))
        values[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            CIRCLE.probabilities_for_candidates(
                {"features": values, "rsu_ids": [0, 1]}, model, metadata, self.device)

    def test_nonfinite_weights_are_rejected_before_model_is_used(self):
        checkpoint = self.checkpoint()
        next(iter(checkpoint["state_dict"].values())).view(-1)[0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            self.saved_load(CIRCLE, checkpoint)

    def test_single_candidate_expected_selection_is_well_defined(self):
        from formal_training import selected_targets
        first, second, extra = selected_targets(np.ones((2, 1), dtype=np.float32))
        np.testing.assert_array_equal(first, [0, 0])
        np.testing.assert_array_equal(second, [0, 0])
        np.testing.assert_array_equal(extra, [False, False])

    def setUp(self):
        torch.manual_seed(19)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.model_path = Path(self.directory.name) / "model.pt"
        self.device = torch.device("cpu")

    def checkpoint(self, scenario="circle", output_size=None, **parameters):
        if output_size is None:
            output_size = 2 if scenario == "circle" else 7
        settings = dict(
            input_size=6, hidden_size=4, output_size=output_size,
            sequence_length=10, grid_size=3, spline_order=2, dropout=0.0,
        )
        settings.update(parameters)
        model = CIRCLE.CircleTKANLSTM(**{
            key: value for key, value in settings.items() if key != "sequence_length"
        })
        return dict(
            scenario=scenario, model_parameters=settings,
            state_dict=model.state_dict(), feature_names=list(FEATURE_NAMES),
            label_values=list(range(output_size)), normalization_mean=[0.0] * 6,
            normalization_std=[1.0] * 6,
        )

    def saved_load(self, controller, checkpoint):
        torch.save(checkpoint, self.model_path)
        return controller.load_model(self.model_path, self.device)

    def test_legacy_circle_loader_keeps_two_argument_api(self):
        checkpoint = self.checkpoint()
        del checkpoint["scenario"]
        model, metadata, path = self.saved_load(CIRCLE, checkpoint)
        self.assertEqual(path, self.model_path.resolve())
        self.assertFalse(model.training)
        self.assertEqual(metadata["label_values"], [0, 1])
        self.assertEqual(tuple(model(torch.zeros(1, 10, 6)).shape), (1, 2))

    def test_rejects_invalid_normalization(self):
        for field, value in [
            ("normalization_mean", [0.0] * 5),
            ("normalization_mean", [[0.0] * 6]),
            ("normalization_mean", [float("nan")] * 6),
            ("normalization_std", [float("inf")] * 6),
            ("normalization_std", [0.0] * 6),
            ("normalization_std", [-1.0] * 6),
        ]:
            with self.subTest(field=field, value=value):
                checkpoint = self.checkpoint()
                checkpoint[field] = value
                with self.assertRaisesRegex(ValueError, "normalization"):
                    self.saved_load(CIRCLE, checkpoint)

    def test_rejects_feature_order_and_sequence_mismatch(self):
        checkpoint = self.checkpoint()
        checkpoint["feature_names"][0:2] = ["y", "x"]
        with self.assertRaisesRegex(ValueError, "feature_names"):
            self.saved_load(CIRCLE, checkpoint)
        for value in (9, 10.5):
            with self.subTest(sequence_length=value):
                checkpoint = self.checkpoint(sequence_length=value)
                with self.assertRaisesRegex(ValueError, "sequence_length"):
                    self.saved_load(CIRCLE, checkpoint)

    def test_rejects_incompatible_input_and_output_dimensions(self):
        for settings, expected in [
            ({"input_size": 5}, "input_size"),
            ({"output_size": 3}, "output_size"),
        ]:
            with self.subTest(settings=settings):
                with self.assertRaisesRegex(ValueError, expected):
                    self.saved_load(CIRCLE, self.checkpoint(**settings))

    def test_rejects_wrong_or_missing_seven_class_scenario(self):
        for scenario, wrong in (("grid", "spidermap"), ("spidermap", "grid")):
            controller = load_controller(scenario)
            for other in (wrong, "circle", None):
                with self.subTest(scenario=scenario, checkpoint_scenario=other):
                    checkpoint = self.checkpoint(scenario)
                    if other is None:
                        del checkpoint["scenario"]
                    else:
                        checkpoint["scenario"] = other
                    with self.assertRaisesRegex(ValueError, "scenario"):
                        self.saved_load(controller, checkpoint)

    def test_rejects_missing_duplicate_fractional_or_out_of_range_labels(self):
        for scenario in ("grid", "spidermap"):
            controller = load_controller(scenario)
            for labels in (
                list(range(6)), [0, 1, 2, 3, 4, 5, 5], [0, 1, 2, 3, 4, 5, 7],
                [0, 1, 2, 3, 4, 5, 6.2], [False, 1, 2, 3, 4, 5, 6],
            ):
                with self.subTest(scenario=scenario, labels=labels):
                    checkpoint = self.checkpoint(scenario)
                    checkpoint["label_values"] = labels
                    with self.assertRaisesRegex(ValueError, "label_values"):
                        self.saved_load(controller, checkpoint)

    def test_seven_class_checkpoint_reloads_weights_and_infers(self):
        for scenario in ("grid", "spidermap"):
            with self.subTest(scenario=scenario):
                controller = load_controller(scenario)
                checkpoint = self.checkpoint(scenario)
                model, metadata, _ = self.saved_load(controller, checkpoint)
                for key, value in checkpoint["state_dict"].items():
                    torch.testing.assert_close(model.state_dict()[key], value)
                probabilities = controller.probabilities_for_candidates(
                    {"features": np.zeros(60), "rsu_ids": list(range(7))},
                    model, metadata, self.device,
                )
                self.assertEqual(probabilities.shape, (7,))
                self.assertTrue(np.isfinite(probabilities).all())
                self.assertTrue((probabilities >= 0).all())
                self.assertAlmostEqual(float(probabilities.sum()), 1.0, places=6)

    def test_probabilities_follow_label_mapping_and_candidate_order(self):
        checkpoint = self.checkpoint("grid")
        checkpoint["label_values"] = [6, 4, 2, 0, 1, 3, 5]
        controller = load_controller("grid")
        _, metadata, _ = self.saved_load(controller, checkpoint)

        class FixedLogits(torch.nn.Module):
            def forward(self, inputs):
                return torch.arange(7, dtype=torch.float32).unsqueeze(0)

        model = FixedLogits()
        candidates = [2, 5, 0, 6, 1, 4, 3]
        actual = controller.probabilities_for_candidates(
            {"features": np.zeros(60), "rsu_ids": candidates},
            model, metadata, self.device,
        )
        original = torch.softmax(torch.arange(7, dtype=torch.float32), 0).numpy()
        expected = original[[metadata["label_values"].index(label) for label in candidates]]
        np.testing.assert_allclose(actual, expected, rtol=1e-6)
        subset = controller.probabilities_for_candidates(
            {"features": np.zeros(60), "rsu_ids": [5, 0]},
            model, metadata, self.device,
        )
        np.testing.assert_allclose(subset, expected[[1, 2]] / expected[[1, 2]].sum())

    def test_importing_controllers_does_not_import_gym(self):
        for scenario in ("circle", "grid", "spidermap"):
            load_controller(scenario)
        self.assertNotIn("ns3gym.ns3env", sys.modules)

    def test_wrong_scenario_is_rejected_before_gym_connection(self):
        for scenario in ("grid", "spidermap"):
            with self.subTest(scenario=scenario):
                checkpoint = self.checkpoint("circle")
                torch.save(checkpoint, self.model_path)
                controller = load_controller(scenario)
                original_import = __import__

                def no_gym(name, *args, **kwargs):
                    self.assertFalse(name.startswith("ns3gym"), "Gym imported before validation")
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=no_gym):
                    with self.assertRaisesRegex(ValueError, "scenario"):
                        controller.main(["--model-file", str(self.model_path), "--device", "cpu"])


if __name__ == "__main__":
    unittest.main()
