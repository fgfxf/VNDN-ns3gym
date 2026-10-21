import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import sys
import os
import subprocess
import signal
import tempfile
import time
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "workflow", Path(__file__).resolve().parents[1] / "campaign_workflow.py")
WORKFLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW)


class WorkflowGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "plan").mkdir()

    def design(self, status):
        (self.root / "plan/design.json").write_text(json.dumps({
            "schema_version": 1, "campaign_id": "fixture", "status": status,
            "validation_only": False, "source_sha256": "a" * 64}))

    def test_unfrozen_sampling_cannot_be_used_to_build_datasets(self):
        self.design("candidate-unfrozen")
        with self.assertRaisesRegex(ValueError, "frozen"):
            WORKFLOW.execute(self.root, "datasets")

    def test_independent_evaluation_requires_formal_model_freeze(self):
        self.design("development-frozen")
        with self.assertRaisesRegex(ValueError, "formal-frozen"):
            WORKFLOW.execute(self.root, "evaluate")

    def test_figures_cannot_be_built_from_development_results(self):
        self.design("development-frozen")
        with self.assertRaisesRegex(ValueError, "formal-frozen"):
            WORKFLOW.execute(self.root, "figures")


class WorkflowStagesTests(unittest.TestCase):
    """Synthetic stage products test orchestration, never scientific results."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "campaign"
        self.root.mkdir()
        self.calls = []
        self.plan = {
            "schema_version": 1, "campaign_id": "validation-fixture",
            "status": "development-frozen", "validation_only": True,
            "source_sha256": "a" * 64, "measurement_start": 20,
            "measurement_duration": 300, "drain_seconds": 3.5,
            "conditions": [{"id": "baseline", "vehicles": 10, "speed_kmh": 30,
                            "requests": 15000}],
            "baseline_condition_id": "baseline",
            "scans": {key: ["baseline"] for key in
                      ("interest", "speed", "vehicles", "vehicles_fixed_k")},
            "seed_families": {"pilot": [1, 2], "train": [11, 12],
                             "validation": [21, 22], "evaluation": [31, 32],
                             "test": [41, 42]},
            "bootstrap": {"resamples": 10000, "seed": 61021},
            "models": {}, "timeouts": {"default": 100}, "time_bin_seconds": 5,
        }
        self.write(self.root / "plan/design.json", self.plan)
        self.config = self.root / "training-config.json"
        self.write(self.config, {"initialization_seeds": [101, 102, 103], "epochs": 1})
        self.exports = {}
        for split in ("train", "validation", "evaluation", "test"):
            rows = []
            for scene in ("circle", "grid", "spidermap"):
                for seed in self.plan["seed_families"][split]:
                    block = "{}-{}-baseline-s{}".format(split, scene, seed)
                    for strategy in (range(4) if split == "test" else (0,)):
                        job = block + "-a" + str(strategy)
                        folder = self.root / "raw-fixture" / job
                        self.write(folder / "manifest.json", {"job": job})
                        rows.append(dict(job_id=job, block_id=block, split=split,
                                         scene=scene, condition_id="baseline",
                                         seed_family=seed, strategy=strategy, path=str(folder),
                                         manifest_sha256=self.sha(folder / "manifest.json")))
            self.exports[split] = rows
        for name, replacement in (
            ("_source_sha256", lambda: "a" * 64),
            ("_export_runs", lambda root, split: copy.deepcopy(self.exports[split])),
            ("_run_command", self.worker),
            ("_load_dataset_manifest", lambda path: json.loads(Path(path).read_text())),
            ("_validate_checkpoint", lambda *args, **kwargs: None),
        ):
            p = patch.object(WORKFLOW, name, replacement, create=True)
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def worker(self, command, log_path, timeout):
        self.calls.append(list(command))
        Path(log_path).write_text("validation_only synthetic worker\n")
        def option(flag):
            return Path(command[command.index(flag) + 1])
        script = Path(command[1]).name
        if script == "build_training_dataset.py":
            sources = option("--sources")
            spec = json.loads(sources.read_text())
            output = option("--output-dir")
            output.mkdir()
            labels = list(range(2 if spec["scenario"] == "circle" else 7))
            manifest = dict(schema_version=1, scenario=spec["scenario"], validation_only=True,
                            label_values=labels, source_code_sha256="a" * 64,
                            source_specification=str(sources),
                            source_specification_sha256=self.sha(sources),
                            shards=[dict(source_path=row["path"], split=row["split"],
                                         seed_family=row["seed_family"],
                                         source_manifest_sha256=row["manifest_sha256"])
                                    for row in spec["runs"]])
            self.write(output / "dataset-manifest.json", manifest)
        elif script == "train_tkan_lstm.py":
            dataset = option("--dataset-manifest")
            data = json.loads(dataset.read_text())
            output = option("--output-root") / "20261021T000001.000001Z"
            output.mkdir(parents=True)
            candidates = []
            offset = command.index("--initialization-seeds") + 1
            seeds = []
            while offset < len(command) and not command[offset].startswith("--"):
                seeds.append(int(command[offset]))
                offset += 1
            for seed in seeds:
                checkpoint = output / ("seed-{}.pt".format(seed))
                checkpoint.write_bytes(("synthetic-checkpoint-" + str(seed)).encode())
                history = checkpoint.with_suffix(".jsonl")
                history.write_text('{"epoch":1}\n')
                candidates.append(dict(seed=seed, checkpoint_path=str(checkpoint),
                                       checkpoint_sha256=self.sha(checkpoint),
                                       history_path=str(history), history_sha256=self.sha(history)))
            final = output / "checkpoint.pt"
            final.write_bytes(Path(candidates[0]["checkpoint_path"]).read_bytes())
            history = output / "training-history.csv"
            history.write_text("epoch,train_loss,validation_loss,validation_macro_f1\n1,1,1,.5\n")
            self.write(output / "model-manifest.json", dict(
                schema_version=1, scenario=data["scenario"], frozen=True, validation_only=True,
                checkpoint_path=str(final), checkpoint_sha256=self.sha(final),
                dataset_manifest=str(dataset), dataset_manifest_sha256=self.sha(dataset),
                selected_seed=seeds[0], candidates=candidates, evaluation_opened=False,
                training_history=dict(path=str(history), sha256=self.sha(history))))
        elif script == "formal_training.py":
            model_path = option("--model-manifest")
            model = json.loads(model_path.read_text())
            output = option("--output-dir")
            output.mkdir()
            (output / "predictions.jsonl").write_text('{"fixture":true}\n')
            self.write(output / "evaluation.json", dict(
                schema_version=1, scenario=model["scenario"], split="evaluation",
                validation_only=True, model_sha256=model["checkpoint_sha256"],
                model_manifest=str(model_path), model_manifest_sha256=self.sha(model_path),
                dataset_manifest_sha256=model["dataset_manifest_sha256"],
                prediction_file_sha256=self.sha(output / "predictions.jsonl"),
                training_history=model["training_history"],
                bootstrap=dict(repetitions=10000, analysis_seed=61021)))
        elif script == "aggregate_campaign.py":
            source = Path(command[2])
            manifest = json.loads(source.read_text())
            output = option("--output-dir")
            output.mkdir()
            self.write(output / "aggregate.json", dict(
                schema_version=1, status="complete", validation_only=True,
                campaign_id=manifest["campaign_id"], campaign_sha256=self.sha(source)))
        elif script == "plot_campaign.py":
            output = option("--output-dir")
            output.mkdir()
            items = []
            for index in range(30):
                files, hashes = {}, {}
                for extension in ("pdf", "svg", "png"):
                    filename = "{}.{}".format(index, extension)
                    (output / filename).write_bytes(b"synthetic validation-only image")
                    files[extension], hashes[extension] = filename, self.sha(output / filename)
                items.append(dict(id=index, files=files, sha256=hashes))
            self.write(output / "figure-index.json", dict(
                schema_version=1, status="complete", validation_only=True, figures=items,
                campaign_id=self.plan["campaign_id"],
                analysis_sha256=self.sha(Path(command[2]) / "aggregate.json"),
                diagnostics=[]))
        else:
            raise AssertionError("unexpected subprocess: " + str(command))

    def run_stage(self, stage, **options):
        return WORKFLOW.execute(self.root, stage, python=sys.executable,
                                model_root=self.root / "models",
                                allow_validation_only=True, **options)

    def train(self):
        first = self.run_stage("datasets")
        self.assertEqual(first["status"], "complete")
        trained = self.run_stage("train", training_config=self.config)
        self.assertEqual(trained["status"], "complete")
        return trained

    def formal(self):
        self.train()
        for scene in ("circle", "grid", "spidermap"):
            candidates = list((self.root / "models" / scene).glob("**/model-manifest.json"))
            self.assertEqual(len(candidates), 1)
            manifest = json.loads(candidates[0].read_text())
            self.plan["models"][scene] = dict(path=manifest["checkpoint_path"],
                                              sha256=manifest["checkpoint_sha256"])
        self.plan["status"] = "formal-frozen"
        self.write(self.root / "plan/design.json", self.plan)

    def test_complete_pipeline_executes_commands_and_preserves_split_and_block_identity(self):
        self.formal()
        result = self.run_stage("evaluate")
        self.assertEqual(result["status"], "complete")
        result = self.run_stage("figures")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(self.calls), 11)
        sources = list((self.root / "workflow/datasets").glob("**/sources.json"))
        self.assertEqual(len(sources), 3)
        for path in sources:
            spec = json.loads(path.read_text())
            self.assertTrue(spec["validation_only"])
            self.assertEqual({row["split"] for row in spec["runs"]},
                             {"train", "validation", "evaluation"})
            self.assertEqual(len(spec["runs"]), 6)
        manifests = list((self.root / "workflow/figures").glob("**/campaign.json"))
        combined = json.loads(manifests[0].read_text())
        self.assertEqual(combined["repetitions"], [41, 42])
        self.assertEqual(len(combined["blocks"]), 6)
        self.assertTrue(all(set(b["runs"]) == {"0", "1", "2", "3"}
                            for b in combined["blocks"]))
        self.assertEqual(combined["models"], self.plan["models"])

    def test_complete_dataset_resume_checks_hash_and_does_not_rebuild(self):
        result = self.run_stage("datasets")
        self.assertEqual(result["status"], "complete")
        self.run_stage("datasets")
        self.assertEqual(len(self.calls), 3)
        manifest = next((self.root / "workflow/datasets").glob("**/dataset-manifest.json"))
        manifest.write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash|changed"):
            self.run_stage("datasets")
        self.assertEqual(len(self.calls), 3)

    def test_incomplete_or_duplicate_export_stops_before_any_builder(self):
        for replacement in (self.exports["train"][:-1],
                            self.exports["train"] + self.exports["train"][:1]):
            with patch.object(WORKFLOW, "_export_runs", lambda root, split:
                              replacement if split == "train" else self.exports[split], create=True):
                with self.assertRaisesRegex(ValueError, "complete|duplicate"):
                    self.run_stage("datasets")
        self.assertEqual(self.calls, [])

    def test_cross_split_seed_overlap_is_rejected(self):
        self.plan["seed_families"]["evaluation"] = [11, 32]
        self.write(self.root / "plan/design.json", self.plan)
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.run_stage("datasets")

    def test_export_manifest_hash_is_rechecked(self):
        source = Path(self.exports["train"][0]["path"]) / "manifest.json"
        source.write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.run_stage("datasets")

    def test_child_failure_is_recorded_and_retry_preserves_attempt(self):
        with patch.object(WORKFLOW, "_run_command", side_effect=RuntimeError("child exit 7"),
                          create=True):
            with self.assertRaisesRegex(RuntimeError, "child exit 7"):
                self.run_stage("datasets", scene="circle")
        records = list((self.root / "workflow/datasets/circle").glob("attempt-*/attempt.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["status"], "failed")
        first = records[0].read_bytes()
        self.assertEqual(self.run_stage("datasets", scene="circle")["status"], "complete")
        self.assertEqual(records[0].read_bytes(), first)
        self.assertEqual(len(list(records[0].parent.parent.glob("attempt-*"))), 2)

    def test_training_requires_datasets_and_three_frozen_initializations(self):
        with self.assertRaisesRegex(ValueError, "datasets"):
            self.run_stage("train", training_config=self.config)
        self.assertEqual(self.run_stage("datasets")["status"], "complete")
        self.write(self.config, {"initialization_seeds": [101, 102], "epochs": 1})
        with self.assertRaisesRegex(ValueError, "three|3"):
            self.run_stage("train", training_config=self.config)

    def test_training_config_change_cannot_silently_select_another_model(self):
        self.train()
        self.write(self.config, {"initialization_seeds": [101, 102, 103], "epochs": 2})
        with self.assertRaisesRegex(ValueError, "identity|config|changed"):
            self.run_stage("train", training_config=self.config)
        self.assertEqual(len(self.calls), 6)

    def test_formal_freeze_allows_verified_training_resume_but_no_new_training(self):
        self.train()
        self.plan["status"] = "formal-frozen"
        self.write(self.root / "plan/design.json", self.plan)
        self.assertEqual(self.run_stage("train", training_config=self.config)["status"], "complete")
        self.assertEqual(len(self.calls), 6)
        other = self.root / "workflow/train/grid"
        # Existing failed/incomplete training cannot be continued after opening formal evaluation.
        for path in other.glob("attempt-*/attempt.json"):
            record = json.loads(path.read_text())
            record["status"] = "failed"
            self.write(path, record)
        with self.assertRaisesRegex(ValueError, "formal-frozen|hash|changed"):
            self.run_stage("train", scene="grid", training_config=self.config)

    def test_evaluation_rejects_a_model_different_from_formal_freeze(self):
        self.formal()
        self.plan["models"]["circle"]["sha256"] = "b" * 64
        self.write(self.root / "plan/design.json", self.plan)
        with self.assertRaisesRegex(ValueError, "frozen|hash"):
            self.run_stage("evaluate")
        self.assertEqual(len(self.calls), 6)

    def test_figures_require_evaluation_and_complete_test_export(self):
        self.formal()
        with self.assertRaisesRegex(ValueError, "evaluate"):
            self.run_stage("figures")
        self.assertEqual(self.run_stage("evaluate")["status"], "complete")
        self.exports["test"].pop()
        with self.assertRaisesRegex(ValueError, "complete"):
            self.run_stage("figures")
        self.assertEqual(len(self.calls), 9)

    def test_source_change_during_child_run_never_marks_stage_complete(self):
        source = ["a" * 64]
        def changed(*args):
            self.worker(*args)
            source[0] = "b" * 64
        with patch.object(WORKFLOW, "_source_sha256", lambda: source[0], create=True):
            with patch.object(WORKFLOW, "_run_command", changed, create=True):
                with self.assertRaisesRegex(ValueError, "source|changed"):
                    self.run_stage("datasets", scene="circle")
        records = list((self.root / "workflow/datasets/circle").glob("*/attempt.json"))
        self.assertEqual(json.loads(records[0].read_text())["status"], "failed")

    def test_training_cannot_reinterpret_dataset_after_frozen_seed_design_changes(self):
        self.assertEqual(self.run_stage("datasets")["status"], "complete")
        self.plan["seed_families"]["train"] = [13, 14]
        self.write(self.root / "plan/design.json", self.plan)
        with self.assertRaisesRegex(ValueError, "design|identity|changed"):
            self.run_stage("train", training_config=self.config)
        self.assertEqual(len(self.calls), 3)

    def test_sampling_revision_builds_new_dataset_without_overwriting_prior_evidence(self):
        first = self.run_stage("datasets")
        old = {scene: Path(value["dataset_manifest"])
               for scene, value in first["products"].items()}
        hashes = {scene: self.sha(path) for scene, path in old.items()}
        self.plan["sampling_revisions"] = [{"reason": "declared coverage extension"}]
        self.write(self.root / "plan/design.json", self.plan)
        second = self.run_stage("datasets")
        self.assertEqual(len(self.calls), 6, "a new sampling revision must rebuild datasets")
        for scene, value in second["products"].items():
            new = Path(value["dataset_manifest"])
            self.assertNotEqual(new, old[scene])
            self.assertIn("datasets-revision-001", str(new))
            self.assertEqual(self.sha(old[scene]), hashes[scene])
            selected = WORKFLOW._completed(self.root, "datasets", scene, self.plan)
            self.assertEqual(selected["products"]["dataset_manifest"], str(new))

    def test_rendering_with_one_missing_numbered_figure_fails_without_overwriting(self):
        self.formal()
        self.assertEqual(self.run_stage("evaluate")["status"], "complete")
        def missing(*args):
            self.worker(*args)
            command = args[0]
            if Path(command[1]).name == "plot_campaign.py":
                folder = Path(command[command.index("--output-dir") + 1])
                path = folder / "figure-index.json"
                value = json.loads(path.read_text())
                value["figures"].pop()
                self.write(path, value)
        with patch.object(WORKFLOW, "_run_command", missing):
            with self.assertRaisesRegex(ValueError, "30"):
                self.run_stage("figures")
        record = next((self.root / "workflow/figures/all").glob("*/attempt.json"))
        self.assertEqual(json.loads(record.read_text())["status"], "failed")

    def test_training_never_accepts_checkpoint_selected_outside_declared_candidates(self):
        self.assertEqual(self.run_stage("datasets")["status"], "complete")
        def mismatched(*args):
            self.worker(*args)
            command = args[0]
            if Path(command[1]).name == "train_tkan_lstm.py":
                folder = Path(command[command.index("--output-root") + 1])
                path = next(folder.glob("*/model-manifest.json"))
                value = json.loads(path.read_text())
                value["selected_seed"] = 999
                self.write(path, value)
        with patch.object(WORKFLOW, "_run_command", mismatched):
            with self.assertRaisesRegex(ValueError, "selected"):
                self.run_stage("train", scene="circle", training_config=self.config)

    def test_completed_evaluation_and_figures_resume_without_executing_children(self):
        self.formal()
        self.assertEqual(self.run_stage("evaluate")["status"], "complete")
        self.assertEqual(self.run_stage("figures")["status"], "complete")
        self.assertEqual(self.run_stage("evaluate")["status"], "complete")
        self.assertEqual(self.run_stage("figures")["status"], "complete")
        self.assertEqual(len(self.calls), 11)

    def test_workflow_does_not_freeze_campaign_or_launch_simulations(self):
        before = (self.root / "plan/design.json").read_bytes()
        self.train()
        self.assertEqual((self.root / "plan/design.json").read_bytes(), before)
        self.assertFalse(any(Path(cmd[1]).name in ("campaign.py", "run_experiment.py")
                             for cmd in self.calls))

    def test_evaluation_rechecks_external_frozen_training_configuration(self):
        self.formal()
        self.write(self.config, {"initialization_seeds": [101, 102, 103], "epochs": 2})
        with self.assertRaisesRegex(ValueError, "hash|changed"):
            self.run_stage("evaluate")
        self.assertEqual(len(self.calls), 6)

    def test_formal_bootstrap_resamples_cannot_be_silently_reduced(self):
        self.formal()
        self.plan["bootstrap"]["resamples"] = 9
        self.write(self.root / "plan/design.json", self.plan)
        with self.assertRaisesRegex(ValueError, "10000|bootstrap"):
            self.run_stage("evaluate")

    def test_disk_reserve_stops_before_starting_an_output_attempt(self):
        self.plan["minimum_free_disk_bytes"] = 100
        self.write(self.root / "plan/design.json", self.plan)
        with patch.object(WORKFLOW, "_free_disk_bytes", return_value=99, create=True):
            with self.assertRaisesRegex(ValueError, "disk"):
                self.run_stage("datasets", scene="circle")
        self.assertEqual(self.calls, [])

    def test_interruption_records_failed_attempt_and_preserves_partial_output(self):
        def interrupt(command, log_path, timeout):
            Path(log_path).write_text("partial child evidence")
            raise KeyboardInterrupt("fixture interrupt")
        with patch.object(WORKFLOW, "_run_command", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_stage("datasets", scene="circle")
        path = next((self.root / "workflow/datasets/circle").glob("*/attempt.json"))
        self.assertEqual(json.loads(path.read_text())["status"], "failed")
        self.assertEqual((path.parent / "build.log").read_text(), "partial child evidence")

    def test_live_child_from_interrupted_attempt_blocks_retry(self):
        with patch.object(WORKFLOW, "_run_command", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_stage("datasets", scene="circle")
        path = next((self.root / "workflow/datasets/circle").glob("*/attempt.json"))
        record = json.loads(path.read_text())
        record["status"] = "running"
        WORKFLOW._save_attempt(path.parent, record)
        self.write(path.parent / "build.process.json",
                   dict(pid=os.getpid(), start_token=WORKFLOW._process_token(os.getpid())))
        with self.assertRaisesRegex(ValueError, "live owned child"):
            self.run_stage("datasets", scene="circle")
        self.assertEqual(self.calls, [])

    def test_empty_attempt_after_directory_creation_is_preserved_and_recovered(self):
        abandoned = self.root / "workflow/datasets/circle/attempt-001"
        abandoned.mkdir(parents=True)
        (abandoned / "unexpected.tmp").write_text("interrupted creation")
        try:
            result = self.run_stage("datasets", scene="circle")
        except ValueError as error:
            result = dict(status="unrecoverable", error=str(error))
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual((abandoned / "unexpected.tmp").read_text(), "interrupted creation")
        self.assertEqual(json.loads((abandoned / "recovery.json").read_text())["status"], "failed")
        self.assertTrue((abandoned.parent / "attempt-002/attempt.json").is_file())

    def test_unregistered_orphan_is_detected_from_durable_launch_token(self):
        abandoned = self.root / "workflow/datasets/circle/attempt-001"
        abandoned.mkdir(parents=True)
        token = "workflow-unit-test-unregistered-child"
        self.write(abandoned / "build.launch.json", {"token": token})
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env=dict(os.environ, VNDN_WORKFLOW_CHILD_TOKEN=token), start_new_session=True)
        try:
            with self.assertRaisesRegex(ValueError, "live owned child"):
                self.run_stage("datasets", scene="circle")
            self.assertEqual(self.calls, [])
        finally:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


class RealChildTests(unittest.TestCase):
    def test_real_child_failure_is_not_success_and_retains_output(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "command.log"
            with self.assertRaisesRegex(RuntimeError, "exit 7"):
                WORKFLOW._run_command([sys.executable, "-c",
                                       "print('failure evidence', flush=True); raise SystemExit(7)"],
                                      log, 10)
            self.assertIn("failure evidence", log.read_text())
            self.assertTrue(log.with_suffix(".process.json").is_file())
            record = json.loads(log.with_suffix(".process.json").read_text())
            self.assertEqual(record.get("returncode"), 7)
            self.assertIn("finished_utc", record)

    def test_real_child_receives_resource_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "command.log"
            WORKFLOW._run_command([sys.executable, "-c",
                                   "import os; print(os.environ['JOBS']); "
                                   "print(os.environ['OMP_NUM_THREADS'])"], log, 10)
            self.assertEqual(log.read_text().splitlines(), ["4", "1"])
            self.assertEqual(json.loads(log.with_suffix(".process.json").read_text()).get(
                "returncode"), 0)

    def test_timeout_reaps_owned_process_group_and_preserves_log(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "command.log"
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                WORKFLOW._run_command(
                    [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)"],
                    log, .2)
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(log.read_text().strip(), "started")
            pid = json.loads(log.with_suffix(".process.json").read_text())["pid"]
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_metadata_write_failure_after_popen_reaps_the_launched_child(self):
        native_popen = subprocess.Popen
        native_write = WORKFLOW.write_json
        children = []
        def capture(*args, **kwargs):
            process = native_popen(*args, **kwargs)
            children.append(process)
            return process
        def broken(path, value):
            if str(path).endswith(".process.json"):
                raise OSError("fixture metadata write failed")
            return native_write(path, value)
        with tempfile.TemporaryDirectory() as temp:
            try:
                with patch.object(WORKFLOW.subprocess, "Popen", side_effect=capture):
                    with patch.object(WORKFLOW, "write_json", side_effect=broken):
                        with self.assertRaisesRegex(OSError, "metadata write"):
                            WORKFLOW._run_command(
                                [sys.executable, "-c", "import time; time.sleep(60)"],
                                Path(temp) / "command.log", 10)
                self.assertIsNotNone(children[0].poll(), "child leaked outside cleanup try/finally")
            finally:
                for child in children:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()

    def test_signal_during_popen_registration_and_repeated_during_cleanup_cannot_leak(self):
        native_popen = subprocess.Popen
        children = []
        def interrupted_registration(*args, **kwargs):
            process = native_popen(*args, **kwargs)
            children.append(process)
            native_wait = process.wait
            def interrupted_cleanup(*args, **kwargs):
                os.kill(os.getpid(), signal.SIGTERM)
                os.kill(os.getpid(), signal.SIGTERM)
                return native_wait(*args, **kwargs)
            process.wait = interrupted_cleanup
            os.kill(os.getpid(), signal.SIGTERM)
            return process
        with tempfile.TemporaryDirectory() as temp:
            try:
                with patch.object(WORKFLOW.subprocess, "Popen",
                                  side_effect=interrupted_registration):
                    with self.assertRaises(KeyboardInterrupt):
                        WORKFLOW._run_command(
                            [sys.executable, "-c", "import time; time.sleep(60)"],
                            Path(temp) / "command.log", 10)
                self.assertIsNotNone(children[0].poll())
            finally:
                for process in children:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        subprocess.Popen.wait(process)


class RealTrainingPipelineTests(unittest.TestCase):
    def test_three_scenes_real_builder_training_and_independent_evaluation_clis(self):
        """Nine real subprocesses; tiny synthetic records, one epoch, no SUMO."""
        support = WORKFLOW._module(
            "_workflow_formal_fixtures", WORKFLOW.AI_ROOT / "tests/formal_test_support.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "campaign"
            plan = WORKFLOW.campaign.make_plan("real-cli-validation")
            plan.update(status="development-frozen", source_sha256="a" * 64,
                        validation_only=True)
            plan["conditions"] = plan["conditions"][:1]
            plan["scans"] = {name: ["baseline"] for name in plan["scans"]}
            plan["seed_families"] = {"pilot": [1, 2], "train": [11, 12],
                                     "validation": [21, 22], "evaluation": [31, 32],
                                     "test": [41, 42]}
            WORKFLOW.campaign.initialize(root, plan)
            exports = {}
            for split in ("train", "validation", "evaluation"):
                rows = []
                for job in WORKFLOW.campaign.jobs_for(plan, split):
                    run = support.fixture_run(root / "raw", job["job_id"], job["scene"],
                                              offset=job["seed_family"], seed=job["seed_family"])
                    rows.append(dict(job, path=str(run),
                                     manifest_sha256=support.sha(run / "manifest.json")))
                exports[split] = rows
            config = root / "training-config.json"
            WORKFLOW.write_json(config, dict(
                initialization_seeds=[101, 102, 103], epochs=1, patience=1,
                hidden_size=4, grid_size=3, spline_order=2, batch_size=16))
            options = dict(root=root, python=sys.executable, model_root=root / "models",
                           allow_validation_only=True, timeout=120)
            with patch.object(WORKFLOW, "_source_sha256", return_value="a" * 64):
                with patch.object(WORKFLOW, "_export_runs",
                                  side_effect=lambda root, split: exports[split]):
                    try:
                        self.assertEqual(WORKFLOW.execute(stage="datasets", **options)["status"],
                                         "complete")
                        trained = WORKFLOW.execute(stage="train", training_config=config, **options)
                        self.assertEqual(trained["status"], "complete")
                        for scene, result in trained["products"].items():
                            model = WORKFLOW.read_json(Path(result["model_manifest"]))
                            self.assertEqual(len(model["candidates"]), 3)
                            self.assertFalse(model["evaluation_opened"])
                            plan["models"][scene] = dict(path=result["checkpoint_path"],
                                                        sha256=result["checkpoint_sha256"])
                        # Test explicitly simulates root's separate P4 gate, never workflow.
                        plan["status"] = "formal-frozen"
                        WORKFLOW.write_json(root / "plan/design.json", plan)
                        evaluated = WORKFLOW.execute(stage="evaluate", **options)
                        self.assertEqual(evaluated["status"], "complete")
                        for scene, result in evaluated["products"].items():
                            value = WORKFLOW.read_json(Path(result["evaluation"]))
                            self.assertEqual(value["bootstrap"]["repetitions"], 10000)
                            self.assertEqual(value["bootstrap"]["independent_seed_count"], 2)
                            self.assertEqual(value["split"], "evaluation")
                            self.assertTrue(value["validation_only"])
                            classes = 2 if scene == "circle" else 7
                            self.assertEqual(len(value["confusion_matrix"]), classes)
                    except Exception as error:
                        logs = "\n".join(str(path) + ":\n" + path.read_text()[-1500:]
                                         for path in (root / "workflow").glob("**/*.log"))
                        raise AssertionError(str(error) + "\n" + logs) from error


if __name__ == "__main__":
    unittest.main()
