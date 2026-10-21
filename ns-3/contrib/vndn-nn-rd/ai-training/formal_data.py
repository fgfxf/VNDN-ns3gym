"""Versioned hello-window datasets for the controlled experiment campaign."""

import bisect
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re

import numpy as np

OBSERVATION_CONTRACT = "rsu-hello-window-v1"
LABEL_CONTRACT = "source-rsu-router-return-serving-rsu-v1"
FEATURE_NAMES = ("x", "y", "speed", "acceleration", "angle", "lane_index")
SCENARIO_LABELS = {"circle": list(range(2)), "grid": list(range(7)),
                   "spidermap": list(range(7))}
SPLITS = ("train", "validation", "evaluation")
RAW_FILES = ("training-observations.jsonl", "face-roles.json", "request-events.csv",
             "mobility-events.csv", "data-rx.csv", "recorder-complete.json",
             "simulation-result.json", "effective-experiment-config.json")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False) + "\n", encoding="utf-8")


def integer(value, field, minimum=0):
    if isinstance(value, bool):
        raise ValueError("{} must be an integer".format(field))
    if isinstance(value, str):
        if not re.fullmatch(r"-?\d+", value):
            raise ValueError("{} must be an integer".format(field))
        value = int(value)
    if not isinstance(value, int) or value < minimum:
        raise ValueError("{} must be an integer >= {}".format(field, minimum))
    return value


def verify_hash(path, expected):
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("missing/invalid hash for {}".format(path))
    if not Path(path).is_file() or sha256_file(path) != expected:
        raise ValueError("hash mismatch: {}".format(path))


def csv_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            yield line, row


def _source(entry, spec, base):
    run = Path(entry["path"]).expanduser()
    if not run.is_absolute():
        run = base / run
    run = run.resolve()
    verify_hash(run / "manifest.json", entry.get("manifest_sha256"))
    manifest = read_json(run / "manifest.json")
    if manifest.get("status") != "complete":
        raise ValueError("source run must be complete: {}".format(run))
    if manifest.get("strategy") != 0:
        raise ValueError("only NoForward sources are accepted")
    if manifest.get("scenario") != spec["scenario"]:
        raise ValueError("source scenario mismatch")
    if not isinstance(manifest.get("validation_only"), bool):
        raise ValueError("source lacks explicit validation_only")
    if manifest["validation_only"] and not spec["validation_only"]:
        raise ValueError("formal dataset cannot contain validation_only source")
    processes = manifest.get("processes", {})
    if not processes or any(record.get("returncode") != 0 for record in processes.values()):
        raise ValueError("source processes did not complete successfully")
    artifacts = manifest.get("artifact_hashes", {})
    for name in RAW_FILES:
        verify_hash(run / "raw" / name, artifacts.get("raw/" + name))
    verify_hash(run / "experiment.json", manifest.get("config_sha256"))
    for name, digest in manifest.get("input_hashes", {}).items():
        verify_hash(name, digest)
    config = read_json(run / "experiment.json")
    for field in ("scenario", "run_id", "strategy"):
        if config.get(field) != manifest.get(field):
            raise ValueError("source config/manifest {} mismatch".format(field))
    if config.get("training_snapshots") is not True:
        raise ValueError("source did not enable training_snapshots")
    for field in ("rng_seed", "rng_run", "sumo_seed", "srand_seed"):
        integer(config.get("seeds", {}).get(field), field, 1)
    complete = read_json(run / "raw/recorder-complete.json")
    result = read_json(run / "raw/simulation-result.json")
    if complete.get("complete") is not True or result.get("complete") is not True:
        raise ValueError("source raw recorder/simulation is not complete")
    if complete.get("training_snapshots") is not True:
        raise ValueError("recorder did not complete training_snapshots")
    if result.get("run_id") != manifest["run_id"] or result.get("scenario") != spec["scenario"]:
        raise ValueError("simulation result identity mismatch")
    digest = manifest.get("source", {}).get("sha256")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("source code hash is missing")
    return run, manifest, config, complete


