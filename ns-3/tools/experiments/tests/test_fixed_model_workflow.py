"""Fixed historic models skip development while preserving figure-stage integrity."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_campaign_workflow import WORKFLOW


SCENES = ("circle", "grid", "spidermap")
SEEDS = {"circle": [23001, 23002], "grid": [23009, 23010],
         "spidermap": [23017, 23018]}
METRICS = ("isr_percent", "mean_success_rtt_ms", "network_mbit",
           "control_mbit", "extra_data_app_attempts")
FIGURE_IDS = ["F{:02d}-{}-{}".format(1 + i * 5 + j, axis, metric)
              for i, axis in enumerate(("interest", "speed", "vehicles"))
              for j, metric in enumerate(METRICS)]
FIGURE_IDS += ["F{:02d}-{}-rtt-3d".format(21 + i, scene) for i, scene in enumerate(SCENES)]
FIGURE_IDS += ["F{:02d}-{}-rtt-box".format(24 + i, scene) for i, scene in enumerate(SCENES)]
FIGURE_IDS += ["F27-baseline-total-traffic"]
DIAGNOSTICS = ["D01-circle-rtt-ecdf", "D02-grid-rtt-ecdf", "D03-spidermap-rtt-ecdf",
               "D04-extra-submission-decomposition", "D05-control-traffic-decomposition",
               "D06-mobility-coverage"]


class FixedModelWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        conditions = [{"id": "c{}".format(i), "vehicles": 10,
                       "speed_kmh": 30, "requests": 6000} for i in range(11)]
        self.plan = dict(schema_version=1, campaign_id="fixed-workflow-fixture",
                         status="formal-frozen", validation_only=True,
                         design_profile="quick-fixed-model-v1", source_sha256="a" * 64,
                         conditions=conditions, baseline_condition_id="c0",
                         measurement_start=20, measurement_duration=120, drain_seconds=3.5,
                         scans={axis: ["c0"] for axis in ("interest", "speed", "vehicles")},
                         figure_ids=list(FIGURE_IDS), test_seeds_by_scene=copy.deepcopy(SEEDS),
                         seed_families={"pilot": [], "train": [], "validation": [], "evaluation": [],
                                        "test": sorted(seed for seeds in SEEDS.values() for seed in seeds)},
                         sampling_jobs={split: [] for split in ("train", "validation", "evaluation")},
                         models={}, timeouts={"default": 100}, time_bin_seconds=5,
                         bootstrap={"resamples": 10000, "seed": 61021})
        self.dependencies = {}
        for scene in SCENES:
            checkpoint = self.root / "history" / scene / "checkpoint.pt"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_bytes(("fixture-" + scene).encode())
            self.dependencies[str(checkpoint)] = WORKFLOW.digest(checkpoint)
            self.plan["models"][scene] = dict(path=str(checkpoint), sha256=WORKFLOW.digest(checkpoint))
        provenance = self.root / "history" / "design.json"
        self.write(provenance, {"source_sha256": "b" * 64})
        self.dependencies[str(provenance)] = WORKFLOW.digest(provenance)
        self.plan["external_models"] = dict(
            schema_version=1, source_root=str(self.root / "history"),
            source_design={"path": str(provenance), "sha256": WORKFLOW.digest(provenance)},
            training_source_sha256="b" * 64, runtime_source_sha256="a" * 64,
            seed_policy="training-seed-reuse-exploratory", dependencies=self.dependencies)
        self.jobs = []
        self.exports = []
        for scene in SCENES:
            for condition in conditions:
                for seed in SEEDS[scene]:
                    block = "test-{}-{}-s{}".format(scene, condition["id"], seed)
                    for strategy in range(4):
                        job = dict(job_id=block + "-a" + str(strategy), block_id=block,
                                   split="test", scene=scene, condition_id=condition["id"],
                                   seed_family=seed, strategy=strategy)
                        self.jobs.append(job)
                        folder = self.root / "runs" / job["job_id"]
                        self.write(folder / "manifest.json", {"fixture": job["job_id"]})
                        self.exports.append(dict(job, path=str(folder),
                                                 manifest_sha256=WORKFLOW.digest(folder / "manifest.json")))
        self.save_plan()
        replacements = [(WORKFLOW, "_source_sha256", lambda: "a" * 64),
                        (WORKFLOW, "_export_runs", lambda root, split: copy.deepcopy(self.exports)),
                        (WORKFLOW, "_run_command", self.worker),
                        (WORKFLOW.campaign, "check_external_models", self.external_check),
                        (WORKFLOW.campaign, "jobs_for", lambda plan, split: self.jobs if split == "test" else []),
                        (WORKFLOW.campaign, "execution_identity",
                         lambda plan, split: WORKFLOW._hash_object(dict(
                             split=split, source=plan["source_sha256"],
                             seeds=plan.get("test_seeds_by_scene"), models=plan["models"])))]
        for target, name, value in replacements:
            mocked = patch.object(target, name, value, create=True)
            mocked.start()
            self.addCleanup(mocked.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def save_plan(self):
        self.write(self.root / "plan/design.json", self.plan)

    def external_check(self, plan):
        for path, expected in plan["external_models"]["dependencies"].items():
            WORKFLOW._check_file(path, expected)
        return dict(plan["external_models"]["dependencies"])

    def worker(self, command, log_path, timeout):
        self.calls.append(command)
        Path(log_path).write_text("synthetic validation-only artifact worker\n")
        output = Path(command[command.index("--output-dir") + 1])
        output.mkdir()
        common = dict(schema_version=1, status="complete", validation_only=True,
                      campaign_id=self.plan["campaign_id"])
        if Path(command[1]).name == "aggregate_campaign.py":
            self.write(output / "aggregate.json", dict(common, campaign_sha256=WORKFLOW.digest(command[2])))
        elif Path(command[1]).name == "plot_campaign.py":
            items = []
            for identity in FIGURE_IDS + DIAGNOSTICS:
                files = {}
                for extension in ("pdf", "svg", "png"):
                    name = identity + "." + extension
                    (output / name).write_bytes(b"synthetic-contract-artifact")
                    files[extension] = name
                items.append(dict(id=identity, files=files,
                                  sha256={ext: WORKFLOW.digest(output / name)
                                          for ext, name in files.items()}))
            self.write(output / "figure-index.json", dict(
                common, analysis_sha256=WORKFLOW.digest(Path(command[2]) / "aggregate.json"),
                figures=items[:22], diagnostics=items[22:]))
        else:
            self.fail("fixed model workflow must not invoke development: " + str(command))

    def run_figures(self):
        return WORKFLOW.execute(self.root, "figures", python=sys.executable,
                                allow_validation_only=True)

    def test_all_264_runs_generate_22_plus_6_figures_without_development(self):
        self.assertEqual(len(self.exports), 264)
        result = self.run_figures()
        self.assertEqual(result["status"], "complete")
        self.assertEqual([Path(command[1]).name for command in self.calls],
                         ["aggregate_campaign.py", "plot_campaign.py"])
        products = result["products"]["all"]
        manifest = json.loads(Path(products["campaign_manifest"]).read_text())
        self.assertEqual(len(manifest["blocks"]), 66)
        self.assertTrue(all(set(block["runs"]) == {"0", "1", "2", "3"}
                            for block in manifest["blocks"]))
        self.assertEqual(manifest["test_seeds_by_scene"], SEEDS)
        self.assertEqual(manifest["external_models"], self.plan["external_models"])
        self.assertEqual(manifest["model_evaluations"], {})
        self.assertTrue(manifest["skip_training_figures"])
        attempt = WORKFLOW._record(Path(products["campaign_manifest"]).parent)
        self.assertTrue(self.dependencies.items() <= attempt["dependencies"].items())

    def test_fixed_models_reject_all_development_stages_before_creating_attempt(self):
        for stage in ("datasets", "train", "evaluate"):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "fixed.*figures|figures.*only"):
                WORKFLOW.execute(self.root, stage, allow_validation_only=True)
        self.assertFalse((self.root / "workflow").exists())

    def test_complete_figures_resume_without_repeating_children(self):
        first = self.run_figures()
        self.assertEqual(self.run_figures(), first)
        self.assertEqual(len(self.calls), 2)

    def test_missing_run_stops_before_any_aggregation(self):
        self.exports.pop()
        with self.assertRaisesRegex(ValueError, "complete split"):
            self.run_figures()
        self.assertEqual(self.calls, [])

    def test_wrong_scene_seed_is_rejected(self):
        self.exports[0]["seed_family"] = SEEDS["grid"][0]
        with self.assertRaisesRegex(ValueError, "identity"):
            self.run_figures()
        self.assertEqual(self.calls, [])

    def test_changed_historical_dependency_rejects_completed_reuse(self):
        self.run_figures()
        path = Path(self.plan["external_models"]["source_design"]["path"])
        path.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.run_figures()
        self.assertEqual(len(self.calls), 2)

    def test_history_change_during_worker_cannot_complete(self):
        def change(command, log_path, timeout):
            self.worker(command, log_path, timeout)
            Path(self.plan["models"]["circle"]["path"]).write_bytes(b"changed")
        with patch.object(WORKFLOW, "_run_command", change), self.assertRaisesRegex(ValueError, "hash changed"):
            self.run_figures()
        attempt = next((self.root / "workflow/figures/all").glob("*/attempt.json"))
        self.assertEqual(json.loads(attempt.read_text())["status"], "failed")

    def test_missing_diagnostic_rejects_completed_claim(self):
        def remove(command, log_path, timeout):
            self.worker(command, log_path, timeout)
            if Path(command[1]).name == "plot_campaign.py":
                path = Path(command[command.index("--output-dir") + 1]) / "figure-index.json"
                index = json.loads(path.read_text())
                index["diagnostics"].pop()
                self.write(path, index)
        with patch.object(WORKFLOW, "_run_command", remove), self.assertRaisesRegex(ValueError, "diagnostic"):
            self.run_figures()

    def test_mutated_external_provenance_changes_completed_stage_identity(self):
        self.run_figures()
        self.plan["external_models"]["seed_policy"] = "invented-policy"
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "identity|design|changed"):
            self.run_figures()
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
