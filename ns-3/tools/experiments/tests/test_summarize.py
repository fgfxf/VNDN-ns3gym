import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from experiment_test_support import valid_run


SPEC = importlib.util.spec_from_file_location(
    "experiment_summarize", Path(__file__).resolve().parents[1] / "summarize.py")
summarize = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summarize)


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = valid_run(Path(self.temporary.name) / "run")

    def invoke(self):
        return summarize.summarize_run(self.run, require_manifest=False)

    def rewrite(self, name, edit):
        path = self.run / "raw" / name
        with path.open(newline="") as stream:
            rows = list(csv.reader(stream))
        edit(rows)
        with path.open("w", newline="") as stream:
            csv.writer(stream).writerows(rows)

    def test_metrics_use_generated_cohort_and_drain_bytes(self):
        result = self.invoke()
        self.assertEqual(result.get("generated"), 4)
        self.assertEqual(result["satisfied"], 1)
        self.assertEqual(result["isr_percent"], 25)
        self.assertEqual(result["mean_success_rtt_ms"], 100)
        self.assertEqual(result["sum_success_rtt_ns"], 100000000)
        self.assertEqual(result["extra_data_app_attempts"], 2)
        self.assertEqual(result["network_l3_bytes"], 500)
        self.assertEqual(result["control_l3_bytes"], 130)
        self.assertEqual(result["relay_l3_bytes"], 130)
        self.assertEqual(result["relay_inner_data_bytes"], 100)
        self.assertEqual(result["relay_encapsulation_bytes"], 30)
        self.assertEqual(result["out_nack_count"], 1)
        self.assertEqual(result["network_bytes_per_interest"], 125)
        self.assertAlmostEqual(result["network_mbit"], .004)
        self.assertIn("L3", result["measurement_scope"])

    def test_zero_success_is_null_not_timeout_delay(self):
        valid_run(self.run, all_timeout=True)
        result = self.invoke()
        self.assertIsNone(result.get("mean_success_rtt_ms", "missing"))
        self.assertIsNone(result["network_bytes_per_satisfied_interest"])

    def test_missing_completion_or_nonclosed_requests_rejected(self):
        (self.run / "raw/recorder-complete.json").unlink()
        with self.assertRaises(ValueError):
            self.invoke()
        valid_run(self.run)
        self.rewrite("request-events.csv", lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "terminal|closed"):
            self.invoke()

    def test_duplicate_generation_and_multiple_terminals_rejected(self):
        for index in (1, 2):
            valid_run(self.run)
            self.rewrite("request-events.csv", lambda rows: rows.append(rows[index]))
            with self.assertRaises(ValueError):
                self.invoke()

    def test_unknown_class_bad_bytes_and_incoming_events_rejected(self):
        for column, value in ((6, "unknown"), (7, "-1"), (3, "IN")):
            valid_run(self.run)
            self.rewrite("packet-l3.csv", lambda rows: rows[1].__setitem__(column, value))
            with self.assertRaises(ValueError):
                self.invoke()

    def test_invalid_terminal_deadline_and_recorder_counts_rejected(self):
        self.rewrite("request-events.csv", lambda rows: rows[2].__setitem__(0, "5000000000"))
        with self.assertRaises(ValueError):
            self.invoke()
        valid_run(self.run)
        p = self.run / "raw/recorder-complete.json"
        value = json.loads(p.read_text())
        value["generated"] = 999
        p.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.invoke()

    def test_app_attempts_are_unique_and_only_known_reasons(self):
        for column, value in ((1, "extra-2"), (6, "UNKNOWN"), (7, "DECISION")):
            valid_run(self.run)
            self.rewrite("data-attempts.csv", lambda rows: rows[1].__setitem__(column, value))
            with self.assertRaises(ValueError):
                self.invoke()

    def test_requires_runner_completion_for_standalone_use(self):
        with self.assertRaisesRegex(ValueError, "manifest"):
            summarize.summarize_run(self.run)

    def test_cpp_completion_must_match_run_and_end_time(self):
        path = self.run / "raw/simulation-result.json"
        for key, value in (("complete", False), ("run_id", "different"),
                           ("simulated_end_ns", 2000000000)):
            valid_run(self.run)
            record = json.loads(path.read_text())
            record[key] = value
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                self.invoke()

    def test_effective_configuration_and_planned_vehicle_count_are_checked(self):
        path = self.run / "raw/effective-experiment-config.json"
        for key, value in (("expected_requests", 3), ("vehicle_ids", ["other"]),
                           ("drain_end_ns", 4000000000)):
            valid_run(self.run)
            record = json.loads(path.read_text())
            record[key] = value
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                self.invoke()

    def test_missing_parent_is_explicitly_allowed_for_application_attempts(self):
        self.rewrite("data-attempts.csv", lambda rows: rows[1].__setitem__(2, ""))
        self.assertEqual(self.invoke()["extra_data_app_attempts"], 2)

    def test_face_only_fallback_target_is_reported_as_unknown(self):
        self.rewrite("data-attempts.csv", lambda rows: rows[1].__setitem__(5, "-1"))
        result = self.invoke()
        self.assertEqual(result["extra_data_app_attempts"], 2)
        self.assertEqual(result["unknown_target_app_attempts"], 1)

    def test_data_after_nack_is_diagnostic_and_never_restores_success(self):
        def add_post_terminal(rows):
            row = list(rows[6])  # NACK terminal for request 3
            row[0] = str(int(row[0]) + 1)
            row[1] = "POST_TERMINAL_DATA"
            rows.append(row)
        self.rewrite("request-events.csv", add_post_terminal)
        result = self.invoke()
        self.assertEqual(result["satisfied"], 1)
        self.assertEqual(result["diagnostic_counts"]["POST_TERMINAL_DATA"], 1)

    def test_data_at_deadline_after_timeout_remains_a_diagnostic(self):
        def add_post_timeout(rows):
            row = list(rows[4])  # TIMEOUT at its deadline for request 2
            row[1] = "POST_TERMINAL_DATA"
            rows.append(row)
        self.rewrite("request-events.csv", add_post_timeout)
        result = self.invoke()
        self.assertEqual(result["satisfied"], 1)
        self.assertEqual(result["terminal_counts"]["TIMEOUT"], 1)
        self.assertEqual(result["diagnostic_counts"]["POST_TERMINAL_DATA"], 1)

    def test_recorder_completion_matches_plan_final_time_and_all_attempt_rows(self):
        marker = self.run / "raw/recorder-complete.json"
        for field, value in (("planned", 5), ("extra_attempts", 1),
                             ("final_time_ns", 5500000000)):
            with self.subTest(field=field):
                valid_run(self.run)
                record = json.loads(marker.read_text())
                record[field] = value
                marker.write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError, "recorder"):
                    self.invoke()
        valid_run(self.run)
        self.rewrite("data-attempts.csv", lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "recorder"):
            self.invoke()
        valid_run(self.run)
        # The completion proof counts every recorded row, even outside [t0,t2).
        self.rewrite("data-attempts.csv",
                     lambda rows: rows[1].__setitem__(0, "5500000000"))
        self.assertEqual(self.invoke()["extra_data_app_attempts"], 1)

    def test_native_nack_is_separate_and_cannot_label_interest_data(self):
        result = self.invoke()
        self.assertEqual(result["out_nack_count"], 1)
        self.assertEqual(result["network_l3_bytes"], 500)
        self.rewrite("packet-l3.csv", lambda rows: rows[1].__setitem__(6, "native_nack"))
        with self.assertRaises(ValueError):
            self.invoke()

    def test_zero_outgoing_bytes_is_a_valid_measured_result(self):
        self.rewrite("packet-l3.csv", lambda rows: rows.__setitem__(slice(1, None), []))
        self.rewrite("data-attempts.csv", lambda rows: rows.__setitem__(slice(1, None), []))
        valid_run(self.run, all_timeout=True)
        self.rewrite("packet-l3.csv", lambda rows: rows.__setitem__(slice(1, None), []))
        self.rewrite("data-attempts.csv", lambda rows: rows.__setitem__(slice(1, None), []))
        marker = self.run / "raw/recorder-complete.json"
        record = json.loads(marker.read_text())
        record["extra_attempts"] = 0
        marker.write_text(json.dumps(record))
        result = self.invoke()
        self.assertEqual(result["network_l3_bytes"], 0)
        self.assertEqual(result["control_l3_bytes"], 0)
        self.assertEqual(result["extra_data_app_attempts"], 0)
        self.assertEqual(result["isr_percent"], 0)

    def test_attempt_must_refer_to_a_generated_business_name(self):
        self.rewrite("data-attempts.csv", lambda rows: rows[1].__setitem__(3, "/unknown/1"))
        with self.assertRaisesRegex(ValueError, "cohort"):
            self.invoke()

    def test_mobility_must_cover_planned_vehicles_and_complete_window(self):
        for edit in (lambda rows: rows[1].__setitem__(0, "1500000000"),
                     lambda rows: rows.append(
                         ["3000000000", "EXIT", "veh0", "2", "1", "2", "5", "1", "0"]),
                     lambda rows: rows.pop()):
            valid_run(self.run)
            self.rewrite("mobility-events.csv", edit)
            with self.assertRaisesRegex(ValueError, "mobility"):
                self.invoke()

    def test_realized_speed_and_handover_statistics_are_reported(self):
        result = self.invoke()
        self.assertEqual(result.get("vehicle_count"), 1)
        self.assertEqual(result["vehicle_time_weighted_speed_mps"], 5)
        self.assertEqual(result["handover_count"], 1)
        self.assertEqual(result["stopped_vehicle_time_fraction"], 0)


if __name__ == "__main__":
    unittest.main()