def _request_table(raw, complete):
    requests, terminals, request_ids = {}, {}, set()
    diagnostics = []
    fields = ("request_id", "name", "vehicle_id", "node_id", "sequence", "send_ns", "deadline_ns")
    for line, row in csv_rows(raw / "request-events.csv"):
        name = row["name"]
        if row["event"] == "GENERATED":
            if name in requests or row["request_id"] in request_ids:
                raise ValueError("duplicate generated request identity")
            record = dict(row, line=line)
            for field in ("node_id", "send_ns", "deadline_ns", "time_ns"):
                record[field] = integer(row[field], field)
            if record["time_ns"] != record["send_ns"] or (
                    record["deadline_ns"] - record["send_ns"] != 3000000000):
                raise ValueError("invalid generated request timing")
            requests[name] = record
            request_ids.add(row["request_id"])
        elif row["event"] in ("DUPLICATE_DATA", "LATE_DATA", "POST_TERMINAL_DATA"):
            diagnostics.append(dict(row, line=line))
        else:
            if row["event"] not in ("DATA", "TIMEOUT", "NACK", "STOPPED") or name in terminals:
                raise ValueError("invalid/duplicate request terminal")
            terminals[name] = dict(row, line=line)
    if set(requests) != set(terminals):
        raise ValueError("request terminal closure failed")
    for name, request in requests.items():
        terminal = terminals[name]
        if any(str(request[field]) != str(terminal[field]) for field in fields):
            raise ValueError("terminal request identity mismatch")
        timestamp = integer(terminal["time_ns"], "terminal time")
        if timestamp < request["send_ns"] or (
                terminal["event"] == "DATA" and timestamp > request["deadline_ns"]) or (
                terminal["event"] == "TIMEOUT" and timestamp < request["deadline_ns"]):
            raise ValueError("terminal time violates request lifetime")
        request["terminal"] = terminal["event"]
    diagnostic_counts = Counter()
    for diagnostic in diagnostics:
        request = requests.get(diagnostic["name"])
        if request is None or any(str(request[field]) != str(diagnostic[field]) for field in fields):
            raise ValueError("diagnostic request identity mismatch")
        terminal = terminals[diagnostic["name"]]
        timestamp = integer(diagnostic["time_ns"], "diagnostic time")
        event = diagnostic["event"]
        if (diagnostic["line"] <= terminal["line"] or
                timestamp < integer(terminal["time_ns"], "terminal time") or
                (event == "LATE_DATA") != (timestamp > request["deadline_ns"]) or
                (event == "DUPLICATE_DATA" and terminal["event"] != "DATA") or
                (event == "POST_TERMINAL_DATA" and terminal["event"] == "DATA")):
            raise ValueError("diagnostic does not follow the actual first terminal")
        diagnostic_counts[event] += 1
    if (complete.get("generated") != len(requests) or
            complete.get("terminal") != len(terminals)):
        raise ValueError("recorder counts do not close")
    return requests, diagnostic_counts


def _faces(raw, scenario, run_id):
    metadata = read_json(raw / "face-roles.json")
    if any(metadata.get(key) != value for key, value in (
            ("schema_version", 1), ("scenario", scenario), ("run_id", run_id))):
        raise ValueError("face metadata identity mismatch")
    roles = {}
    for node in metadata["nodes"]:
        identity = integer(node["node_id"], "node_id")
        if identity in roles:
            raise ValueError("duplicate face node identity")
        roles[identity] = node["role"]
    faces, returns, wireless = set(), set(), set()
    for face in metadata["faces"]:
        key = (integer(face["node_id"], "node_id"), integer(face["face_id"], "face_id"))
        if key in faces or key[0] not in roles:
            raise ValueError("duplicate/unknown face identity")
        faces.add(key)
        if face["role"] == "router_return":
            peers = face["peer_node_ids"]
            if roles[key[0]] != "rsu" or not peers or any(roles.get(p) != "router" for p in peers):
                raise ValueError("router_return must connect RSU to Router")
            returns.add(key)
        if face["role"] == "wireless":
            wireless.add(key)
    return returns, wireless


