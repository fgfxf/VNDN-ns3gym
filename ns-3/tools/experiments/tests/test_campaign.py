import importlib.util
import copy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "vndn_campaign", Path(__file__).resolve().parents[1] / "campaign.py")
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)


class CampaignDesignTests(unittest.TestCase):
    def test_full_design_has_one_shared_baseline_and_4080_jobs(self):
        plan = CAMPAIGN.make_plan("test", 300, 20, 3.5)
        self.assertEqual(len(plan["conditions"]), 17)
        self.assertEqual(len(CAMPAIGN.jobs_for(plan, "test")), 4080)
        self.assertEqual(len(CAMPAIGN.jobs_for(plan, "train")), 510)
        self.assertEqual(len(CAMPAIGN.jobs_for(plan, "validation")), 153)
        self.assertEqual(len(CAMPAIGN.jobs_for(plan, "evaluation")), 255)
        for scan in plan["scans"].values():
            self.assertEqual(len(scan), 5)
            self.assertEqual(scan.count(plan["baseline_condition_id"]), 1)
        families = [set(v) for v in plan["seed_families"].values()]
        for i, a in enumerate(families):
            for b in families[i + 1:]:
                self.assertFalse(a & b)
        jobs = CAMPAIGN.jobs_for(plan, "test")
        self.assertEqual(len({x["job_id"] for x in jobs}), len(jobs))
        self.assertTrue(all(x["strategy"] in range(4) for x in jobs))

    def test_duration_changes_load_but_does_not_become_a_scan_factor(self):
        plan = CAMPAIGN.make_plan("test", 200, 20, 3.5)
        self.assertEqual(len(plan["conditions"]), 17)
        index = {c["id"]: c for c in plan["conditions"]}
        baseline = index[plan["baseline_condition_id"]]
        self.assertEqual(baseline["requests"], 10000)
        for cid in plan["scans"]["vehicles"]:
            c = index[cid]
            self.assertEqual(c["requests"], c["vehicles"] * 5 * 200)
        for cid in plan["scans"]["vehicles_fixed_k"]:
            self.assertEqual(index[cid]["requests"], 10000)

    def test_pilot_is_disjoint_and_uses_seven_unique_edge_conditions(self):
        plan = CAMPAIGN.make_plan("test", 300, 20, 3.5)
        jobs = CAMPAIGN.jobs_for(plan, "pilot")
        self.assertEqual(len(jobs), 42)
        self.assertEqual(len({j["condition_id"] for j in jobs}), 7)
        self.assertTrue(all(j["strategy"] == 0 for j in jobs))
        self.assertTrue(all(j["seed_family"] < 20000 for j in jobs))

    def test_invalid_design_is_rejected_before_any_output(self):
        for duration, warmup, drain in [(0, 20, 3.5), (300, -1, 3.5), (300, 20, 2.5)]:
            with self.subTest(duration=duration, warmup=warmup, drain=drain):
                with self.assertRaises(ValueError):
                    CAMPAIGN.make_plan("test", duration, warmup, drain)

    def test_initialization_never_overwrites_a_campaign(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "campaign"
            CAMPAIGN.initialize(root, CAMPAIGN.make_plan("test", 300, 20, 3.5))
            before = (root / "plan/design.json").read_bytes()
            with self.assertRaises(FileExistsError):
                CAMPAIGN.initialize(root, CAMPAIGN.make_plan("changed", 200, 20, 3.5))
            self.assertEqual((root / "plan/design.json").read_bytes(), before)

    def test_resume_revalidates_a_complete_attempt_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = CAMPAIGN.jobs_for(CAMPAIGN.make_plan("test"), "test")[3]
            path = root / "manifest.json"
            manifest = dict(status="complete", block_id=job["block_id"], strategy=3,
                            scenario=job["scene"], source={"sha256": "source"},
                            model={"sha256": "model"}, validation_only=False)
            path.write_text(json.dumps(manifest))
            attempt = dict(status="complete", manifest_path=str(path),
                           manifest_sha256=CAMPAIGN.digest(path))
            with patch.object(CAMPAIGN.runner.summary, "summarize_run", return_value={}) as verify:
                result = CAMPAIGN.completed_attempt([attempt], job, "source", "model")
                self.assertEqual(result, root)
                verify.assert_called_once_with(root)
            path.write_text(json.dumps(dict(manifest, strategy=0)))
            with self.assertRaisesRegex(ValueError, "hash"):
                CAMPAIGN.completed_attempt([attempt], job, "source", "model")

    def test_resume_does_not_accept_wrong_source_model_or_pilot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = CAMPAIGN.jobs_for(CAMPAIGN.make_plan("test"), "test")[3]
            for change in ({"source": {"sha256": "wrong"}},
                           {"model": {"sha256": "wrong"}}, {"validation_only": True},
                           {"block_id": "another-block"}):
                manifest = dict(status="complete", block_id=job["block_id"], strategy=3,
                                scenario=job["scene"], source={"sha256": "source"},
                                model={"sha256": "model"}, validation_only=False)
                manifest.update(change)
                path = root / "manifest.json"
                path.write_text(json.dumps(manifest))
                attempt = dict(status="complete", manifest_path=str(path),
                               manifest_sha256=CAMPAIGN.digest(path))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    CAMPAIGN.completed_attempt([attempt], job, "source", "model")

    def test_two_complete_attempts_cannot_count_as_two_repetitions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = CAMPAIGN.jobs_for(CAMPAIGN.make_plan("test"), "test")[0]
            attempts = []
            for i in (1, 2):
                path = root / str(i) / "manifest.json"
                path.parent.mkdir()
                path.write_text(json.dumps(dict(status="complete", block_id=job["block_id"],
                    strategy=0, scenario=job["scene"], source={"sha256": "source"},
                    model=None, validation_only=False)))
                attempts.append(dict(status="complete", manifest_path=str(path),
                                     manifest_sha256=CAMPAIGN.digest(path)))
            with patch.object(CAMPAIGN.runner.summary, "summarize_run", return_value={}):
                with self.assertRaises(ValueError):
                    CAMPAIGN.completed_attempt(attempts, job, "source")

    def test_resume_recovers_an_attempt_written_before_state_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = CAMPAIGN.jobs_for(CAMPAIGN.make_plan("test"), "pilot")[0]
            attempt = root / "pilot" / job["job_id"] / "attempt-001"
            attempt.mkdir(parents=True)
            record = dict(attempt=1, status="failed", path=str(attempt),
                          error="interrupted child")
            (attempt / "attempt.json").write_text(json.dumps(record))
            self.assertEqual(CAMPAIGN.reconcile_attempts(root, job, []), [record])
            self.assertEqual(CAMPAIGN.reconcile_attempts(root, job, [record]), [record])

    def test_ambiguous_unfinished_attempt_is_preserved_as_failed_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = CAMPAIGN.jobs_for(CAMPAIGN.make_plan("test"), "train")[0]
            attempt = root / "sampling" / job["job_id"] / "attempt-001"
            attempt.mkdir(parents=True)
            sentinel = attempt / "partial-data.csv"
            sentinel.write_text("evidence")
            recovered = CAMPAIGN.reconcile_attempts(root, job, [])
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["status"], "failed")
            self.assertEqual(sentinel.read_text(), "evidence")

    def test_resume_identity_freezes_real_conditions_time_seeds_and_source(self):
        original = CAMPAIGN.make_plan("test")
        for field, value in (("measurement_duration", 600), ("source_sha256", "changed")):
            changed = copy.deepcopy(original)
            changed[field] = value
            self.assertNotEqual(CAMPAIGN.execution_identity(original, "train"),
                                CAMPAIGN.execution_identity(changed, "train"))
        changed = copy.deepcopy(original)
        changed["conditions"][0]["requests"] += 1
        self.assertNotEqual(CAMPAIGN.execution_identity(original, "test"),
                            CAMPAIGN.execution_identity(changed, "test"))
        changed = copy.deepcopy(original)
        changed["seed_families"]["train"].append(20099)
        self.assertNotEqual(CAMPAIGN.execution_identity(original, "train"),
                            CAMPAIGN.execution_identity(changed, "train"))

    def test_later_model_freeze_does_not_change_training_identity(self):
        original = CAMPAIGN.make_plan("test")
        later = copy.deepcopy(original)
        later["models"] = {"circle": {"path": "/model.pt", "sha256": "model"}}
        later["status"] = "formal-frozen"
        self.assertEqual(CAMPAIGN.execution_identity(original, "train"),
                         CAMPAIGN.execution_identity(later, "train"))
        self.assertNotEqual(CAMPAIGN.execution_identity(original, "test"),
                            CAMPAIGN.execution_identity(later, "test"))

    def test_formal_freeze_checks_model_contract_not_only_file_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            CAMPAIGN.initialize(root, CAMPAIGN.make_plan("test"))
            path = root / "not-a-model.pt"
            path.write_bytes(b"not a valid formal checkpoint")
            models = [scene + "=" + str(path) for scene in CAMPAIGN.SCENES]
            before = (root / "plan/design.json").read_bytes()
            with patch.object(CAMPAIGN.runner, "source_snapshot", return_value={"sha256": "source"}):
                with self.assertRaises(ValueError):
                    CAMPAIGN.freeze(root, "formal", models, 1800)
            self.assertEqual((root / "plan/design.json").read_bytes(), before)

    def test_signals_wait_for_runner_cleanup_and_preserve_failed_attempt_and_state(self):
        # Real /usr/bin/time and real run_experiment, with fixture-only waf and
        # controller children. No simulator binary or SUMO process is launched.
        from test_run_experiment import RunExperimentTest

        def descendants(pid):
            result = []
            path = Path("/proc") / str(pid) / "task" / str(pid) / "children"
            try:
                children = [int(value) for value in path.read_text().split()]
            except FileNotFoundError:
                return result
            for child in children:
                result.append(child)
                result.extend(descendants(child))
            return result

        for interruption in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=interruption.name):
                fixture = RunExperimentTest()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                fixture.state.write_text(json.dumps({"sleep": 30, "spawn_descendant": True}))
                tool_dir = fixture.root / "tools/experiments"
                tool_dir.mkdir(parents=True)
                for name in ("run_experiment.py", "summarize.py"):
                    shutil.copyfile(CAMPAIGN.HERE / name, tool_dir / name)
                root = fixture.root / "campaign"
                plan = CAMPAIGN.make_plan("cancel-test")
                plan.update(source_sha256="source", status="formal-frozen",
                            minimum_free_disk_bytes=0)
                plan["models"]["circle"] = dict(
                    path=str(fixture.model), sha256=CAMPAIGN.digest(fixture.model))
                CAMPAIGN.initialize(root, plan)
                job = CAMPAIGN.jobs_for(plan, "test")[3]
                harness = """
import importlib.util, json, pathlib, sys
spec=importlib.util.spec_from_file_location('campaign', sys.argv[1])
campaign=importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
campaign.ROOT=pathlib.Path(sys.argv[2])
campaign.HERE=campaign.ROOT/'tools/experiments'
campaign.runner.source_snapshot=lambda root: {'sha256':'source'}
campaign.prepare_job_input=lambda root, plan, job: pathlib.Path(sys.argv[3])
job=json.loads(sys.argv[4])
campaign.jobs_for=lambda plan, split: [job]
sys.exit(campaign.main(['run','--root',sys.argv[5],'--split','test']))
"""
                unrelated = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    start_new_session=True)
                process = subprocess.Popen(
                    [sys.executable, "-c", harness, str(Path(CAMPAIGN.__file__)),
                     str(fixture.root), str(fixture.config), json.dumps(job), str(root)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                owned = []
                try:
                    deadline = time.monotonic() + 5
                    ready = fixture.root / "process-ids.json"
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(ready.exists(), "The nested real runner must actually start")
                    owned = descendants(process.pid)
                    self.assertGreaterEqual(len(owned), 5)
                    process.send_signal(interruption)
                    time.sleep(.05)
                    if process.poll() is None:
                        process.send_signal(interruption)
                    stdout, stderr = process.communicate(timeout=8)
                    self.assertEqual(process.returncode, 1, (stdout, stderr))
                    state = json.loads((root / "plan/state-test.json").read_text())
                    entry = state["jobs"][job["job_id"]]
                    self.assertEqual(entry["status"], "failed")
                    self.assertEqual(len(entry["attempts"]), 1)
                    attempt = entry["attempts"][0]
                    self.assertEqual(attempt["status"], "failed")
                    self.assertEqual(attempt["interrupted_by"], interruption.name)
                    self.assertEqual(attempt, json.loads(
                        (Path(attempt["path"]) / "attempt.json").read_text()))
                    self.assertNotEqual(attempt["resources"]["exit_code"], 0)
                    self.assertTrue((Path(attempt["path"]) / "resources.txt").is_file())
                    manifest = json.loads(Path(attempt["manifest_path"]).read_text())
                    self.assertEqual(manifest["status"], "failed")
                    self.assertIn("SIGTERM", manifest["error"])
                    self.assertIsNone(unrelated.poll())
                    for pid in owned:
                        stat = Path("/proc") / str(pid) / "stat"
                        self.assertTrue(
                            not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z",
                            "An owned runner or simulation process survived cancellation")
                finally:
                    for pid in reversed(owned):
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    CAMPAIGN.runner.stop_group(process)
                    CAMPAIGN.runner.stop_group(unrelated)
                    process.stdout.close()
                    process.stderr.close()

    def test_unresponsive_runner_cleanup_waits_then_reaps_owned_separate_sessions(self):
        self.assertGreaterEqual(CAMPAIGN.CANCEL_GRACE_SECONDS, 25)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ready = root / "pids.json"
            resources = root / "resources.json"
            script = """
import json, os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],
                       start_new_session=True)
pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(30)
"""
            process = subprocess.Popen(
                ["/usr/bin/time", "-f", '{"exit_code":%x,"wall_seconds":%e}',
                 "-o", str(resources), sys.executable, "-c", script, str(ready)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                env=dict(os.environ, LC_ALL="C"))
            pids = []
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                pids = json.loads(ready.read_text())
                # Only shorten the unit fixture's grace period; production is 30 s.
                with patch.object(CAMPAIGN, "CANCEL_GRACE_SECONDS", .15):
                    cleanup = CAMPAIGN.cancel_measured_runner(process)
                self.assertGreaterEqual(cleanup["elapsed_seconds"], .15)
                self.assertEqual(cleanup["runner_pids"], [pids[0]])
                self.assertEqual(set(cleanup["forced_pids"]), set(pids))
                self.assertNotIn("time_wrapper_forced", cleanup)
                self.assertNotEqual(process.returncode, 0)
                # GNU time's %x can be 0 for a child killed by a signal.
                # Its actual wait status and signal line must still prove failure.
                resource_text = resources.read_text()
                resource = json.loads(resource_text.splitlines()[-1])
                self.assertIn("Command terminated by signal 9", resource_text)
                self.assertGreaterEqual(resource["wall_seconds"], .15)
                for pid in pids:
                    self.assertIsNone(CAMPAIGN.process_identity(pid))
            finally:
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                CAMPAIGN.runner.stop_group(process)


if __name__ == "__main__":
    unittest.main()
