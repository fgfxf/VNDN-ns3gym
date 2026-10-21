"""The 120-second first-draft campaign keeps a fixed, explicit sampling budget."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "quick_campaign", Path(__file__).resolve().parents[1] / "campaign.py")
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)
PROFILE = "quick-draft-v1"


def quick():
    return campaign.make_plan("quick-test", profile=PROFILE)


class QuickCampaignTest(unittest.TestCase):
    def test_default_window_scales_requests_without_increasing_vehicle_frequency(self):
        plan = quick()
        self.assertEqual(campaign.QUICK_PROFILE, PROFILE)
        self.assertEqual(plan["design_profile"], PROFILE)
        self.assertEqual((plan["measurement_start"], plan["measurement_duration"],
                          plan["drain_seconds"]), (20, 120, 3.5))
        parameters = {(c["vehicles"], c["speed_kmh"], c["requests"])
                      for c in plan["conditions"]}
        self.assertEqual(parameters, {(10, 30, 6000), (10, 30, 1500), (10, 30, 12000),
                                     (10, 10, 6000), (10, 50, 6000), (5, 30, 3000),
                                     (15, 30, 9000), (20, 30, 12000)})
        index = {row["id"]: row for row in plan["conditions"]}
        self.assertEqual([index[cid]["requests"] for cid in plan["scans"]["interest"]],
                         [1500, 6000, 12000])
        self.assertEqual([index[cid]["speed_kmh"] for cid in plan["scans"]["speed"]],
                         [10, 30, 50])
        for cid in plan["scans"]["vehicles"]:
            row = index[cid]
            self.assertEqual(row["requests"] / row["vehicles"] / 120, 5)
        self.assertEqual([identifier.split("-", 1)[0] for identifier in plan["figure_ids"]],
                         ["F{:02d}".format(i) for i in list(range(1, 16)) + list(range(21, 31))])
        self.assertEqual(plan["figure_ids"], campaign.make_plan(
            "prior-figures", profile=campaign.COMPACT_PROFILE)["figure_ids"])

    def test_sampling_is_48_explicit_runs_with_disjoint_seed_domains(self):
        plan = quick()
        expected = {"train": (24, 23001), "validation": (12, 33001),
                    "evaluation": (12, 43001)}
        all_jobs = []
        index = {row["id"]: (row["vehicles"], row["speed_kmh"], row["requests"])
                 for row in plan["conditions"]}
        representatives = {(10, 30, 6000), (10, 10, 6000), (10, 50, 6000), (20, 30, 12000)}
        for split, (count, start) in expected.items():
            jobs = campaign.jobs_for(plan, split)
            self.assertEqual(len(jobs), count)
            self.assertEqual([row["seed_family"] for row in jobs], list(range(start, start + count)))
            self.assertEqual({row["strategy"] for row in jobs}, {0})
            for scene in campaign.SCENES:
                rows = [row for row in jobs if row["scene"] == scene]
                self.assertEqual(len(rows), count // 3)
                self.assertEqual({index[row["condition_id"]] for row in rows},
                                 set(index.values()) if split == "train" else representatives)
            all_jobs.extend(jobs)
        self.assertEqual(len({row["job_id"] for row in all_jobs}), 48)
        quick_seeds = {seed for values in plan["seed_families"].values() for seed in values}
        self.assertEqual(len(quick_seeds), sum(map(len, plan["seed_families"].values())))
        for profile in ("full", campaign.COMPACT_PROFILE):
            prior = campaign.make_plan("prior", profile=profile)
            prior_seeds = {seed for values in prior["seed_families"].values() for seed in values}
            self.assertFalse(quick_seeds & prior_seeds)

    def test_192_formal_runs_are_paired_and_start_with_all_three_baselines(self):
        plan = quick()
        jobs = campaign.jobs_for(plan, "test")
        self.assertEqual(len(jobs), 192)
        self.assertEqual(plan["seed_families"]["test"], [52001, 52002])
        expected = [(seed, cid, scene, strategy)
                    for seed in (52001, 52002)
                    for cid in ["baseline"] + [row["id"] for row in plan["conditions"]
                                               if row["id"] != "baseline"]
                    for scene in campaign.SCENES for strategy in range(4)]
        actual = [(row["seed_family"], row["condition_id"], row["scene"], row["strategy"])
                  for row in jobs]
        self.assertEqual(actual, expected)
        self.assertEqual(actual[:12], [(52001, "baseline", scene, strategy)
                                      for scene in campaign.SCENES for strategy in range(4)])
        blocks = {}
        for row in jobs:
            blocks.setdefault(row["block_id"], []).append(row["strategy"])
        self.assertEqual(len(blocks), 48)
        self.assertTrue(all(values == [0, 1, 2, 3] for values in blocks.values()))

    def test_window_and_formal_seed_changes_are_rejected(self):
        for settings in ({"duration": 300}, {"duration": 90}, {"warmup": 10}, {"drain": 4}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                campaign.make_plan("wrong", profile=PROFILE, **settings)
        for mutate in (lambda p: p["conditions"][0].update(requests=15000),
                       lambda p: p["scans"]["speed"].reverse(),
                       lambda p: p["seed_families"]["test"].append(52003),
                       lambda p: p["seed_families"]["test"].__setitem__(0, 51001),
                       lambda p: p["figure_ids"].pop()):
            plan = quick()
            mutate(plan)
            with self.assertRaises(ValueError):
                campaign.jobs_for(plan, "test")

    def test_fixed_sampling_budget_cannot_be_removed_expanded_or_reassigned(self):
        plan = quick()
        self.assertEqual((plan["sampling_max_additional_jobs"],
                          plan["sampling_max_additional_per_scene"]), (0, 0))
        addition = dict(split="train", scene="circle", condition_id="baseline", seed_family=23099)
        with self.assertRaisesRegex(ValueError, "fixed"):
            campaign.extend_sampling_plan(plan, [addition], "coverage missing")
        for mutate in (
                lambda p: p["sampling_jobs"]["train"].pop(),
                lambda p: p["sampling_jobs"]["train"][0].update(condition_id="n10-v30-k1500"),
                lambda p: p["sampling_jobs"]["evaluation"][0].update(seed_family=23001),
                lambda p: p.update(sampling_max_additional_jobs=24),
                lambda p: p["sampling_revisions"].append(dict(additions=[addition])),
                lambda p: p["sampling_jobs"]["train"].append(
                    {key: value for key, value in addition.items() if key != "split"})):
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.assertRaises(ValueError):
                campaign.jobs_for(changed, "train")

    def test_resume_identity_includes_sparse_assignment_and_profile(self):
        original = quick()
        for mutate in (
                lambda p: p["sampling_jobs"]["train"].reverse(),
                lambda p: p.update(design_profile=campaign.COMPACT_PROFILE),
                lambda p: p["figure_ids"].pop()):
            changed = copy.deepcopy(original)
            mutate(changed)
            self.assertNotEqual(campaign.execution_identity(original, "train"),
                                campaign.execution_identity(changed, "train"))

    def test_cli_selects_the_profile_default_and_never_overwrites_design(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "quick"
            arguments = ["init", "--root", str(root), "--profile", PROFILE]
            self.assertEqual(campaign.main(arguments), 0)
            path = root / "plan/design.json"
            original = path.read_bytes()
            self.assertEqual(json.loads(original)["measurement_duration"], 120)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(campaign.main(arguments), 1)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
