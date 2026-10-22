"""Frozen-model campaign: scene-specific seeds and real 28-artifact rendering."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaign_test_support import create_campaign, digest, dump, seal_run
from experiment_test_support import valid_run, write_csv, REQUEST_FIELDS, MOBILITY_FIELDS, ATTEMPT_FIELDS

DIRECTORY = Path(__file__).resolve().parents[1]
PROFILE = "quick-fixed-model-v1"
SEEDS = {"circle": [23001, 23002], "grid": [23009, 23010],
         "spidermap": [23017, 23018]}


def module(name):
    spec = importlib.util.spec_from_file_location("fixed_figures_" + name,
                                                DIRECTORY / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


aggregate = module("aggregate_campaign")
plot = module("plot_campaign")


def figure_ids(scans):
    return [name for name in aggregate.expected_figure_ids(scans) if "confusion" not in name]


def formal_manifest():
    parameters = [(10, 30, k) for k in (1500, 3000, 6000, 9000, 12000)]
    parameters += [(10, v, 6000) for v in (15, 50, 60)]
    parameters += [(n, 30, n * 600) for n in (5, 15, 20)]
    ids = {row: "n{}-v{}-k{}".format(*row) for row in parameters}
    scans = dict(interest=[ids[10, 30, k] for k in (1500, 3000, 6000, 9000, 12000)],
                 speed=[ids[10, v, 6000] for v in (15, 30, 50, 60)],
                 vehicles=[ids[n, 30, n * 600] for n in (5, 10, 15, 20)])
    value = dict(schema_version=1, campaign_id="fixed-model-test", validation_only=False,
                 source_sha256="a" * 64, design_profile=PROFILE,
                 repetitions=sum(SEEDS.values(), []), test_seeds_by_scene=copy.deepcopy(SEEDS),
                 bootstrap=dict(resamples=10000, seed=61021),
                 baseline_condition_id=ids[10, 30, 6000], scans=scans,
                 figure_ids=figure_ids(scans), skip_training_figures=True,
                 conditions=[dict(id=ids[row], vehicles=row[0], speed_kmh=row[1],
                                  requests=row[2]) for row in parameters],
                 models={scene: {} for scene in SEEDS}, model_evaluations={},
                 external_models={scene: {} for scene in SEEDS}, blocks=[])
    for scene, seeds in SEEDS.items():
        for cid in ids.values():
            for seed in seeds:
                block_id = "{}-{}-{}".format(scene, cid, seed)
                value["blocks"].append(dict(scene=scene, condition_id=cid, seed_family=seed,
                    block_id=block_id, runs={str(strategy): dict(
                        path="/fixture/{}/{}".format(block_id, strategy),
                        manifest_sha256="b" * 64) for strategy in range(4)}))
    return value


def tiny_manifest(root):
    manifest = create_campaign(root)
    value = json.loads(manifest.read_text())
    value.update(design_profile=PROFILE, repetitions=sum(SEEDS.values(), []),
                 test_seeds_by_scene=copy.deepcopy(SEEDS), skip_training_figures=True,
                 external_models={})
    del value["scans"]["vehicles_fixed_k"]
    value["figure_ids"] = figure_ids(value["scans"])
    for block in value["blocks"]:
        index = [50001, 50002].index(block["seed_family"])
        seed = SEEDS[block["scene"]][index]
        block["seed_family"] = seed
        for strategy, ref in block["runs"].items():
            run = Path(ref["path"])
            config = json.loads((run / "experiment.json").read_text())
            config["seeds"].update(rng_run=seed, sumo_seed=seed, srand_seed=seed)
            dump(run / "experiment.json", config)
            effective_path = run / "raw/effective-experiment-config.json"
            effective = json.loads(effective_path.read_text())
            effective["seeds"] = config["seeds"]
            dump(effective_path, effective)
            block["runs"][strategy] = seal_run(run, value["source_sha256"],
                value["models"][block["scene"]], block["block_id"], int(strategy))
    # Actual history/evaluation files are absent, not mocked or silently ignored.
    for ref in value["model_evaluations"].values():
        evaluation = json.loads(Path(ref["path"]).read_text())
        Path(evaluation["training_history"]["path"]).unlink()
        Path(ref["path"]).unlink()
    value["model_evaluations"] = {}
    dump(manifest, value)
    return manifest


def full_small_campaign(root):
    """All 264 runs and 5/4/4 axes, scaled request/vehicle counts for a raw-log fixture."""
    manifest = tiny_manifest(root)
    value = json.loads(manifest.read_text())
    parameters = [(2, 30, k) for k in (2, 4, 8, 12, 16)]
    parameters += [(2, v, 8) for v in (15, 50, 60)]
    parameters += [(n, 30, n * 4) for n in (1, 3, 4)]
    ids = {row: "n{}-v{}-k{}".format(*row) for row in parameters}
    value.update(conditions=[dict(id=ids[row], vehicles=row[0], speed_kmh=row[1],
                                 requests=row[2]) for row in parameters],
                 baseline_condition_id=ids[2, 30, 8], blocks=[],
                 scans=dict(interest=[ids[2, 30, k] for k in (2, 4, 8, 12, 16)],
                            speed=[ids[2, v, 8] for v in (15, 30, 50, 60)],
                            vehicles=[ids[n, 30, n * 4] for n in (1, 2, 3, 4)]))
    for scene, seeds in SEEDS.items():
        for vehicles, speed, requests in parameters:
            cid = ids[vehicles, speed, requests]
            for seed in seeds:
                block_id = "{}-{}-{}".format(scene, cid, seed)
                input_summary = root / (block_id + "-input-summary.json")
                dump(input_summary, {"scenario": scene,
                     "vehicles": [{"vehicle_id": "veh" + str(i)} for i in range(vehicles)],
                     "requested_speed_kmh": speed, "requested_count": requests, "seed": seed})
                block = dict(scene=scene, condition_id=cid, seed_family=seed,
                             block_id=block_id, runs={})
                for strategy in range(4):
                    run = valid_run(root / (block_id + "-s" + str(strategy)))
                    config = json.loads((run / "experiment.json").read_text())
                    config.update(scenario=scene, strategy=strategy, block_id=block_id,
                                  input_summary=str(input_summary),
                                  seeds=dict(rng_seed=1, rng_run=seed, sumo_seed=seed, srand_seed=seed))
                    dump(run / "experiment.json", config)
                    valid_run(run, preserve_config=True)
                    request_rows = []
                    for index in range(requests):
                        vehicle = "veh" + str(index % vehicles)
                        sequence = index // vehicles + 1
                        send = 1000000000 + index * 10000000
                        base = [vehicle + ":" + str(sequence), "/com/baidu/" + str(index + 1),
                                vehicle, 2 + index % vehicles, sequence, send, send + 3000000000, 0]
                        request_rows.append([send, "GENERATED"] + base)
                        terminal = "DATA" if index % 2 == 0 else "TIMEOUT"
                        request_rows.append([send + (100000000 if terminal == "DATA" else 3000000000),
                                             terminal] + base)
                    raw = run / "raw"
                    write_csv(raw / "request-events.csv", REQUEST_FIELDS, request_rows)
                    write_csv(raw / "data-attempts.csv", ATTEMPT_FIELDS, [])
                    mobility = []
                    for i in range(vehicles):
                        for time, event, rsu, previous in (
                                (0, "ENTER", -1, -1), (1000000000, "SAMPLE", 0, -1),
                                (1500000000, "ASSOCIATION", 1, 0),
                                (2000000000, "SAMPLE", 1, 0), (5500000000, "SAMPLE", 1, 0)):
                            mobility.append([time, event, "veh" + str(i), 2 + i,
                                             1 + i, 2, speed / 3.6, rsu, previous])
                    write_csv(raw / "mobility-events.csv", MOBILITY_FIELDS, mobility)
                    effective_path = raw / "effective-experiment-config.json"
                    effective = json.loads(effective_path.read_text())
                    effective.update(expected_requests=requests,
                                     vehicle_ids=["veh" + str(i) for i in range(vehicles)])
                    dump(effective_path, effective)
                    completion_path = raw / "recorder-complete.json"
                    completion = json.loads(completion_path.read_text())
                    completion.update(generated=requests, terminal=requests, planned=requests,
                                      extra_attempts=0)
                    dump(completion_path, completion)
                    block["runs"][str(strategy)] = seal_run(
                        run, value["source_sha256"], value["models"][scene], block_id, strategy)
                value["blocks"].append(block)
    dump(manifest, value)
    return manifest


class FixedModelDesignTest(unittest.TestCase):
    def test_264_runs_and_22_numbered_figures_without_training_evaluations(self):
        value = formal_manifest()
        conditions, blocks = aggregate.validate_campaign(value)
        self.assertEqual(len(conditions), 11)
        self.assertEqual(len(blocks), 66)
        self.assertEqual(sum(len(b["runs"]) for b in blocks.values()), 264)
        self.assertEqual(len(value["figure_ids"]), 22)

    def test_missing_wrong_scene_seed_wrong_matrix_and_training_figure_rejected(self):
        for mutate in (
                lambda v: v["blocks"].pop(),
                lambda v: v["blocks"][0]["runs"].pop("2"),
                lambda v: v["test_seeds_by_scene"]["grid"].__setitem__(0, 23001),
                lambda v: v.update(repetitions=[23001, 23002]),
                lambda v: v["conditions"][-1].update(requests=30000),
                lambda v: v["figure_ids"].append("F28-circle-confusion"),
                lambda v: v.update(skip_training_figures=False)):
            value = formal_manifest()
            mutate(value)
            with self.assertRaises(ValueError):
                aggregate.validate_campaign(value)


class FixedModelFiguresTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = tiny_manifest(self.root / "input")

    def analysis(self):
        return aggregate.aggregate_campaign(self.manifest, self.root / "analysis")

    def test_scene_seed_selection_and_metrics_keep_two_replicates(self):
        result = self.analysis()
        self.assertEqual(result["run_count"], 24)
        self.assertEqual(result["representative_seeds_by_scene"],
                         {scene: seeds[0] for scene, seeds in SEEDS.items()})
        self.assertTrue(all(row["repetitions"] == 2 and len(row["run_values"]) == 2
                            for row in result["points"]))
        self.assertTrue(all(row["seed_families"] == 2 for row in result["variation_audit"]))
        self.assertEqual({row["seed_family"] for row in result["factor_audit"]},
                         set(sum(SEEDS.values(), [])))
        for point in result["points"]:
            if point["metric"] == "isr_percent":
                self.assertEqual(point["estimate"], 25.)
                self.assertEqual(point["run_sd"], 0.)

    def test_frozen_model_tampering_and_missing_scene_block_are_rejected(self):
        value = json.loads(self.manifest.read_text())
        Path(value["models"]["grid"]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.analysis()

    def test_wrong_representative_seed_cannot_silently_make_empty_rtt_figures(self):
        self.analysis()
        path = self.root / "analysis/aggregate.json"
        result = json.loads(path.read_text())
        result["representative_seeds_by_scene"]["grid"] = SEEDS["circle"][0]
        dump(path, result)
        with self.assertRaisesRegex(ValueError, "representative|seed"):
            plot.load_analysis(self.root / "analysis")

    def test_every_scan_uses_run_values_and_sd(self):
        result = self.analysis()
        calls = []
        original = plot._draw_points
        def draw(axis, x, records, strategy, descriptive=False):
            calls.append(descriptive)
            return original(axis, x, records, strategy, descriptive)
        def discard(figure, *args, **kwargs):
            plot.plt.close(figure)
            return {}
        with patch.object(plot, "_draw_points", side_effect=draw), \
                patch.object(plot, "save_figure", side_effect=discard):
            plot.scan_figures(result, self.root, plot.lookup_points(result))
        self.assertEqual(len(calls), 180)
        self.assertTrue(all(calls))

    def test_real_aggregate_and_render_28_figures_without_training_files(self):
        self.manifest = full_small_campaign(self.root / "full-input")
        result = self.analysis()
        self.assertEqual(result["run_count"], 264)
        self.assertEqual(result["block_count"], 66)
        self.assertEqual(len(result["points"]), 3 * 11 * 4 * 8)
        self.assertEqual([len(result["scans"][name]) for name in ("interest", "speed", "vehicles")],
                         [5, 4, 4])
        self.assertTrue(all(point["repetitions"] == 2 for point in result["points"]))
        # Complete rendering must not mask a missing scenario/condition/seed block.
        missing = json.loads(self.manifest.read_text())
        missing["blocks"].pop()
        incomplete = self.root / "incomplete.json"
        dump(incomplete, missing)
        with self.assertRaisesRegex(ValueError, "complete|missing|matrix"):
            aggregate.aggregate_campaign(incomplete, self.root / "incomplete-analysis")
        output = self.root / "figures"
        report = plot.plot_campaign(self.root / "analysis", output)
        self.assertEqual(len(report["figures"]), 22)
        self.assertEqual(len(report["diagnostics"]), 6)
        items = report["figures"] + report["diagnostics"]
        self.assertFalse(any(i["kind"] in ("learning", "confusion") for i in items))
        self.assertEqual(report["plot_configuration"]["representative_seeds_by_scene"],
                         {scene: seeds[0] for scene, seeds in SEEDS.items()})
        bins = list(plot.csv_records(output / "time-bin-rtt.csv"))
        for scene, seeds in SEEDS.items():
            rows = [r for r in bins if r["scene"] == scene]
            self.assertEqual({int(r["seed_family"]) for r in rows}, {seeds[0]})
            self.assertGreater(sum(int(r["successes"]) for r in rows), 0)
        for item in items:
            for extension in ("pdf", "svg", "png"):
                self.assertGreater((output / item["files"][extension]).stat().st_size, 100)
            self.assertIn("n=2", item["caption_en"])
        index = (output / "index.html").read_text()
        self.assertIn("28", index)
        self.assertIn("n=2", index)
        self.assertNotIn("n=6", index)
        self.assertEqual(index.count('data-figure-id="'), 28)
        for item in items:
            self.assertIn(item["files"]["png"], index)
        self.assertFalse((output / "model-confusion-counts.csv").exists())


if __name__ == "__main__":
    unittest.main()