def _return_times(raw, allowed):
    returns = {}
    for line, row in csv_rows(raw / "data-rx.csv"):
        node, face = integer(row["node_id"], "node_id"), integer(row["face_id"], "face_id")
        if (node, face) in allowed:
            key = (row["name"], node)
            value = (integer(row["time_ns"], "time_ns"), line, face)
            if key not in returns or value[:2] < returns[key][:2]:
                returns[key] = value
    return returns


def _mobility(raw):
    history = defaultdict(list)
    for line, row in csv_rows(raw / "mobility-events.csv"):
        if row["event"] in ("ENTER", "ASSOCIATION"):
            history[(row["vehicle_id"], integer(row["node_id"], "node_id"))].append(
                (integer(row["time_ns"], "time_ns"), line,
                 integer(row["rsu_id"], "rsu_id", -1), row["event"],
                 integer(row["previous_rsu_id"], "previous_rsu_id", -1)))
    for records in history.values():
        records.sort()
    return history


def _handover(records, start, end):
    last_valid = None
    for time, _, current, _, previous in records:
        if time > end:
            break
        if last_valid is None and previous >= 0:
            last_valid = previous
        if current >= 0:
            changed = last_valid is not None and current != last_valid
            last_valid = current
            if changed and start <= time <= end:
                return True
    return False


def _observation(row, scenario, run_id, request, wireless, seen, events):
    if row.get("schema_version") != 1 or row.get("observation_contract") != OBSERVATION_CONTRACT:
        raise ValueError("unsupported observation contract")
    if row.get("scenario") != scenario or row.get("run_id") != run_id:
        raise ValueError("observation scenario/run mismatch")
    event = integer(row.get("decision_event_id"), "decision_event_id", 1)
    if event != len(events) + 1:
        raise ValueError("decision_event_id must be consecutive within a run")
    events.add(event)
    exclusion = row.get("sample_exclusion_reason")
    if not isinstance(exclusion, str):
        raise ValueError("missing sample_exclusion_reason")
    if exclusion == "UNKNOWN_REQUEST":
        if request is not None:
            raise ValueError("known request marked UNKNOWN_REQUEST")
        return "unknown_request", None
    if request is None:
        raise ValueError("observation has unknown request without exclusion")
    if exclusion == "OBU_ID_MISMATCH":
        if row.get("obu_node_id") == request["node_id"]:
            raise ValueError("matching OBU marked OBU_ID_MISMATCH")
        return "obu_id_mismatch", None
    for field, expected in (
            ("request_id", request["request_id"]), ("vehicle_id", request["vehicle_id"]),
            ("obu_node_id", request["node_id"]), ("send_time_ns", request["send_ns"]),
            ("deadline_ns", request["deadline_ns"])):
        if row.get(field) != expected:
            raise ValueError("observation request identity mismatch: " + field)
    source = integer(row.get("source_rsu_id"), "source_rsu_id")
    if source not in SCENARIO_LABELS[scenario]:
        raise ValueError("source RSU is not in the scenario")
    if (source, row.get("incoming_face_id")) not in wireless:
        raise ValueError("observation is not a wireless decision")
    decision = integer(row.get("decision_time_ns"), "decision_time_ns")
    key = (request["request_id"], source)
    first = seen.setdefault(key, event)
    expected_first = first == event
    if row.get("first_for_source_request") is not expected_first or (
            row.get("first_decision_event_id") != first):
        raise ValueError("incorrect first/duplicate decision claim")
    if not expected_first:
        return "duplicate_source_request", None
    if not request["send_ns"] <= decision <= request["deadline_ns"]:
        return "decision_outside_request_lifetime", None
    if exclusion:
        return exclusion.lower(), None
    candidates = row.get("candidate_rsu_ids")
    if (not isinstance(candidates, list) or not candidates or source not in candidates or
            any(isinstance(x, bool) or not isinstance(x, int) or x not in SCENARIO_LABELS[scenario]
                for x in candidates) or len(set(candidates)) != len(candidates)):
        raise ValueError("invalid candidate RSU identities")
    values = np.asarray(row.get("features"), dtype=np.float64)
    if values.shape != (10, 6):
        raise ValueError("observation must be 10x6")
    with np.errstate(over="ignore", invalid="ignore"):
        converted = values.astype(np.float32)
    if not np.isfinite(values).all() or not np.isfinite(converted).all():
        return "nonfinite_feature", None
    length = integer(row.get("actual_history_length"), "actual_history_length")
    if length > 10 or row.get("padding_count") != 10 - length:
        raise ValueError("history length/padding mismatch")
    times = row.get("hello_receive_times_ns")
    if not isinstance(times, list) or len(times) != length:
        raise ValueError("hello history length mismatch")
    times = [integer(t, "hello_receive_time") for t in times]
    if times != sorted(times) or any(t > decision for t in times):
        raise ValueError("future or unordered hello violates causality")
    if length:
        if row.get("history_age_ns") != decision - times[-1]:
            raise ValueError("history age does not match received hello")
        if length < 10 and not np.all(values[:10 - length] == values[10 - length]):
            raise ValueError("left padding must repeat the earliest hello")
    elif np.any(values != 0) or row.get("history_age_ns") is not None:
        raise ValueError("empty history must use all-zero padding and null age")
    return None, converted


