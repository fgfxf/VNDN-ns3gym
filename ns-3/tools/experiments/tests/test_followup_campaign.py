"""Fixed follow-up matrix, immutable evidence, cancellation and progress."""
import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from experiment_test_support import valid_run

SCRIPT = Path(__file__).resolve().parents[1] / "followup_campaign.py"
SPEC = importlib.util.spec_from_file_location("followup_campaign", SCRIPT)
C = importlib.util.module_from_spec(SPEC)

class FollowupCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SPEC.loader.exec_module(C)

    def test_matrix_has_99_unique_tasks_and_648000_requests(self):
        tasks = C.make_tasks()
        self.assertEqual(len(tasks), 99)
        self.assertEqual(len({t["id"] for t in tasks}), 99)
        self.assertEqual(sum(t["requests"] for t in tasks), 648000)
        self.assertEqual({stage: sum(t["stage"] == stage for t in tasks)
                          for stage in ("accuracy", "online", "state")},
                         {"accuracy": 36, "online": 36, "state": 27})

    def test_matrix_pairs_periods_and_strategies_by_fixed_new_seeds(self):
        tasks = C.make_tasks()
        for scene in C.SCENES:
            subset = [t for t in tasks if t["scene"] == scene]
            self.assertEqual({t["seed_family"] for t in subset}, {84001, 84002, 84003})
            for interval in (20, 40, 80, 160):
                for seed in C.SEEDS:
                    pair = [t for t in subset if t["hello_interval_ms"] == interval and
                            t["seed_family"] == seed and t["stage"] in ("accuracy", "online")]
                    self.assertEqual({t["strategy"] for t in pair}, {0, 3})
                    self.assertEqual({t["condition_id"] for t in pair},
                                     {"n10-v30-k6000-hello{}".format(interval)})
                    self.assertEqual(len({C.input_key(t) for t in pair}), 1)
            self.assertEqual({t["vehicles"] for t in subset if t["stage"] == "state"}, {5, 15, 20})

    def test_completed_evidence_reuse_rejects_changed_manifest_and_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            task, plan, record = self.fixture(Path(temp))
            self.assertEqual(C.verify_completed(record, task, plan), Path(record["run_dir"]))
            (Path(record["run_dir"]) / "payload.txt").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "hash"):
                C.verify_completed(record, task, plan)
            (Path(record["run_dir"]) / "payload.txt").write_text("fixture")
            manifest = Path(record["run_dir"]) / "manifest.json"
            manifest.write_text(manifest.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "hash"):
                C.verify_completed(record, task, plan)

    def fixture(self, root):
        task = C.make_tasks()[0]
        task = dict(task, input_hashes={})
        run = root / "run"
        run.mkdir()
        valid_run(run)
        payload = run / "payload.txt"
        payload.write_text("fixture")
        config = dict(C.read(run / "experiment.json"), hello_interval_ms=20,
                      resource_observations=True, training_snapshots=True)
        C.write(run / "experiment.json", config)
        artifacts = {str(p.relative_to(run)): C.sha(p) for p in run.rglob("*") if p.is_file()}
        manifest = dict(schema_version=1, status="complete", block_id=task["id"], scenario=task["scene"],
                        strategy=0, source={"sha256": "src"}, model=None,
                        input_hashes={}, execution_mode="existing-binary", validation_only=False,
                        artifact_hashes=artifacts,
                        binary={"sha256": "bin"},
                        processes={"simulation": {"returncode": 0}})
        C.write(run / "manifest.json", manifest)
        record = dict(status="complete", run_dir=str(run),
                      manifest_sha256=C.sha(run / "manifest.json"))
        plan = dict(source={"sha256": "src"}, models={}, binaries={task["scene"]: {"sha256": "bin"}})
        return task, plan, record

    def test_completed_wrong_task_source_or_build_mode_rejected(self):
        for field, value in (("source", {"sha256": "other"}), ("strategy", 3),
                             ("validation_only", True), ("execution_mode", "waf-build-and-run")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                task, plan, record = self.fixture(Path(temp))
                path = Path(record["run_dir"]) / "manifest.json"
                data = C.read(path)
                data[field] = value
                C.write(path, data)
                record["manifest_sha256"] = C.sha(path)
                with self.assertRaises(ValueError):
                    C.verify_completed(record, task, plan)

    def test_partial_run_is_preserved_and_retry_number_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = C.make_tasks()[0]
            directory = root / "runs" / task["id"]
            (directory / "attempt-001").mkdir(parents=True)
            (directory / "attempt-001" / "partial.log").write_text("keep")
            self.assertEqual(C.next_attempt(root, task), 2)
            (directory / "attempt-002").mkdir()
            with self.assertRaisesRegex(ValueError, "2"):
                C.next_attempt(root, task)
            self.assertEqual((directory / "attempt-001" / "partial.log").read_text(), "keep")

    def test_completed_manifest_recovers_after_progress_commit_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = C.make_tasks()[0]
            attempt = root / "runs" / task["id"] / "attempt-001"
            attempt.mkdir(parents=True)
            (root / "plan/tasks").mkdir(parents=True)
            task, plan, expected = self.fixture(attempt)
            self.assertFalse(C.task_record(root, task).exists())
            recovered = C.recover_completed(root, task, plan)
            self.assertEqual(recovered["run_dir"], expected["run_dir"])
            self.assertTrue(C.task_record(root, task).is_file())
            self.assertEqual(C.recover_completed(root, task, plan), recovered)

    def test_progress_reports_counts_elapsed_and_no_remaining_time(self):
        plan = {"tasks": C.make_tasks()}
        state = dict(status="running", stage="online", completed=45,
                     stage_completed={"accuracy": 36, "online": 9, "state": 0},
                     session_elapsed_seconds=120, cumulative_elapsed_seconds=180,
                     current_task=C.make_tasks()[45], current_elapsed_seconds=13)
        text = C.format_status(state, plan)
        self.assertIn("45/99", text)
        self.assertIn("54", text)
        self.assertIn("已用", text)
        self.assertIn("9/36", text)
        self.assertNotIn("预计", text)
        self.assertNotIn("剩余时间", text)

    def test_stop_refuses_reused_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "plan").mkdir()
            C.write(root / "plan/followup-state.json", {"pid": 123, "start_token": "old"})
            with patch.object(C, "process_identity", return_value=(123, "new")), patch.object(C.os, "kill") as kill:
                self.assertFalse(C.request_stop(root))
                kill.assert_not_called()

    def test_run_limit_then_resume_reuses_finished_run_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            root = project / "data/experiments/followup"
            tasks = [dict(t, input_hashes={}, config_path="fixture") for t in C.make_tasks()[:3]]
            plan = dict(tasks=tasks, source={"sha256": "src"}, models={},
                        binaries={"circle": {"sha256": "bin"}})
            invoked = []
            def run(argv, project_root, cancelled):
                cancelled()
                task_id = argv[argv.index("--block-id") + 1]
                task = next(t for t in tasks if t["id"] == task_id)
                directory = Path(argv[argv.index("--output-root") + 1])
                _, _, record = self.fixture(directory)
                manifest_path = Path(record["run_dir"]) / "manifest.json"
                manifest = C.read(manifest_path)
                manifest["block_id"] = task_id
                C.write(manifest_path, manifest)
                invoked.append(task_id)
                self.assertIn("--no-build", argv)
                self.assertNotIn("--test-controller", argv)
                return 0
            with patch.object(C, "ROOT", project), patch.object(C, "initialize", return_value=plan), \
                    patch.object(C, "verify_runtime"), patch.object(C.runner, "_run_block", side_effect=run), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(C.execute(root, max_runs=1), 0)
                self.assertEqual(C.execute(root, max_runs=1), 0)
                self.assertEqual(invoked, [tasks[0]["id"], tasks[1]["id"]])
                record = C.read(C.task_record(root, tasks[0]))
                (Path(record["run_dir"]) / "payload.txt").write_text("changed")
                self.assertEqual(C.execute(root, max_runs=1), 1)
                self.assertEqual(len(invoked), 2)

    def test_interrupt_preserves_partial_attempt_for_next_run(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            root = project / "data/experiments/followup"
            task = dict(C.make_tasks()[0], input_hashes={}, config_path="fixture")
            plan = dict(tasks=[task], source={"sha256": "src"}, models={}, binaries={})
            def interrupted(argv, project_root, cancelled):
                attempt = Path(argv[argv.index("--output-root") + 1])
                (attempt / "partial.log").write_text("partial evidence")
                raise KeyboardInterrupt("fixture stop")
            with patch.object(C, "ROOT", project), patch.object(C, "initialize", return_value=plan), \
                    patch.object(C, "verify_runtime"), patch.object(C.runner, "_run_block", side_effect=interrupted), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(C.execute(root), 130)
            state = C.read(root / "plan/followup-state.json")
            self.assertEqual(state["status"], "interrupted")
            self.assertEqual(state["completed"], 0)
            self.assertEqual(C.next_attempt(root, task), 2)
            self.assertEqual((root / "runs" / task["id"] / "attempt-001/partial.log").read_text(), "partial evidence")

    def test_analysis_zero_exit_requires_artifacts_and_resume_does_not_resimulate(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            root = project / "data/experiments/followup"
            task = dict(C.make_tasks()[0], input_hashes={}, config_path="fixture")
            plan = dict(tasks=[task], source={"sha256": "src"}, models={},
                        binaries={"circle": {"sha256": "bin"}})
            def run(argv, project_root, cancelled):
                directory = Path(argv[argv.index("--output-root") + 1])
                self.fixture(directory)
                return 0
            process = Mock(returncode=0)
            process.poll.return_value = 0
            with patch.object(C, "ROOT", project), patch.object(C, "initialize", return_value=plan), \
                    patch.object(C, "verify_runtime"), patch.object(C.runner, "_run_block", side_effect=run) as invoke, \
                    patch.object(C.subprocess, "Popen", return_value=process), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(C.execute(root), 1)
                self.assertEqual(C.read(root / "plan/followup-state.json")["completed"], 1)
                (root / "analysis").mkdir()
                (root / "figures").mkdir()
                (root / "figures/index.html").write_text("fixture figures")
                C.write(root / "analysis/status.json", {"status": "complete"})
                C.write(root / "analysis/summary.json", {"status": "complete",
                    "counts": {"accuracy": 36, "online": 63, "cpu_processes": 15},
                    "artifact_hashes": {"figures/index.html": C.sha(root / "figures/index.html")}})
                self.assertEqual(C.execute(root), 0)
                self.assertEqual(invoke.call_count, 1)
            self.assertEqual(C.read(root / "plan/followup-state.json")["status"], "complete")

if __name__ == "__main__":
    unittest.main()
