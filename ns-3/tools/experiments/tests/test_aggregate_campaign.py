"""Behavioral specifications for complete paired campaign analysis."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from campaign_test_support import create_campaign, digest, dump, seal_run

SPEC = importlib.util.spec_from_file_location(
    "aggregate_campaign", Path(__file__).resolve().parents[1] / "aggregate_campaign.py")
aggregate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aggregate)


def metrics(success=1, rtt_sum_ms=100, generated=4, network=500, control=130, extra=2):
    return {
        "generated": generated, "satisfied": success,
        "sum_success_rtt_ns": int(rtt_sum_ms * 1000000),
        "network_l3_bytes": network, "control_l3_bytes": control,
        "extra_data_app_attempts": extra,
    }


def block(value):
    return {str(strategy): dict(value) for strategy in range(4)}


class PairedStatisticsTest(unittest.TestCase):
    def test_success_rtt_uses_success_weighting(self):
        result = aggregate.paired_statistics(
            [block(metrics(1, 100)), block(metrics(3, 900))], 1000, 23)
        self.assertEqual(result["metrics"]["mean_success_rtt_ms"]["0"]["estimate"], 250)

    def test_counts_and_isr_use_equal_run_weight(self):
        result = aggregate.paired_statistics(
            [block(metrics(1, 100, 2)), block(metrics(3, 900, 10))], 1000, 23)
        self.assertEqual(result["metrics"]["isr_percent"]["0"]["estimate"], 40)
        self.assertEqual(result["metrics"]["network_mbit"]["0"]["estimate"], .004)

    def test_zero_success_resamples_are_retained_and_ci_unavailable(self):
        result = aggregate.paired_statistics(
            [block(metrics(0, 0)), block(metrics(1, 100))], 1000, 23)
        rtt = result["metrics"]["mean_success_rtt_ms"]["0"]
        self.assertEqual(rtt["estimate"], 100)
        self.assertGreater(rtt["invalid_resamples"], 0)
        self.assertIsNone(rtt["ci_low"])
        self.assertIsNone(rtt["ci_high"])
        self.assertEqual(rtt["resamples"], 1000)

    def test_all_zero_success_is_na_not_zero_or_deadline(self):
        result = aggregate.paired_statistics([block(metrics(0, 0))], 100, 5)
        rtt = result["metrics"]["mean_success_rtt_ms"]["3"]
        self.assertIsNone(rtt["estimate"])
        self.assertEqual(rtt["invalid_resamples"], 100)

    def test_paired_effect_uses_same_resampled_blocks(self):
        values = []
        for network in (100, 1000, 10000):
            item = block(metrics(network=network, control=10))
            item["3"]["network_l3_bytes"] += 50
            values.append(item)
        result = aggregate.paired_statistics(values, 1000, 9)
        effect = result["effects"]["network_mbit"]["3-0"]
        self.assertAlmostEqual(effect["estimate"], .0004)
        self.assertAlmostEqual(effect["ci_low"], .0004)
        self.assertAlmostEqual(effect["ci_high"], .0004)

    def test_repeatability_and_incomplete_or_nonfinite_rejection(self):
        values = [block(metrics()), block(metrics(3, 900))]
        self.assertEqual(aggregate.paired_statistics(values, 100, 99),
                         aggregate.paired_statistics(values, 100, 99))
        del values[1]["2"]
        with self.assertRaises(ValueError):
            aggregate.paired_statistics(values, 100, 99)
        invalid = block(metrics())
        invalid["1"]["sum_success_rtt_ns"] = float("nan")
        with self.assertRaises(ValueError):
            aggregate.paired_statistics([invalid], 100, 99)


class HandoverDefinitionTest(unittest.TestCase):
    @staticmethod
    def event(time, previous, current):
        return {"time_ns": str(time), "event": "ASSOCIATION", "vehicle_id": "v",
                "previous_rsu_id": str(previous), "rsu_id": str(current)}

    def test_direct_cross_reconnect_and_same_station_restore_differ(self):
        events = aggregate.handover_events([
            self.event(10, -1, 0), self.event(20, 0, 1),
            self.event(30, 1, -1), self.event(40, -1, 1),
            self.event(50, 1, -1), self.event(70, -1, 0)])
        handovers = [event for event in events if event["is_handover"]]
        self.assertEqual([e["time_ns"] for e in handovers], [20, 70])
        self.assertEqual([e["kind"] for e in handovers], ["direct", "cross_reconnect"])
        self.assertEqual(handovers[1]["loss_duration_ns"], 20)
        self.assertEqual(sum(e["kind"] == "loss" for e in events), 2)
        self.assertEqual(sum(e["kind"] == "restore" for e in events), 1)

    def test_request_closed_interval_and_ties(self):
        events = aggregate.handover_events([self.event(20, 0, 1)])
        self.assertEqual(aggregate.request_handover("v", 20, 30, events), (True, True))
        self.assertEqual(aggregate.request_handover("v", 10, 20, events), (True, True))
        self.assertEqual(aggregate.request_handover("v", 10, 19, events), (False, False))
        self.assertEqual(aggregate.request_handover("other", 10, 30, events), (False, False))


class FactorInvariantTest(unittest.TestCase):
    def fixture(self):
        campaign = {"repetitions": [1], "baseline_condition_id": "base",
                    "scans": {"interest": ["base", "load"], "speed": ["base", "fast"]}}
        signatures = {}
        for scene in aggregate.SCENARIOS:
            for condition in ("base", "load", "fast"):
                signatures[scene, condition, 1] = {
                    "request_sha256": "load-requests" if condition == "load" else "same-requests",
                    "mobility_sha256": "fast-mobility" if condition == "fast" else "same-mobility",
                    "route_family_sha256": "same-families",
                    "network_sha256": "same-road"}
        return campaign, signatures

    def test_speed_changes_mobility_but_not_requests_and_route_families(self):
        campaign, signatures = self.fixture()
        aggregate.audit_factor_invariants(campaign, signatures)
        signatures["circle", "fast", 1]["request_sha256"] = "different-requests"
        with self.assertRaisesRegex(ValueError, "speed|request"):
            aggregate.audit_factor_invariants(campaign, signatures)

    def test_interest_load_must_not_change_vehicle_trajectory(self):
        campaign, signatures = self.fixture()
        signatures["grid", "load", 1]["mobility_sha256"] = "different-mobility"
        with self.assertRaisesRegex(ValueError, "interest|mobility|trajectory"):
            aggregate.audit_factor_invariants(campaign, signatures)


class CampaignAuditTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = create_campaign(self.root / "input")
        self.output = self.root / "analysis"

    def mutate(self, operation):
        value = json.loads(self.manifest.read_text())
        operation(value)
        dump(self.manifest, value)

    def test_complete_campaign_has_audited_sources_statistics_and_baseline(self):
        result = aggregate.aggregate_campaign(self.manifest, self.output)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["validation_only"])
        self.assertEqual(result["run_count"], 24)
        self.assertEqual(len(result["points"]), 3 * 4 * len(aggregate.METRICS))
        self.assertEqual(result["representative_seed"], 50001)
        self.assertEqual(result["campaign_sha256"], digest(self.manifest))
        self.assertTrue((self.output / "baseline-requests.csv").is_file())
        self.assertTrue((self.output / "paired-effects.csv").is_file())
        self.assertTrue((self.output / "run-details.json").is_file())

    def test_model_training_history_hash_is_part_of_the_analysis_contract(self):
        value = json.loads(self.manifest.read_text())
        evaluation_path = Path(value["model_evaluations"]["circle"]["path"])
        evaluation = json.loads(evaluation_path.read_text())
        Path(evaluation["training_history"]["path"]).write_text("tampered")
        with self.assertRaisesRegex(ValueError, "hash"):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_declared_missing_or_duplicate_blocks_cannot_be_silently_ignored(self):
        self.mutate(lambda value: value["blocks"].pop())
        with self.assertRaisesRegex(ValueError, "complete|missing|matrix"):
            aggregate.aggregate_campaign(self.manifest, self.output)
        self.manifest = create_campaign(self.root / "second")
        self.mutate(lambda value: value["blocks"].append(value["blocks"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_missing_strategy_and_reused_run_rejected(self):
        self.mutate(lambda value: value["blocks"][0]["runs"].pop("2"))
        with self.assertRaisesRegex(ValueError, "four|strateg"):
            aggregate.aggregate_campaign(self.manifest, self.output)
        self.manifest = create_campaign(self.root / "second")
        self.mutate(lambda value: value["blocks"][1]["runs"].update(value["blocks"][0]["runs"]))
        with self.assertRaises(ValueError):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_formal_campaign_cannot_use_small_validation_fixture(self):
        self.mutate(lambda value: value.update(validation_only=False))
        with self.assertRaisesRegex(ValueError, "20|17|formal"):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_tampered_raw_or_model_hash_rejected(self):
        value = json.loads(self.manifest.read_text())
        run = Path(value["blocks"][0]["runs"]["0"]["path"])
        with (run / "raw/packet-l3.csv").open("a") as stream:
            stream.write("tampered\n")
        with self.assertRaisesRegex(ValueError, "hash"):
            aggregate.aggregate_campaign(self.manifest, self.output)
        self.manifest = create_campaign(self.root / "second")
        value = json.loads(self.manifest.read_text())
        Path(value["models"]["circle"]["path"]).write_bytes(b"changed model")
        with self.assertRaisesRegex(ValueError, "hash"):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_changed_source_and_wrong_evaluation_contract_rejected(self):
        self.mutate(lambda value: value.update(source_sha256="c" * 64))
        with self.assertRaisesRegex(ValueError, "source"):
            aggregate.aggregate_campaign(self.manifest, self.output)
        self.manifest = create_campaign(self.root / "second")
        value = json.loads(self.manifest.read_text())
        evaluation_path = Path(value["model_evaluations"]["circle"]["path"])
        evaluation = json.loads(evaluation_path.read_text())
        evaluation["split"] = "validation"
        dump(evaluation_path, evaluation)
        value["model_evaluations"]["circle"]["sha256"] = digest(evaluation_path)
        dump(self.manifest, value)
        with self.assertRaisesRegex(ValueError, "evaluation|split"):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_invalid_condition_and_existing_output_rejected(self):
        self.mutate(lambda value: value["conditions"][0].update(requests=999))
        with self.assertRaisesRegex(ValueError, "condition|request|budget"):
            aggregate.aggregate_campaign(self.manifest, self.output)
        self.manifest = create_campaign(self.root / "second")
        self.output.mkdir()
        with self.assertRaises((ValueError, FileExistsError)):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_measurement_window_cannot_change_between_repetitions(self):
        value = json.loads(self.manifest.read_text())
        block = value["blocks"][0]
        for strategy, reference in block["runs"].items():
            run = Path(reference["path"])
            config = json.loads((run / "experiment.json").read_text())
            config["measurement_end_s"] = 2.1
            dump(run / "experiment.json", config)
            effective = json.loads((run / "raw/effective-experiment-config.json").read_text())
            effective["measurement_end_ns"] = 2100000000
            dump(run / "raw/effective-experiment-config.json", effective)
            block["runs"][strategy] = seal_run(
                run, value["source_sha256"], value["models"][block["scene"]],
                block["block_id"], int(strategy))
        dump(self.manifest, value)
        with self.assertRaisesRegex(ValueError, "window"):
            aggregate.aggregate_campaign(self.manifest, self.output)

    def test_source_request_and_mobility_variation_counts_are_disclosed(self):
        result = aggregate.aggregate_campaign(self.manifest, self.output)
        # Fixture seeds differ, but its actual requests and trajectories are
        # deliberately identical. Report this instead of claiming two mobile
        # traffic realizations merely from different seed numbers.
        audit = result.get("variation_audit", [])
        self.assertEqual(len(audit), 3)
        self.assertEqual(audit[0]["unique_request_cohorts"], 1)
        self.assertEqual(audit[0]["unique_physical_mobility"], 1)
        self.assertEqual(audit[0]["seed_families"], 2)


if __name__ == "__main__":
    unittest.main()