def _materialize_run(run, manifest, complete, entry, scenario, output, shard_number, audit):
    raw = run / "raw"
    requests, diagnostic_counts = _request_table(raw, complete)
    returns_allowed, wireless = _faces(raw, scenario, manifest["run_id"])
    returns, mobility = _return_times(raw, returns_allowed), _mobility(raw)
    prefix = "shard-{:05d}".format(shard_number)
    binary = output / (prefix + ".tmp")
    labels, terminals, exclusions = [], Counter(), Counter()
    samples_path = output / (prefix + ".samples.jsonl")
    seen, events = {}, set()
    retained = 0
    row_count = 0
    eligible_count = 0
    with binary.open("wb") as values_out, samples_path.open("w", encoding="utf-8") as samples:
        with (raw / "training-observations.jsonl").open(encoding="utf-8") as stream:
            for line, text in enumerate(stream, 1):
                row_count += 1
                row = json.loads(text)
                eligible_count += not bool(row.get("sample_exclusion_reason"))
                request = requests.get(row.get("name"))
                reason, values = _observation(row, scenario, manifest["run_id"], request,
                                               wireless, seen, events)
                returned = None
                associated = None
                records = []
                if reason is None:
                    returned = returns.get((row["name"], row["source_rsu_id"]))
                    if returned is None:
                        reason = "missing_return"
                    elif returned[0] < row["decision_time_ns"]:
                        reason = "return_before_decision"
                    elif returned[0] > request["deadline_ns"]:
                        reason = "late_return"
                    else:
                        records = mobility.get((request["vehicle_id"], request["node_id"]), [])
                        before = bisect.bisect_right([x[0] for x in records], returned[0])
                        if not before:
                            reason = "unknown_association"
                        else:
                            associated = records[before - 1]
                            if any(r[0] == returned[0] and r[3] == "ASSOCIATION" for r in records):
                                reason = "ambiguous_same_time_association"
                            elif associated[2] not in SCENARIO_LABELS[scenario]:
                                reason = "unassociated_return"
                evidence = dict(
                    observation_line=line, decision_event_id=row.get("decision_event_id"),
                    request_id=row.get("request_id"), name=row.get("name"),
                    vehicle_id=row.get("vehicle_id"), obu_node_id=row.get("obu_node_id"),
                    source_rsu_id=row.get("source_rsu_id"), exclusion_reason=reason,
                    candidate_rsu_ids=row.get("candidate_rsu_ids"),
                    return_time_ns=returned[0] if returned else None,
                    return_line=returned[1] if returned else None,
                    return_face_id=returned[2] if returned else None,
                    association_line=associated[1] if associated else None,
                    terminal=request["terminal"] if request else None,
                    actual_history_length=row.get("actual_history_length"),
                    history_age_ns=row.get("history_age_ns"),
                    decision_time_ns=row.get("decision_time_ns"),
                    handover=_handover(records, request["send_ns"], request["deadline_ns"])
                    if request and records else False)
                if reason:
                    exclusions[reason] += 1
                else:
                    values.tofile(values_out)
                    labels.append(associated[2])
                    terminals[request["terminal"]] += 1
                    evidence.update(sample_index=retained, label=associated[2])
                    retained += 1
                samples.write(json.dumps(evidence, allow_nan=False) + "\n")
    if (complete.get("training_snapshot_rows") != row_count or
            complete.get("training_snapshot_eligible") != eligible_count or
            complete.get("training_snapshot_excluded") != row_count - eligible_count):
        raise ValueError("training observation count does not match completion marker")
    feature_path = output / (prefix + ".features.npy")
    target_path = output / (prefix + ".targets.npy")
    if retained:
        source = np.memmap(binary, dtype=np.float32, mode="r", shape=(retained, 10, 6))
        destination = np.lib.format.open_memmap(
            feature_path, mode="w+", dtype=np.float32, shape=(retained, 10, 6))
        for start in range(0, retained, 4096):
            destination[start:start + 4096] = source[start:start + 4096]
        destination.flush()
        del destination, source
    else:
        np.save(feature_path, np.empty((0, 10, 6), dtype=np.float32))
    binary.unlink()
    np.save(target_path, np.asarray(labels, dtype=np.int64))
    counts = np.bincount(labels, minlength=len(SCENARIO_LABELS[scenario])).tolist()
    audit["excluded"].update(exclusions)
    audit["observation_count"] += row_count
    audit["generated_count"] += len(requests)
    shard = dict(
        run_id=manifest["run_id"], source_path=str(run), split=entry["split"],
        seed_family=entry["seed_family"], condition_id=entry["condition_id"],
        sample_count=retained, observation_count=row_count, generated_count=len(requests),
        class_counts=counts, terminal_counts=dict(terminals), excluded=dict(exclusions),
        diagnostic_counts=dict(diagnostic_counts),
        features=feature_path.name, targets=target_path.name, samples=samples_path.name,
        source_manifest_sha256=entry["manifest_sha256"], source_code=manifest["source"])
    shard["hashes"] = {p.name: sha256_file(p) for p in (feature_path, target_path, samples_path)}
    audit["runs"].append(shard)
    return shard


