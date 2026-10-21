"""Preparation/formal boundary, truthful progress, and owned-child cleanup."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("campaign_pipeline", HERE / "run_campaign_pipeline.py")
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "plan").mkdir()

    def test_preparation_stops_at_ready_without_formal_simulation_or_figures(self):
        steps = []
        settings = dict(training_config=str(self.root / "config.json"), run_timeout=1800,
                        stage_timeout=3600, python=sys.executable)
        plan = dict(status="development-frozen")
        products = {scene: {"products": {"checkpoint_path": "/models/" + scene + ".pt",
                                        "dataset_manifest": "/datasets/" + scene + ".json"}}
                    for scene in ("circle", "grid", "spidermap")}
        with mock.patch.object(pipeline, "read_plan", return_value=plan, create=True), \
                mock.patch.object(pipeline, "completed_product", side_effect=lambda root, stage, scene: products[scene], create=True), \
                mock.patch.object(pipeline, "audit_coverage", create=True):
            result = pipeline.prepare_campaign(self.root, settings,
                lambda stage, command=None, scene=None: steps.append((stage, command, scene)))
        self.assertEqual(result, "ready-for-formal")
        names = [row[0] for row in steps]
        self.assertEqual(names[:3], ["sample-train", "sample-validation", "sample-evaluation"])
        self.assertEqual(names.count("datasets"), 3)
        self.assertEqual(names.count("train"), 3)
        self.assertEqual(names.count("evaluate"), 3)
        self.assertLess(names.index("coverage"), names.index("train"))
        self.assertNotIn("test", names)
        self.assertNotIn("figures", names)
        sampling = [command for stage, command, _ in steps if stage.startswith("sample-")]
        self.assertTrue(all("--no-build" in command for command in sampling))
        self.assertTrue(all(command[command.index("--max-attempts") + 1] == "2" for command in sampling))

    def test_failed_coverage_prevents_any_training(self):
        steps = []
        settings = dict(training_config="config", run_timeout=10, stage_timeout=10, python=sys.executable)
        with mock.patch.object(pipeline, "read_plan", return_value={"status": "development-frozen"}, create=True), \
                mock.patch.object(pipeline, "completed_product", return_value={"products": {"dataset_manifest": "/data.json"}}, create=True), \
                mock.patch.object(pipeline, "audit_coverage", side_effect=ValueError("insufficient coverage"), create=True):
            with self.assertRaisesRegex(ValueError, "insufficient coverage"):
                pipeline.prepare_campaign(self.root, settings,
                    lambda stage, command=None, scene=None: steps.append(stage))
        self.assertNotIn("train", steps)

    def test_progress_counts_completed_jobs_not_attempts_and_exposes_current_job(self):
        jobs = [dict(job_id="one", scene="circle", strategy=0, condition_id="baseline", seed_family=1),
                dict(job_id="two", scene="grid", strategy=0, condition_id="edge", seed_family=2)]
        (self.root / "plan/pipeline-state.json").write_text(json.dumps(dict(
            status="running", stage="sample-train", pid=os.getpid(), start_token="token",
            started_utc="2026-10-21T00:00:00+00:00", current_scene=None)))
        (self.root / "plan/state-train.json").write_text(json.dumps({"jobs": {
            "one": dict(jobs[0], status="complete", attempts=[{"status": "failed"}, {"status": "complete"}]),
            "two": dict(jobs[1], status="running", attempts=[])}}))
        with mock.patch.object(pipeline, "read_plan", return_value={}, create=True), \
                mock.patch.object(pipeline, "planned_jobs", side_effect=lambda plan, split: jobs if split == "train" else [], create=True), \
                mock.patch.object(pipeline, "is_live", return_value=True, create=True):
            report = pipeline.progress(self.root, now="2026-10-21T00:01:00+00:00")
        self.assertEqual(report["sampling"]["completed"], 1)
        self.assertEqual(report["sampling"]["remaining"], 1)
        self.assertEqual(report["current_job"]["scene"], "grid")
        self.assertEqual(report["current_job"]["ordinal"], 2)
        self.assertEqual(report["elapsed_seconds"], 60)
        self.assertEqual(report["session_elapsed_seconds"], 60)
        self.assertFalse(any("eta" in key.lower() for key in report))

    def test_stale_running_state_is_not_reported_as_live(self):
        (self.root / "plan/pipeline-state.json").write_text(json.dumps(dict(
            status="running", stage="train", pid=987654, start_token="stale",
            started_utc="2026-10-21T00:00:00+00:00")))
        with mock.patch.object(pipeline, "read_plan", return_value={}, create=True), \
                mock.patch.object(pipeline, "planned_jobs", return_value=[], create=True), \
                mock.patch.object(pipeline, "is_live", return_value=False, create=True):
            report = pipeline.progress(self.root)
        self.assertEqual(report["status"], "interrupted")
        self.assertFalse(report["process_alive"])

    def test_nonzero_stage_preserves_log_and_raises(self):
        log = self.root / "failure.log"
        with self.assertRaisesRegex(RuntimeError, "exit 7"):
            pipeline.run_command([sys.executable, "-c", "print('evidence'); raise SystemExit(7)"],
                                 log, {"signal": None}, lambda child: None)
        self.assertIn("evidence", log.read_text())
        metadata = json.loads(log.with_suffix(".process.json").read_text())
        self.assertEqual(metadata["returncode"], 7)

    def test_stop_reaps_child_that_uses_a_separate_session(self):
        log = self.root / "stop.log"
        ids = self.root / "child-id"
        script = ("import pathlib, subprocess, sys, time; "
                  "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True); "
                  "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)")
        cancellation = {"signal": None}
        def heartbeat(child):
            if ids.exists():
                cancellation["signal"] = "SIGTERM"
        with self.assertRaises(KeyboardInterrupt):
            pipeline.run_command([sys.executable, "-c", script, str(ids)], log,
                                 cancellation, heartbeat)
        pid = int(ids.read_text())
        self.assertIsNone(pipeline.campaign.process_identity(pid))
        metadata = json.loads(log.with_suffix(".process.json").read_text())
        self.assertIn("cleanup", metadata)

    def test_resume_seal_rejects_source_changes_and_archive_tampering(self):
        source = self.root / "source"
        source.mkdir()
        (source / "main.py").write_text("print('original')\n")
        snapshot = dict(sha256="original", scope=["main.py"], trace_configuration_suffixes=[])
        with mock.patch.object(pipeline, "ROOT", source), \
                mock.patch.object(pipeline, "read_plan", return_value={"source_sha256": "original"}), \
                mock.patch.object(pipeline.campaign.runner, "source_snapshot", return_value=snapshot):
            pipeline.seal_source(self.root)
            pipeline.seal_source(self.root)
            archive = self.root / "plan/source.tar.gz"
            self.assertTrue(archive.is_file())
            archive.write_bytes(archive.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "changed"):
                pipeline.seal_source(self.root)
        with mock.patch.object(pipeline, "read_plan", return_value={"source_sha256": "original"}), \
                mock.patch.object(pipeline.campaign.runner, "source_snapshot", return_value=dict(snapshot, sha256="new")):
            with self.assertRaisesRegex(ValueError, "source differs"):
                pipeline.seal_source(self.root)

    def test_orphan_between_launch_and_pid_record_is_discovered_and_stopped(self):
        logs = self.root / "plan/pipeline-logs"
        logs.mkdir()
        token = "pipeline-test-" + str(os.getpid())
        (logs / "lost.launch.json").write_text(json.dumps({"token": token}))
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
            env=dict(os.environ, VNDN_PIPELINE_TOKEN=token), start_new_session=True)
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        try:
            discovered = pipeline.active_children(self.root)
            self.assertIn(process.pid, [row["pid"] for row in discovered])
            self.assertEqual(pipeline.stop(self.root)["status"], "stopped")
            process.wait(timeout=2)
            self.assertIsNone(other.poll(), "unrelated user process must not be signalled")
        finally:
            for child in (process, other):
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=2)

    def test_current_terminal_receives_progress_every_ten_seconds(self):
        state, saved = {}, []
        with mock.patch.object(pipeline, "progress", return_value={"status": "running"}) as reading, \
                mock.patch.object(pipeline, "display") as displaying:
            heartbeat = pipeline.stage_heartbeat(self.root, state, lambda: saved.append(True),
                                                clock=iter([0, 5, 9, 10, 20]).__next__)
            for _ in range(5):
                heartbeat({"pid": 42})
        self.assertEqual(displaying.call_count, 3)
        self.assertEqual(reading.call_count, 3)
        self.assertEqual(state["child"], {"pid": 42})
        self.assertTrue(saved)

    def test_human_progress_distinguishes_action_total_and_current_run_time(self):
        report = dict(status="running", stage="test", elapsed_seconds=600,
            session_elapsed_seconds=60, sampling=dict(completed=48, total=48, remaining=0),
            formal=dict(completed=3, total=480, remaining=477), current_job=dict(scene="grid",
                strategy=3, condition_id="baseline", seed_family=50001, ordinal=4, total=480,
                elapsed_seconds=30))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            pipeline.display(report)
        text = output.getvalue()
        self.assertIn("本次已用: 1.0", text)
        self.assertIn("累计已用: 10.0", text)
        self.assertIn("当前轮已用: 0.5", text)


if __name__ == "__main__":
    unittest.main()
