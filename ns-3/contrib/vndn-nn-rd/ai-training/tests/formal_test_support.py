"""Small timestamped, hashed runs; no simulator or real experiment data."""
import csv
import hashlib
import json
from pathlib import Path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_csv(path, fields, rows):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def fixture_run(root, name, scenario="circle", offset=0, seed=1):
    count = 2 if scenario == "circle" else 7
    run = Path(root) / name
    raw = run / "raw"
    raw.mkdir(parents=True)
    observations, requests, mobility, received = [], [], [], []
    for label in range(count):
        send = 1000000000 + label * 100000000
        request_id, packet = "veh:{}".format(label), "/com/baidu/{}".format(label)
        base = dict(request_id=request_id, name=packet, vehicle_id="veh",
                    node_id=count, sequence=label, send_ns=send,
                    deadline_ns=send + 3000000000, rsu_id=label)
        requests += [dict(base, time_ns=send, event="GENERATED"),
                     dict(base, time_ns=send + 3000000000, event="TIMEOUT")]
        mobility.append(dict(time_ns=send, event="ASSOCIATION", vehicle_id="veh",
                             node_id=count, x=label, y=0, speed_mps=5,
                             rsu_id=label, previous_rsu_id=label - 1))
        observations.append(dict(
            schema_version=1, observation_contract="rsu-hello-window-v1",
            scenario=scenario, run_id=name, request_id=request_id, name=packet,
            vehicle_id="veh", obu_node_id=count, source_rsu_id=0,
            incoming_face_id=257, decision_event_id=label + 1,
            decision_time_ns=send + 10000000, send_time_ns=send,
            deadline_ns=send + 3000000000, candidate_rsu_ids=list(range(count)),
            features=[[offset + label, 0, 5, 0, 90, 0]] * 10,
            hello_receive_times_ns=[send], actual_history_length=1,
            padding_count=9, history_age_ns=10000000,
            first_for_source_request=True, first_decision_event_id=label + 1,
            sample_exclusion_reason=""))
        received.append(dict(time_ns=send + 20000000, node_id=0, face_id=258, name=packet))
    write_csv(raw / "request-events.csv", list(requests[0]), requests)
    write_csv(raw / "mobility-events.csv", list(mobility[0]), mobility)
    write_csv(raw / "data-rx.csv", list(received[0]), received)
    write_observations(run, observations)
    write_json(raw / "face-roles.json", dict(
        schema_version=1, scenario=scenario, run_id=name,
        nodes=[dict(node_id=i, role="rsu") for i in range(count)] +
              [dict(node_id=count, role="obu"), dict(node_id=count + 2, role="router")],
        faces=[dict(node_id=i, face_id=258, role="router_return", device_index=1,
                    peer_node_ids=[count + 2]) for i in range(count)] +
              [dict(node_id=i, face_id=257, role="wireless", device_index=0,
                    peer_node_ids=[]) for i in range(count)]))
    write_json(raw / "recorder-complete.json", dict(
        schema_version=1, complete=True, generated=count, terminal=count,
        planned=count, training_snapshots=True, training_observations=count))
    write_json(raw / "simulation-result.json", dict(
        schema_version=1, complete=True, run_id=name, scenario=scenario))
    config = dict(schema_version=1, run_id=name, scenario=scenario, strategy=0,
                  training_snapshots=True, validation_only=True,
                  measurement_start_s=1, measurement_end_s=2, drain_end_s=5.5,
                  seeds=dict(rng_seed=seed, rng_run=seed, sumo_seed=seed, srand_seed=seed))
    write_json(run / "experiment.json", config)
    write_json(raw / "effective-experiment-config.json", config)
    write_json(run / "manifest.json", dict(
        schema_version=1, run_id=name, scenario=scenario, strategy=0,
        status="complete", validation_only=True, source={"sha256": "a" * 64},
        config_sha256=sha(run / "experiment.json"), input_hashes={},
        processes={"simulation": {"returncode": 0}}, artifact_hashes={}))
    reseal(run)
    return run


def write_observations(run, rows):
    (Path(run) / "raw/training-observations.jsonl").write_text(
        "".join(json.dumps(row, allow_nan=False) + "\n" for row in rows))


def observations(run):
    return [json.loads(line) for line in
            (Path(run) / "raw/training-observations.jsonl").read_text().splitlines()]


def reseal(run):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    marker_path = run / "raw/recorder-complete.json"
    marker = json.loads(marker_path.read_text())
    snapshot_rows = observations(run)
    marker.update(training_snapshot_rows=len(snapshot_rows),
                  training_snapshot_eligible=sum(not row["sample_exclusion_reason"]
                                                 for row in snapshot_rows),
                  training_snapshot_excluded=sum(bool(row["sample_exclusion_reason"])
                                                 for row in snapshot_rows))
    write_json(marker_path, marker)
    manifest["artifact_hashes"] = {
        str(path.relative_to(run)): sha(path) for path in (run / "raw").iterdir()
        if path.is_file()}
    manifest["config_sha256"] = sha(run / "experiment.json")
    write_json(run / "manifest.json", manifest)


def fixture_spec(root, scenario="circle"):
    root = Path(root)
    entries = []
    for index, split in enumerate(("train", "validation", "evaluation")):
        run = fixture_run(root, split, scenario, index * 1000, index + 1)
        entries.append(dict(path=str(run), split=split, seed_family=index + 1,
                            condition_id="baseline", manifest_sha256=sha(run / "manifest.json")))
    path = root / "sources.json"
    write_json(path, dict(schema_version=1, scenario=scenario,
                         split_version="fixture-v1", validation_only=True, runs=entries))
    return path


def update_spec(path):
    spec = json.loads(Path(path).read_text())
    for run in spec["runs"]:
        run["manifest_sha256"] = sha(Path(run["path"]) / "manifest.json")
    write_json(path, spec)
