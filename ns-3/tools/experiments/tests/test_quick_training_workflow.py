"""Quick profile changes only the declared training budget and resume location."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "_quick_training_workflow", Path(__file__).resolve().parents[1] / "campaign_workflow.py")
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class QuickTrainingConfigurationTests(unittest.TestCase):
    def config(self, seeds, epochs=30):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "train.json"
        path.write_text(json.dumps(dict(initialization_seeds=seeds, epochs=epochs)))
        return path

    def test_quick_accepts_one_predeclared_seed_and_no_more_than_thirty_epochs(self):
        result = workflow._configuration(self.config([61021]), profile="quick-draft-v1")
        self.assertEqual(result["initialization_seeds"], [61021])
        with self.assertRaisesRegex(ValueError, "30|thirty"):
            workflow._configuration(self.config([61021], 31), profile="quick-draft-v1")

    def test_legacy_still_requires_three_and_quick_requires_exactly_one(self):
        with self.assertRaises(ValueError):
            workflow._configuration(self.config([61021]))
        self.assertEqual(len(workflow._configuration(self.config([1, 2, 3]))["initialization_seeds"]), 3)
        with self.assertRaises(ValueError):
            workflow._configuration(self.config([1, 2, 3]), profile="quick-draft-v1")

    def test_actual_quick_plan_retries_failed_attempt_with_the_same_training_session(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "plan").mkdir()
        plan = workflow.campaign.make_plan("quick-fixture", profile="quick-draft-v1")
        plan.update(status="development-frozen", source_sha256="a" * 64,
                    minimum_free_disk_bytes=0)
        (root / "plan/design.json").write_text(json.dumps(plan))
        config = self.config([62021], 1)
        dataset = root / "dataset-manifest.json"
        dataset.write_text('{}')
        sessions = []

        def worker(command, log, timeout):
            self.assertIn("--session-dir", command)
            output = Path(command[command.index("--session-dir") + 1])
            sessions.append(output)
            Path(log).write_text("synthetic training process, no scientific results\n")
            if len(sessions) == 1:
                output.mkdir(parents=True)
                (output / "preserved-epoch").write_text("committed state")
                raise RuntimeError("synthetic interruption")
            self.assertEqual((output / "preserved-epoch").read_text(), "committed state")
            checkpoint = output / "checkpoint.pt"
            checkpoint.write_bytes(b"synthetic inference checkpoint")
            (output / "model-manifest.json").write_text(json.dumps(dict(
                checkpoint_path=str(checkpoint), checkpoint_sha256=workflow.digest(checkpoint))))

        def run():
            return workflow.execute(root, "train", scene="circle", training_config=config,
                                    model_root=root / "models")

        with patch.object(workflow, "_source_sha256", return_value="a" * 64), \
                patch.object(workflow, "_completed", return_value={"products": {
                    "dataset_manifest": str(dataset)}}), \
                patch.object(workflow, "_dataset_product"), \
                patch.object(workflow, "_model_product"), \
                patch.object(workflow, "_run_command", side_effect=worker):
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                run()
            result = run()
            self.assertEqual(result["status"], "complete")
            self.assertEqual(sessions[0], sessions[1])
            self.assertTrue(sessions[0].name.endswith("-session"))
            run()
            self.assertEqual(len(sessions), 2, "completed workflow must not relaunch trainer")


if __name__ == "__main__":
    unittest.main()