def build_dataset(spec_path, output_dir):
    """Build immutable per-run mmap shards; audit all excluded observations.

    Data are read one run at a time. No result-order windows are constructed.
    A rejected build retains audit evidence but never writes an accepted manifest.
    """
    spec_path, output = Path(spec_path).resolve(), Path(output_dir).resolve()
    spec = read_json(spec_path)
    if (spec.get("schema_version") != 1 or spec.get("scenario") not in SCENARIO_LABELS or
            not isinstance(spec.get("validation_only"), bool) or not spec.get("split_version")):
        raise ValueError("invalid source specification")
    entries = spec.get("runs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("source specification has no runs")
    sources, paths, run_ids, families, random_families, code = [], set(), set(), {}, {}, None
    for entry in entries:
        split = entry.get("split")
        if split not in SPLITS:
            raise ValueError("split must be train, validation or evaluation")
        family = integer(entry.get("seed_family"), "seed_family", 1)
        if family in families and families[family] != split:
            raise ValueError("seed family leaks across split boundaries")
        families[family] = split
        if not isinstance(entry.get("condition_id"), str) or not entry["condition_id"]:
            raise ValueError("missing condition_id")
        run, manifest, config, complete = _source(entry, spec, spec_path.parent)
        if run in paths or manifest["run_id"] in run_ids:
            raise ValueError("duplicate run source")
        paths.add(run)
        run_ids.add(manifest["run_id"])
        signature = tuple(config["seeds"][key] for key in
                          ("rng_seed", "rng_run", "sumo_seed", "srand_seed"))
        if signature in random_families and random_families[signature] != split:
            raise ValueError("actual simulation seeds leak across splits")
        random_families[signature] = split
        if code is not None and code != manifest["source"]["sha256"]:
            raise ValueError("sources were collected from different code")
        code = manifest["source"]["sha256"]
        sources.append((run, manifest, complete, entry))
    if set(families.values()) != set(SPLITS):
        raise ValueError("all three explicit splits are required")
    output.mkdir(parents=True, exist_ok=False)
    audit = dict(observation_count=0, generated_count=0, excluded=Counter(), runs=[])
    try:
        shards = []
        for index, (run, manifest, complete, entry) in enumerate(sources):
            shards.append(_materialize_run(run, manifest, complete, entry, spec["scenario"],
                                            output, index, audit))
            _source(entry, spec, spec_path.parent)  # Do not certify evidence changed while being read.
        splits = {}
        for split in SPLITS:
            selected = [s for s in shards if s["split"] == split]
            counts = np.asarray([s["class_counts"] for s in selected], dtype=np.int64).sum(axis=0)
            splits[split] = dict(sample_count=int(counts.sum()), class_counts=counts.tolist(),
                                 run_count=len(selected),
                                 seed_families=sorted({s["seed_family"] for s in selected}))
            missing = np.flatnonzero(counts == 0).tolist()
            if missing:
                raise ValueError("{} missing target classes: {}".format(split, missing))
        result = dict(
            schema_version=1, scenario=spec["scenario"], validation_only=spec["validation_only"],
            observation_contract=OBSERVATION_CONTRACT, label_contract=LABEL_CONTRACT,
            feature_names=list(FEATURE_NAMES), sequence_length=10,
            label_values=SCENARIO_LABELS[spec["scenario"]], split_version=spec["split_version"],
            source_specification=str(spec_path), source_specification_sha256=sha256_file(spec_path),
            source_code_sha256=code, shards=shards, splits=splits,
            audit=dict(audit, excluded=dict(audit["excluded"])))
        write_json(output / "dataset-manifest.json", result)
        return result
    finally:
        write_json(output / "audit.json", dict(audit, excluded=dict(audit["excluded"])))


def load_dataset_manifest(path, verify_sources=True):
    path = Path(path).resolve()
    result = read_json(path)
    scenario = result.get("scenario")
    if (result.get("schema_version") != 1 or scenario not in SCENARIO_LABELS or
            result.get("observation_contract") != OBSERVATION_CONTRACT or
            result.get("label_contract") != LABEL_CONTRACT or
            result.get("feature_names") != list(FEATURE_NAMES) or
            result.get("sequence_length") != 10 or
            result.get("label_values") != SCENARIO_LABELS[scenario]):
        raise ValueError("dataset contract mismatch")
    verify_hash(result["source_specification"], result["source_specification_sha256"])
    for shard in result["shards"]:
        for filename, digest in shard["hashes"].items():
            verify_hash(path.parent / filename, digest)
        if verify_sources:
            run = Path(shard["source_path"])
            verify_hash(run / "manifest.json", shard["source_manifest_sha256"])
            source = read_json(run / "manifest.json")
            for filename in RAW_FILES:
                verify_hash(run / "raw" / filename,
                            source["artifact_hashes"].get("raw/" + filename))
            for filename, digest in source.get("input_hashes", {}).items():
                verify_hash(filename, digest)
    return result
