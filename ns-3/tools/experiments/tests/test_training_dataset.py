"""Real causal-label and leakage boundaries, without running SUMO."""
import copy
import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

AI = Path(__file__).resolve().parents[3] / "contrib/vndn-nn-rd/ai-training"
sys.path.insert(0, str(AI))
sys.path.insert(0, str(AI / "tests"))
import formal_data as data
from formal_test_support import (fixture_spec, observations, reseal, update_spec,
                                 write_csv, write_json, write_observations)


class FormalDatasetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = fixture_spec(self.root)
        self.run = self.root / "train"
        self.output = self.root / "dataset"

    def build(self):
        result = data.build_dataset(self.spec, self.output)
        self.assertIsInstance(result, dict, "a real manifest must be built")
        self.assertEqual(result.get("schema_version"), 1)
        return result

    def mutate(self, fn, filename="training-observations.jsonl"):
        if filename.endswith(".jsonl"):
            rows = observations(self.run)
            fn(rows)
            write_observations(self.run, rows)
        else:
            path = self.run / "raw" / filename
            with path.open(newline="") as stream:
                reader = csv.DictReader(stream)
                fields, rows = reader.fieldnames, list(reader)
            fn(rows)
            write_csv(path, fields, rows)
        reseal(self.run)
        update_spec(self.spec)

    def test_real_hello_snapshots_and_timeout_labels_are_preserved(self):
        result = self.build()
        self.assertEqual(result["splits"]["train"]["class_counts"], [1, 1])
        shard = result["shards"][0]
        values = np.load(self.output / shard["features"], mmap_mode="r")
        self.assertIsInstance(values, np.memmap)
        self.assertEqual(values.shape, (2, 10, 6))
        np.testing.assert_array_equal(values[0, :, 0], 0)
        self.assertEqual(shard["terminal_counts"], {"TIMEOUT": 2})

    def test_duplicate_source_is_not_weighted_twice_and_another_source_is_distinct(self):
        def edit(rows):
            duplicate = copy.deepcopy(rows[0])
            duplicate.update(decision_event_id=3, first_for_source_request=False,
                             sample_exclusion_reason="DUPLICATE_SOURCE_REQUEST")
            second = copy.deepcopy(rows[0])
            second.update(source_rsu_id=1, decision_event_id=4, first_decision_event_id=4)
            rows.extend([duplicate, second])
        self.mutate(edit)
        self.mutate(lambda rows: rows.append(dict(rows[0], node_id=1, time_ns=1120000000)),
                    "data-rx.csv")
        result = self.build()
        self.assertEqual(result["splits"]["train"]["sample_count"], 3)
        self.assertEqual(result["splits"]["train"]["class_counts"], [1, 2])
        self.assertEqual(result["audit"]["excluded"]["duplicate_source_request"], 1)

    def test_copied_run_cannot_be_counted_as_another_independent_run(self):
        copied = self.root / "copied-train"
        shutil.copytree(self.run, copied)
        specification = json.loads(self.spec.read_text())
        specification["runs"].append(dict(specification["runs"][0], path=str(copied)))
        write_json(self.spec, specification)
        with self.assertRaisesRegex(ValueError, "duplicate.*run|run.*duplicate"):
            data.build_dataset(self.spec, self.output)

    def test_wireless_copy_cannot_supply_the_return_label(self):
        self.mutate(lambda rows: rows.insert(0, dict(rows[0], face_id=257, time_ns=1000000001)),
                    "data-rx.csv")
        result = self.build()
        self.assertEqual(result["splits"]["train"]["sample_count"], 2)

    def test_no_return_is_reported_without_faking_a_timeout_label(self):
        self.mutate(lambda rows: rows.pop(0), "data-rx.csv")
        with self.assertRaisesRegex(ValueError, "missing.*class|class.*missing"):
            data.build_dataset(self.spec, self.output)
        audit = self.output / "audit.json"
        self.assertTrue(audit.is_file(), "even rejected datasets retain exclusion evidence")
        self.assertEqual(json.loads(audit.read_text())["excluded"]["missing_return"], 1)

    def test_late_return_excluded(self):
        self.mutate(lambda rows: rows[0].update(time_ns=4000000001), "data-rx.csv")
        with self.assertRaisesRegex(ValueError, "missing.*class|class.*missing"):
            data.build_dataset(self.spec, self.output)

    def test_causally_invalid_first_return_is_not_replaced_by_later_copy(self):
        self.mutate(lambda rows: rows.insert(0, dict(rows[0], time_ns=1000000001)),
                    "data-rx.csv")
        with self.assertRaisesRegex(ValueError, "missing.*class|class.*missing"):
            data.build_dataset(self.spec, self.output)

    def test_same_nanosecond_association_is_ambiguous(self):
        self.mutate(lambda rows: rows[0].update(time_ns=1020000000), "mobility-events.csv")
        with self.assertRaisesRegex(ValueError, "missing.*class|class.*missing"):
            data.build_dataset(self.spec, self.output)

    def test_future_hello_is_rejected(self):
        self.mutate(lambda rows: rows[0].update(hello_receive_times_ns=[9999999999]))
        with self.assertRaisesRegex(ValueError, "hello|causal"):
            data.build_dataset(self.spec, self.output)

    def test_padding_must_match_online_earliest_state(self):
        self.mutate(lambda rows: rows[0]["features"].__setitem__(0, [42] * 6))
        with self.assertRaisesRegex(ValueError, "padding"):
            data.build_dataset(self.spec, self.output)

    def test_wrong_duplicate_claim_rejected(self):
        self.mutate(lambda rows: rows[0].update(first_for_source_request=False))
        with self.assertRaisesRegex(ValueError, "first|duplicate"):
            data.build_dataset(self.spec, self.output)

    def test_split_cannot_share_a_seed_family(self):
        spec = json.loads(self.spec.read_text())
        spec["runs"][1]["seed_family"] = spec["runs"][0]["seed_family"]
        write_json(self.spec, spec)
        with self.assertRaisesRegex(ValueError, "seed.*split|leak"):
            data.build_dataset(self.spec, self.output)

    def test_changed_source_bytes_rejected(self):
        with (self.run / "raw/data-rx.csv").open("a") as stream:
            stream.write("123,0,258,/com/baidu/0\n")
        with self.assertRaisesRegex(ValueError, "hash"):
            data.build_dataset(self.spec, self.output)

    def test_changed_manifest_rejected(self):
        path = self.run / "manifest.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "hash"):
            data.build_dataset(self.spec, self.output)

    def test_unfinished_and_non_noforward_sources_rejected(self):
        for field, value in (("status", "failed"), ("strategy", 3)):
            with self.subTest(field=field):
                path = self.run / "manifest.json"
                manifest = json.loads(path.read_text())
                original = manifest[field]
                manifest[field] = value
                write_json(path, manifest)
                update_spec(self.spec)
                with self.assertRaisesRegex(ValueError, "complete|NoForward"):
                    data.build_dataset(self.spec, self.output)
                manifest[field] = original
                write_json(path, manifest)

    def test_formal_dataset_rejects_validation_only_source(self):
        spec = json.loads(self.spec.read_text())
        spec["validation_only"] = False
        write_json(self.spec, spec)
        with self.assertRaisesRegex(ValueError, "validation_only"):
            data.build_dataset(self.spec, self.output)

    def test_complete_marker_cannot_hide_missing_observation_rows(self):
        path = self.run / "raw/recorder-complete.json"
        marker = json.loads(path.read_text())
        marker["training_snapshot_rows"] += 1
        write_json(path, marker)
        manifest_path = self.run / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["artifact_hashes"]["raw/recorder-complete.json"] = data.sha256_file(path)
        write_json(manifest_path, manifest)
        update_spec(self.spec)
        with self.assertRaisesRegex(ValueError, "observation.*count|snapshot.*count"):
            data.build_dataset(self.spec, self.output)

    def test_wrong_obu_exclusion_is_preserved_as_diagnostic(self):
        def edit(rows):
            excluded = copy.deepcopy(rows[0])
            excluded.update(decision_event_id=3, obu_node_id=999,
                            first_decision_event_id=None,
                            sample_exclusion_reason="OBU_ID_MISMATCH")
            rows.append(excluded)
        self.mutate(edit)
        result = self.build()
        self.assertEqual(result["audit"]["excluded"]["obu_id_mismatch"], 1)
        self.assertEqual(result["splits"]["train"]["sample_count"], 2)

    def test_late_first_observation_still_owns_source_deduplication(self):
        def edit(rows):
            late = copy.deepcopy(rows[0])
            late.update(decision_event_id=2, first_decision_event_id=2,
                        decision_time_ns=4000000001, sample_exclusion_reason="DECISION_AFTER_DEADLINE")
            valid = copy.deepcopy(rows[1])
            valid.update(decision_event_id=1, first_decision_event_id=1)
            duplicate = copy.deepcopy(late)
            duplicate.update(decision_event_id=3, decision_time_ns=4000000002,
                             first_for_source_request=False,
                             sample_exclusion_reason="DUPLICATE_SOURCE_REQUEST")
            rows[:] = [valid, late, duplicate]
        self.mutate(edit)
        with self.assertRaisesRegex(ValueError, "missing.*class"):
            data.build_dataset(self.spec, self.output)
        audit = json.loads((self.output / "audit.json").read_text())
        self.assertEqual(audit["excluded"].get("duplicate_source_request"), 1)

    def test_actual_candidate_subset_is_preserved(self):
        self.mutate(lambda rows: rows[0].update(candidate_rsu_ids=[0]))
        result = self.build()
        samples = self.output / result["shards"][0]["samples"]
        self.assertEqual(json.loads(samples.read_text().splitlines()[0])["candidate_rsu_ids"], [0])

    def test_data_diagnostics_preserve_first_terminal_and_do_not_increase_denominator(self):
        def edit(rows):
            rows[1].update(event="DATA", time_ns=1050000000)
            rows.extend([
                dict(rows[1], event="DUPLICATE_DATA", time_ns=1060000000),
                dict(rows[1], event="LATE_DATA", time_ns=4000000001),
                dict(rows[3], event="POST_TERMINAL_DATA"),
            ])
        self.mutate(edit, "request-events.csv")
        result = self.build()
        self.assertEqual(result["shards"][0]["terminal_counts"], {"DATA": 1, "TIMEOUT": 1})
        self.assertEqual(result["shards"][0]["generated_count"], 2)
        self.assertEqual(result["shards"][0]["diagnostic_counts"], {
            "DUPLICATE_DATA": 1, "LATE_DATA": 1, "POST_TERMINAL_DATA": 1})

    def test_diagnostic_before_first_terminal_is_not_valid_evidence(self):
        self.mutate(lambda rows: rows.append(
            dict(rows[1], event="POST_TERMINAL_DATA", time_ns=1000000001)),
            "request-events.csv")
        with self.assertRaisesRegex(ValueError, "diagnostic|terminal"):
            data.build_dataset(self.spec, self.output)


if __name__ == "__main__":
    unittest.main()
