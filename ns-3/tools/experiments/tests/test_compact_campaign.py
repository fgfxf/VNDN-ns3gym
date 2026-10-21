"""Compact study design, bounded additions, and actual 25-figure rendering."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaign_test_support import create_campaign, dump


DIRECTORY = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location("compact_" + name, DIRECTORY / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


campaign = module("campaign")
aggregate = module("aggregate_campaign")
plot = module("plot_campaign")
PROFILE = "compact-exploratory-v1"


def compact():
    return campaign.make_plan("compact-test", profile=PROFILE)


class CompactDesignTest(unittest.TestCase):
    def test_formal_jobs_begin_with_three_scene_baseline_then_follow_seed_batches(self):
        plan = compact()
        jobs = campaign.jobs_for(plan, "test")
        expected = [(seed, cid, scene, strategy)
                    for seed in range(51001, 51006)
                    for cid in ["baseline"] + [row["id"] for row in plan["conditions"]
                                               if row["id"] != "baseline"]
                    for scene in campaign.SCENES for strategy in range(4)]
        actual = [(job["seed_family"], job["condition_id"], job["scene"], job["strategy"])
                  for job in jobs]
        self.assertEqual(actual[:12], [(51001, "baseline", scene, strategy)
                                      for scene in campaign.SCENES for strategy in range(4)])
        self.assertEqual(actual, expected)
        old = campaign.jobs_for(campaign.make_plan("full-order"), "test")
        self.assertTrue(all(job["scene"] == "circle" and job["condition_id"] == "baseline"
                            for job in old[:80]))

    def test_exact_eight_conditions_48_sparse_samples_and_480_paired_runs(self):
        plan = compact()
        self.assertEqual(plan["design_profile"], PROFILE)
        self.assertEqual([len(plan["scans"][s]) for s in ("interest", "speed", "vehicles")],
                         [3, 3, 4])
        self.assertNotIn("vehicles_fixed_k", plan["scans"])
        parameters = {(c["vehicles"], c["speed_kmh"], c["requests"]) for c in plan["conditions"]}
        self.assertEqual(parameters, {(10, 30, 15000), (10, 30, 3750), (10, 30, 30000),
                                     (10, 10, 15000), (10, 50, 15000), (5, 30, 7500),
                                     (15, 30, 22500), (20, 30, 30000)})
        sampled = []
        for split, expected in (("train", 24), ("validation", 12), ("evaluation", 12)):
            jobs = campaign.jobs_for(plan, split)
            self.assertEqual(len(jobs), expected)
            self.assertTrue(all(job["strategy"] == 0 for job in jobs))
            sampled.extend(jobs)
        self.assertEqual(len({j["seed_family"] for j in sampled}), 48)
        self.assertEqual(len({j["job_id"] for j in sampled}), 48)
        formal = campaign.jobs_for(plan, "test")
        self.assertEqual(len(formal), 480)
        self.assertEqual({j["seed_family"] for j in formal}, set(range(51001, 51006)))
        for scene in campaign.SCENES:
            for cid in (c["id"] for c in plan["conditions"]):
                selected = [j for j in formal if (j["scene"], j["condition_id"]) == (scene, cid)]
                self.assertEqual(len(selected), 20)
        self.assertEqual(len(plan["figure_ids"]), 25)

    def test_validation_and_evaluation_cover_only_the_declared_four_conditions(self):
        plan = compact()
        lookup = {c["id"]: (c["vehicles"], c["speed_kmh"], c["requests"])
                  for c in plan["conditions"]}
        expected = {(10, 30, 15000), (10, 10, 15000), (10, 50, 15000), (20, 30, 30000)}
        for split in ("validation", "evaluation"):
            for scene in campaign.SCENES:
                rows = [j for j in campaign.jobs_for(plan, split) if j["scene"] == scene]
                self.assertEqual({lookup[j["condition_id"]] for j in rows}, expected)

    def test_bad_sparse_identity_or_seed_leak_cannot_be_executed(self):
        for mutate in (
                lambda p: p["sampling_jobs"]["train"].pop(),
                lambda p: p["sampling_jobs"]["train"][0].update(scene="unknown"),
                lambda p: p["sampling_jobs"]["train"][0].update(condition_id="unknown"),
                lambda p: p["sampling_jobs"]["validation"][0].update(seed_family=21001),
                lambda p: p["seed_families"]["evaluation"].append(21001)):
            plan = compact()
            mutate(plan)
            with self.assertRaises(ValueError):
                campaign.jobs_for(plan, "train")

    def test_sampling_assignment_and_figure_declaration_are_frozen(self):
        original = compact()
        changed = copy.deepcopy(original)
        first, second = changed["sampling_jobs"]["train"][:2]
        first["condition_id"], second["condition_id"] = second["condition_id"], first["condition_id"]
        self.assertNotEqual(campaign.execution_identity(original, "train"),
                            campaign.execution_identity(changed, "train"))
        changed = copy.deepcopy(original)
        changed["figure_ids"].pop()
        with self.assertRaises(ValueError):
            campaign.jobs_for(changed, "test")

    def test_compact_profile_does_not_silently_change_the_approved_window(self):
        with self.assertRaises(ValueError):
            campaign.make_plan("changed-window", duration=120, profile=PROFILE)

    def test_only_append_new_sampling_jobs_bounded_to_24_and_eight_per_scene(self):
        plan = compact()
        old_test = campaign.execution_identity(plan, "test")
        additions = [dict(split="train", scene=scene, condition_id="baseline",
                          seed_family=22001 + index * 8 + offset)
                     for index, scene in enumerate(campaign.SCENES) for offset in range(8)]
        revised = campaign.extend_sampling_plan(plan, additions, "missing class coverage")
        self.assertEqual(sum(len(revised["sampling_jobs"][s]) for s in
                             ("train", "validation", "evaluation")), 72)
        self.assertEqual(old_test, campaign.execution_identity(revised, "test"))
        for split in ("train", "validation", "evaluation"):
            self.assertEqual(revised["sampling_jobs"][split][:len(plan["sampling_jobs"][split])],
                             plan["sampling_jobs"][split])
        self.assertEqual(len(revised["sampling_revisions"]), 1)
        for extra in (additions[:1], [dict(split="train", scene="circle", condition_id="baseline",
                                           seed_family=22090)]):
            with self.assertRaises(ValueError):
                campaign.extend_sampling_plan(revised, extra, "additional coverage")
        self.assertEqual(sum(len(plan["sampling_jobs"][s]) for s in plan["sampling_jobs"]), 48)

    def test_additions_reject_wrong_split_reused_seeds_and_missing_reason(self):
        item = dict(split="train", scene="circle", condition_id="baseline", seed_family=22001)
        for row, reason in ((dict(item, split="test"), "coverage"),
                            (dict(item, seed_family=31001), "coverage"),
                            (dict(item, condition_id="unknown"), "coverage"), (item, "")):
            with self.assertRaises(ValueError):
                campaign.extend_sampling_plan(compact(), [row], reason)

    def test_disk_revision_keeps_existing_failed_attempts_and_requires_matching_old_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = compact()
            plan.update(status="development-frozen", source_sha256="a" * 64)
            campaign.initialize(root, plan)
            job = campaign.jobs_for(plan, "train")[0]
            old_job = dict(job, status="failed", attempts=[dict(attempt=1, status="failed",
                                                               error="preserve evidence")])
            state = dict(schema_version=1, split="train", jobs={job["job_id"]: old_job},
                         execution_design_sha256=campaign.execution_identity(plan, "train"))
            state_path = root / "plan/state-train.json"
            dump(state_path, state)
            addition = dict(split="train", scene="circle", condition_id="baseline", seed_family=22001)
            with patch.object(campaign.runner, "source_snapshot", return_value={"sha256": "a" * 64}):
                revised = campaign.append_sampling_jobs(root, [addition], "missing class coverage")
            saved = json.loads(state_path.read_text())
            self.assertEqual(saved["jobs"], state["jobs"])
            self.assertEqual(saved["execution_design_sha256"],
                             campaign.execution_identity(revised, "train"))
            self.assertEqual(len(list((root / "plan/sampling-revisions").glob("*/revision.json"))), 1)
            saved["execution_design_sha256"] = "tampered"
            dump(state_path, saved)
            before = (root / "plan/design.json").read_bytes()
            with patch.object(campaign.runner, "source_snapshot", return_value={"sha256": "a" * 64}):
                with self.assertRaises(ValueError):
                    campaign.append_sampling_jobs(root, [dict(addition, seed_family=22002)], "coverage")
            self.assertEqual((root / "plan/design.json").read_bytes(), before)

    def test_additions_are_forbidden_after_model_work_begins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = compact()
            plan.update(status="development-frozen", source_sha256="a" * 64)
            campaign.initialize(root, plan)
            (root / "workflow/train/circle/attempt-001").mkdir(parents=True)
            with self.assertRaises(ValueError):
                campaign.append_sampling_jobs(root, [dict(split="train", scene="circle",
                    condition_id="baseline", seed_family=22001)], "coverage")

    def test_coverage_failure_can_append_without_modifying_old_dataset_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = compact()
            plan.update(status="development-frozen", source_sha256="a" * 64)
            campaign.initialize(root, plan)
            old = root / "workflow/datasets/circle/attempt-001"
            old.mkdir(parents=True)
            evidence = old / "attempt.json"
            evidence.write_text('{"status":"failed","error":"missing target class 5"}')
            before = evidence.read_bytes()
            with patch.object(campaign.runner, "source_snapshot", return_value={"sha256": "a" * 64}):
                revised = campaign.append_sampling_jobs(root, [dict(split="train", scene="circle",
                    condition_id="baseline", seed_family=22001)], "missing target class 5")
            self.assertEqual(evidence.read_bytes(), before)
            self.assertEqual(len(revised["sampling_revisions"]), 1)

    def test_interrupted_append_recovers_only_its_recorded_before_and_after_states(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = compact()
            plan.update(status="development-frozen", source_sha256="a" * 64)
            campaign.initialize(root, plan)
            original = campaign.runner.write_json

            def interrupt_commit(path, value):
                if Path(path) == root / "plan/design.json":
                    raise OSError("simulated interruption during commit")
                return original(path, value)

            addition = dict(split="train", scene="circle", condition_id="baseline", seed_family=22001)
            with patch.object(campaign.runner, "source_snapshot", return_value={"sha256": "a" * 64}):
                with patch.object(campaign.runner, "write_json", side_effect=interrupt_commit):
                    with self.assertRaisesRegex(OSError, "simulated interruption"):
                        campaign.append_sampling_jobs(root, [addition], "coverage")
                self.assertEqual(json.loads((root / "plan/design.json").read_text()), plan)
                recovered = campaign.recover_sampling_revision(root)
            self.assertEqual(len(campaign.jobs_for(recovered, "train")), 25)
            journal = next((root / "plan/sampling-revisions").glob("*/revision.json"))
            self.assertEqual(json.loads(journal.read_text())["status"], "complete")

    def test_no_build_command_is_forwarded_to_the_existing_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = compact()
            job = campaign.jobs_for(plan, "train")[0]
            process = unittest.mock.Mock(returncode=1)
            process.poll.return_value = 1
            with patch.object(campaign, "prepare_job_input", return_value=root / "config.json"), \
                    patch.object(campaign.subprocess, "Popen", return_value=process):
                result = campaign._run_job(root, plan, job, 1, no_build=True)
            self.assertIn("--no-build", result["command"])
            self.assertIn("--training-snapshots", result["command"])

    def test_append_rechecks_completed_manifest_and_current_input_seal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = compact()
            plan.update(status="development-frozen", source_sha256="a" * 64)
            campaign.initialize(root, plan)
            job = campaign.jobs_for(plan, "train")[0]
            run = root / "completed-run"
            run.mkdir()
            manifest = dict(status="complete", block_id=job["block_id"], scenario=job["scene"],
                            strategy=0, source={"sha256": "a" * 64}, input_hashes={"input": "sealed"})
            dump(run / "manifest.json", manifest)
            attempt = dict(attempt=1, status="complete", manifest_path=str(run / "manifest.json"),
                           manifest_sha256=campaign.digest(run / "manifest.json"))
            state = dict(schema_version=1, split="train", jobs={job["job_id"]:
                         dict(job, status="complete", attempts=[attempt])},
                         execution_design_sha256=campaign.execution_identity(plan, "train"))
            dump(root / "plan/state-train.json", state)
            addition = dict(split="train", scene="circle", condition_id="baseline", seed_family=22001)
            with patch.object(campaign.runner, "source_snapshot", return_value={"sha256": "a" * 64}), \
                    patch.object(campaign.runner.summary, "summarize_run", return_value={}) as verify, \
                    patch.object(campaign, "prepare_job_input", return_value=root / "config.json"), \
                    patch.object(campaign.runner, "prepare_inputs", return_value=({}, {"input": "changed"})):
                before = (root / "plan/design.json").read_bytes()
                with self.assertRaisesRegex(ValueError, "completed input"):
                    campaign.append_sampling_jobs(root, [addition], "coverage")
                verify.assert_called_once_with(run)
                self.assertEqual((root / "plan/design.json").read_bytes(), before)

    def test_invalid_scan_membership_cannot_survive_correct_point_counts(self):
        plan = compact()
        plan["scans"]["speed"][-1] = plan["scans"]["interest"][-1]
        with self.assertRaisesRegex(ValueError, "scan"):
            campaign.jobs_for(plan, "train")


class CompactAggregationTest(unittest.TestCase):
    def test_run_dispersion_keeps_the_weighted_rtt_point_and_zero_success_seed(self):
        def block(success, milliseconds):
            value = dict(generated=4, satisfied=success, sum_success_rtt_ns=milliseconds * 1000000,
                         network_l3_bytes=500, control_l3_bytes=20, extra_data_app_attempts=1)
            return {str(strategy): dict(value) for strategy in range(4)}
        result = aggregate.paired_statistics([block(1, 100), block(3, 900), block(0, 0)], 100, 7)
        rtt = result["metrics"]["mean_success_rtt_ms"]["0"]
        self.assertEqual(rtt["estimate"], 250)
        self.assertEqual(rtt["run_values"], [100., 300., None])
        self.assertEqual(rtt["run_defined"], 2)
        self.assertAlmostEqual(rtt["run_sd"], 200 / (2 ** .5))

    def formal_manifest(self):
        plan = compact()
        value = dict(plan, repetitions=plan["seed_families"]["test"], source_sha256="a" * 64,
                     models={s: {} for s in campaign.SCENES},
                     model_evaluations={s: {} for s in campaign.SCENES}, blocks=[])
        blocks = {}
        for job in campaign.jobs_for(plan, "test"):
            block = blocks.setdefault(job["block_id"], dict(scene=job["scene"],
                condition_id=job["condition_id"], seed_family=job["seed_family"],
                block_id=job["block_id"], runs={}))
            block["runs"][str(job["strategy"])] = dict(path="/fixture/" + job["job_id"],
                                                      manifest_sha256="b" * 64)
        value["blocks"] = list(blocks.values())
        return value

    def test_real_compact_design_is_accepted_without_validation_only_bypass(self):
        value = self.formal_manifest()
        self.assertFalse(value["validation_only"])
        conditions, blocks = aggregate.validate_campaign(value)
        self.assertEqual(len(conditions), 8)
        self.assertEqual(len(blocks), 120)
        self.assertEqual(value["figure_ids"], aggregate.expected_figure_ids(value["scans"]))

    def test_formal_compact_refuses_missing_blocks_wrong_repetitions_and_range(self):
        for mutate in (lambda v: v["blocks"].pop(),
                       lambda v: v["repetitions"].pop(),
                       lambda v: v["conditions"][-1].update(vehicles=40),
                       lambda v: v["figure_ids"].pop(),
                       lambda v: v["blocks"][0]["runs"].pop("2")):
            value = self.formal_manifest()
            mutate(value)
            with self.assertRaises(ValueError):
                aggregate.validate_campaign(value)

    def test_three_scans_render_exact_25_images_with_old_style_data_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = create_campaign(root / "input")
            value = json.loads(manifest.read_text())
            value["design_profile"] = PROFILE
            del value["scans"]["vehicles_fixed_k"]
            value["figure_ids"] = aggregate.expected_figure_ids(value["scans"])
            dump(manifest, value)
            result = aggregate.aggregate_campaign(manifest, root / "analysis")
            self.assertEqual(result["design_profile"], PROFILE)
            figures = plot.plot_campaign(root / "analysis", root / "figures")
            self.assertEqual({r["id"] for r in figures["figures"]}, set(value["figure_ids"]))
            self.assertEqual(len(figures["figures"]), 25)
            self.assertEqual(sum(r["kind"] == "scan" for r in figures["figures"]), 15)
            for record in figures["figures"]:
                for suffix in ("pdf", "svg", "png"):
                    self.assertGreater((root / "figures" / record["files"][suffix]).stat().st_size, 100)
                if record["kind"] == "scan":
                    self.assertIn("sample standard deviation", record["caption_en"])
                    self.assertIn("not a confidence interval", record["caption_en"])
            self.assertTrue(figures["validation_only"])


if __name__ == "__main__":
    unittest.main()
