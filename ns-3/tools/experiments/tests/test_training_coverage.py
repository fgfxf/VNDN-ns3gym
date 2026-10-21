"""Coverage gates over real hashed dataset shards; fixtures are not experiments."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

AI = Path(__file__).resolve().parents[3] / "contrib/vndn-nn-rd/ai-training"
sys.path.insert(0, str(AI))
sys.path.insert(0, str(AI / "tests"))
import formal_data as data
from formal_test_support import (fixture_run, fixture_spec, observations, reseal,
                                 sha, update_spec, write_csv, write_json, write_observations)


class TrainingCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "coverage.json"
        self.manifests = {}

    def fixtures(self, no_cross=False, extra_empty=False, excluded=False):
        for scene in ("circle", "grid", "spidermap"):
            folder = self.root / scene
            folder.mkdir()
            spec_path = fixture_spec(folder, scene)
            spec = json.loads(spec_path.read_text())
            if no_cross:
                for entry in spec["runs"]:
                    run = Path(entry["path"])
                    rows = observations(run)
                    for index, row in enumerate(rows):
                        row["source_rsu_id"] = index
                    write_observations(run, rows)
                    rx_path = run / "raw/data-rx.csv"
                    with rx_path.open() as stream:
                        reader = csv.DictReader(stream)
                        fields, received = reader.fieldnames, list(reader)
                    for index, row in enumerate(received):
                        row["node_id"] = index
                    write_csv(rx_path, fields, received)
                    reseal(run)
                update_spec(spec_path)
            if excluded:
                run = folder / "train"
                rows = observations(run)
                duplicate = copy.deepcopy(rows[0])
                duplicate.update(decision_event_id=len(rows) + 1, first_for_source_request=False,
                                 sample_exclusion_reason="DUPLICATE_SOURCE_REQUEST")
                rows.append(duplicate)
                write_observations(run, rows)
                reseal(run)
                update_spec(spec_path)
            if extra_empty:
                run = fixture_run(folder, "empty-train", scene, seed=17)
                rx_path = run / "raw/data-rx.csv"
                rx_path.write_text(rx_path.read_text().splitlines()[0] + "\n")
                reseal(run)
                spec = json.loads(spec_path.read_text())
                spec["runs"].append(dict(path=str(run), split="train", seed_family=17,
                                         condition_id="empty-condition", manifest_sha256=sha(run / "manifest.json")))
                write_json(spec_path, spec)
            output = folder / "dataset"
            data.build_dataset(spec_path, output)
            self.manifests[scene] = output / "dataset-manifest.json"
        return self.manifests

    def audit(self):
        spec = importlib.util.spec_from_file_location(
            "training_coverage_under_test", Path(__file__).resolve().parents[1] / "training_coverage.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.audit_datasets(self.manifests, self.output)

    def mutate_shard_evidence(self, edit):
        path = self.manifests["circle"]
        manifest = json.loads(path.read_text())
        shard = manifest["shards"][0]
        samples_path = path.parent / shard["samples"]
        rows = [json.loads(line) for line in samples_path.read_text().splitlines()]
        edit(rows)
        samples_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        shard["hashes"][shard["samples"]] = sha(samples_path)
        write_json(path, manifest)

    def test_complete_supports_are_stratified_without_making_windows_independent_runs(self):
        self.fixtures()
        report = self.audit()
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["issues"], [])
        for scene, count in (("circle", 2), ("grid", 7), ("spidermap", 7)):
            row = report["scenes"][scene]["splits"]["train"]
            self.assertEqual(row["sample_count"], count)
            self.assertEqual(row["class_counts"], [1] * count)
            self.assertEqual(row["cross_rsu_target_count"], count - 1)
            self.assertEqual(row["short_history_count"], count)
            self.assertEqual(row["run_count"], 1)
            self.assertEqual(row["seed_families"], [1])
            self.assertEqual(row["conditions"]["baseline"]["sample_count"], count)
            self.assertEqual(row["seeds"]["1"]["sample_count"], count)
            self.assertEqual(len(row["vehicles"]), 1)
        self.assertEqual(json.loads(self.output.read_text()), report)

    def test_all_classes_without_cross_rsu_targets_fail_and_save_report(self):
        self.fixtures(no_cross=True)
        # This is valid input for the pre-existing class-only dataset gate.
        existing = data.load_dataset_manifest(self.manifests["circle"])
        self.assertEqual(existing["splits"]["train"]["class_counts"], [1, 1])
        with self.assertRaisesRegex(ValueError, "coverage.*insufficient"):
            self.audit()
        report = json.loads(self.output.read_text())
        self.assertEqual(report["status"], "insufficient")
        self.assertEqual(len([row for row in report["issues"] if row["kind"] == "no_cross_rsu_targets"]), 9)

    def test_excluded_observations_do_not_add_label_or_cross_target_support(self):
        self.fixtures(excluded=True)
        report = self.audit()
        row = report["scenes"]["circle"]["splits"]["train"]
        self.assertEqual(row["observation_count"], 3)
        self.assertEqual(row["sample_count"], 2)
        self.assertEqual(row["excluded"], {"duplicate_source_request": 1})
        self.assertEqual(row["cross_rsu_target_count"], 1)

    def test_zero_sample_run_is_reported_but_split_can_be_covered_by_other_runs(self):
        self.fixtures(extra_empty=True)
        report = self.audit()
        rows = report["scenes"]["circle"]["runs"]
        empty = next(row for row in rows if row["run_id"] == "empty-train")
        self.assertEqual(empty["sample_count"], 0)
        self.assertEqual(empty["excluded"], {"missing_return": 2})
        self.assertEqual(report["status"], "complete")

    def test_missing_scene_is_rejected_with_evidence(self):
        self.fixtures()
        del self.manifests["spidermap"]
        with self.assertRaises(ValueError):
            self.audit()
        self.assertTrue(self.output.is_file())

    def test_wrong_scene_manifest_is_rejected(self):
        self.fixtures()
        self.manifests["grid"] = self.manifests["circle"]
        with self.assertRaisesRegex(ValueError, "coverage.*insufficient"):
            self.audit()
        self.assertIn("scenario", self.output.read_text())

    def test_changed_source_hash_is_rejected(self):
        self.fixtures()
        source = self.root / "circle/train/raw/data-rx.csv"
        source.write_text(source.read_text() + "\n")
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("hash", self.output.read_text())

    def test_summary_count_mismatch_is_rejected(self):
        self.fixtures()
        path = self.manifests["circle"]
        manifest = json.loads(path.read_text())
        manifest["splits"]["train"]["sample_count"] += 1
        write_json(path, manifest)
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("count", self.output.read_text())

    def test_illegal_accepted_label_is_rejected_even_if_file_hash_is_updated(self):
        self.fixtures()
        self.mutate_shard_evidence(lambda rows: rows[0].update(label=99))
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("label", self.output.read_text())

    def test_valid_label_must_equal_target_array(self):
        self.fixtures()
        self.mutate_shard_evidence(lambda rows: rows[0].update(label=1))
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("target", self.output.read_text())

    def test_excluded_row_cannot_also_have_accepted_index(self):
        self.fixtures()
        self.mutate_shard_evidence(lambda rows: rows[0].update(exclusion_reason="missing_return"))
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("sample_index", self.output.read_text())

    def test_accepted_indices_must_be_consecutive(self):
        self.fixtures()
        self.mutate_shard_evidence(lambda rows: rows[1].update(sample_index=0))
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("sample_index", self.output.read_text())

    def test_invalid_jsonl_row_still_retains_a_report(self):
        self.fixtures()
        self.mutate_shard_evidence(lambda rows: rows.__setitem__(0, []))
        with self.assertRaises(ValueError):
            self.audit()
        self.assertIn("observation", self.output.read_text())


if __name__ == "__main__":
    unittest.main()
