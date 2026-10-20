#!/usr/bin/env python3.8
"""Validate one run: request outcomes, L3 outgoing I+D bytes, APP_SUBMIT attempts.

These are not NetDevice-accepted bytes/copies or MAC airtime. No statistical
comparison, training, simulation, or plotting is performed by this tool.
"""
import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import sys


CONTROL_CLASSES = frozenset((
    "hello", "p2p_handshake", "search", "find", "neural_route", "neural_pit"))
CLASSES = CONTROL_CLASSES | {"business", "relay_data"}
REASONS = frozenset(("PREDICTIVE_EXTRA", "REACTIVE_RELAY", "REPEATED_SUBMIT"))
TERMINALS = frozenset(("DATA", "TIMEOUT", "NACK", "STOPPED"))
RAW_FILES = ("request-events.csv", "data-attempts.csv", "packet-l3.csv",
             "mobility-events.csv", "recorder-complete.json", "simulation-result.json",
             "effective-experiment-config.json")
HEADERS = {
    "request-events.csv": (
        "time_ns,event,request_id,name,vehicle_id,node_id,sequence,send_ns,deadline_ns,rsu_id"),
    "data-attempts.csv": (
        "time_ns,attempt_id,parent_attempt_id,name,source_node,target_node,reason,stage"),
    "packet-l3.csv": (
        "time_ns,node_id,face_id,direction,packet_type,name,semantic_class,wire_bytes,inner_data_bytes"),
    "mobility-events.csv": (
        "time_ns,event,vehicle_id,node_id,x,y,speed_mps,rsu_id,previous_rsu_id"),
}
MEASUREMENT_SCOPE = (
    "NDN L3 outgoing INTEREST+DATA wire bytes; NACK counts separate; "
    "application extra Data submission attempts, not device acceptance or MAC airtime")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Cannot read {}: {}".format(path, error))
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object: " + str(path))
    return value


def integer(value, label, minimum=0):
    if isinstance(value, bool):
        raise ValueError("Invalid integer " + label)
    try:
        parsed = int(str(value))
    except (ValueError, TypeError):
        raise ValueError("Invalid integer {}: {!r}".format(label, value))
    if parsed < minimum:
        raise ValueError("{} must be >= {}".format(label, minimum))
    return parsed


def seconds_ns(value):
    try:
        scaled = Decimal(str(value)) * 1000000000
        if not scaled.is_finite() or scaled != scaled.to_integral_value():
            raise ValueError("Time must be finite, with nanosecond precision")
        return int(scaled)
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid time: " + str(value))


def rows(path):
    path = Path(path)
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != HEADERS[path.name].split(","):
                raise ValueError("Unexpected CSV header: " + str(path))
            for index, row in enumerate(reader, 2):
                if None in row or any(value is None or (value == "" and not (
                        path.name == "data-attempts.csv" and key == "parent_attempt_id"))
                        for key, value in row.items()):
                    raise ValueError("Incomplete CSV row {}:{}".format(path, index))
                yield row
    except OSError as error:
        raise ValueError("Missing experiment log {}: {}".format(path, error))


def validate_manifest(run):
    manifest = read_json(run / "manifest.json")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
        raise ValueError("manifest must record a complete run")
    processes = manifest.get("processes", {})
    if processes.get("simulation", {}).get("returncode") != 0:
        raise ValueError("manifest lacks successful simulation exit")
    if manifest.get("strategy") == 3 and processes.get("controller", {}).get("returncode") != 0:
        raise ValueError("manifest lacks successful controller exit")
    expected = {"experiment.json"} | {"raw/" + name for name in RAW_FILES}
    recorded = manifest.get("artifact_hashes", {})
    if not expected.issubset(recorded):
        raise ValueError("manifest lacks required artifact hashes")
    for relative, digest in recorded.items():
        path = (run / relative).resolve()
        if run not in path.parents or not path.is_file() or sha256_file(path) != digest:
            raise ValueError("Artifact hash mismatch: " + relative)
    return manifest


def summarize_mobility(path, vehicles, start, end, drain):
    observations = {vehicle: [] for vehicle in vehicles}
    for row in rows(path):
        timestamp = integer(row["time_ns"], "mobility time")
        integer(row["node_id"], "mobility node")
        integer(row["rsu_id"], "mobility rsu", -1)
        integer(row["previous_rsu_id"], "mobility previous rsu", -1)
        if row["vehicle_id"] not in observations or row["event"] not in (
                "ENTER", "SAMPLE", "ASSOCIATION", "EXIT"):
            raise ValueError("Unknown mobility vehicle/event")
        for field in ("x", "y", "speed_mps"):
            try:
                finite = math.isfinite(float(row[field]))
            except ValueError:
                finite = False
            if not finite:
                raise ValueError("Nonfinite mobility " + field)
        if float(row["speed_mps"]) < 0:
            raise ValueError("Negative mobility speed")
        observations[row["vehicle_id"]].append((timestamp, row))
    weighted, stopped, time_total, maximum_gap = 0.0, 0, 0, 0
    speed_segments = []
    handovers = Counter()
    for vehicle, events in observations.items():
        events.sort(key=lambda item: item[0])
        entered = [time for time, row in events if row["event"] == "ENTER"]
        if len(entered) != 1 or entered[0] > start:
            raise ValueError("mobility vehicle not admitted before measurement: " + vehicle)
        if any(row["event"] == "EXIT" and time < drain for time, row in events):
            raise ValueError("mobility vehicle exited before drain completed: " + vehicle)
        samples = {}
        last_rsu = -1
        for timestamp, row in events:
            if row["event"] == "SAMPLE":
                samples[timestamp] = float(row["speed_mps"])
            rsu = int(row["rsu_id"])
            if row["event"] in ("SAMPLE", "ASSOCIATION") and rsu >= 0:
                if row["event"] == "ASSOCIATION" and start <= timestamp < end and (
                        last_rsu >= 0 and last_rsu != rsu):
                    handovers[vehicle] += 1
                last_rsu = rsu
        points = sorted(samples.items())
        if not points or points[0][0] > start or points[-1][0] < drain:
            raise ValueError("mobility SAMPLE log does not cover measurement and drain: " + vehicle)
        covered = 0
        for (left, speed), (right, _) in zip(points, points[1:]):
            length = max(0, min(right, end) - max(left, start))
            if length:
                weighted += speed * length
                time_total += length
                covered += length
                stopped += length if speed <= .1 else 0
                speed_segments.append((speed, length))
                maximum_gap = max(maximum_gap, right - left)
        if covered != end - start:
            raise ValueError("mobility SAMPLE intervals do not cover the measurement window")
    if not time_total:
        raise ValueError("No measured mobility vehicle-time")
    speed_segments.sort()

    def percentile(fraction):
        accumulated = 0
        for speed, weight in speed_segments:
            accumulated += weight
            if accumulated >= fraction * time_total:
                return speed
        return speed_segments[-1][0]

    return {
        "vehicle_count": len(vehicles),
        "mobility_event_count": sum(len(events) for events in observations.values()),
        "vehicle_time_weighted_speed_mps": weighted / time_total,
        "vehicle_time_weighted_speed_kmh": weighted / time_total * 3.6,
        "speed_time_weighted_p05_mps": percentile(.05),
        "speed_time_weighted_p50_mps": percentile(.5),
        "speed_time_weighted_p95_mps": percentile(.95),
        "stopped_vehicle_time_fraction": stopped / time_total,
        "stopped_speed_threshold_mps": .1,
        "speed_estimator": "time-weighted left-hold SAMPLE values over measurement interval",
        "maximum_measured_sample_gap_s": maximum_gap / 1000000000.0,
        "handover_count": sum(handovers.values()),
        "handovers_by_vehicle": {vehicle: handovers[vehicle] for vehicle in sorted(vehicles)},
    }


def summarize_run(run_dir, require_manifest=True):
    """Compute one run, refusing missing, ambiguous, or non-closing records."""
    run = Path(run_dir).resolve()
    manifest = validate_manifest(run) if require_manifest else None
    config = read_json(run / "experiment.json")
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported experiment schema")
    start, end, drain = (seconds_ns(config[key]) for key in (
        "measurement_start_s", "measurement_end_s", "drain_end_s"))
    if not (0 <= start < end and drain >= end + 3000000000):
        raise ValueError("Invalid measurement/drain window")
    completion = read_json(run / "raw/recorder-complete.json")
    if completion.get("schema_version") != 1 or completion.get("complete") is not True:
        raise ValueError("recorder completion marker is not complete")
    simulation = read_json(run / "raw/simulation-result.json")
    if simulation.get("schema_version") != 1 or simulation.get("complete") is not True:
        raise ValueError("simulation completion marker is not complete")
    if any(simulation.get(key) != config[key] for key in ("run_id", "scenario")) or (
            integer(simulation.get("expected_end_ns"), "expected end") != drain or
            integer(simulation.get("simulated_end_ns"), "simulated end") != drain + 1):
        raise ValueError("simulation completion does not match this run and end time")
    if integer(completion.get("final_time_ns"), "recorder final_time_ns") != drain + 1:
        raise ValueError("recorder final time does not match simulation completion")
    effective = read_json(run / "raw/effective-experiment-config.json")
    for key in ("schema_version", "run_id", "scenario", "sumo_config", "route_file",
                "request_plan", "output_dir", "seeds", "strategy"):
        if key in config and effective.get(key) != config[key]:
            raise ValueError("C++ effective config mismatch: " + key)
    for key, value in (("measurement_start_ns", start), ("measurement_end_ns", end),
                       ("drain_end_ns", drain)):
        if integer(effective.get(key), key) != value:
            raise ValueError("C++ effective config mismatch: " + key)

    generated, terminals = {}, {}
    outcome_counts, diagnostics = Counter(), Counter()
    success_sum = 0
    identity_fields = ("name", "vehicle_id", "node_id", "sequence", "send_ns", "deadline_ns")
    for row in rows(run / "raw/request-events.csv"):
        timestamp = integer(row["time_ns"], "request time_ns")
        send = integer(row["send_ns"], "send_ns")
        deadline = integer(row["deadline_ns"], "deadline_ns")
        sequence = integer(row["sequence"], "sequence", 1)
        integer(row["node_id"], "node_id")
        integer(row["rsu_id"], "rsu_id", -1)
        identity = row["request_id"]
        event = row["event"]
        if identity != "{}:{}".format(row["vehicle_id"], sequence):
            raise ValueError("request_id disagrees with vehicle/sequence")
        if not (start <= send < end and deadline == send + 3000000000):
            raise ValueError("Request outside cohort or inconsistent deadline")
        if not (send <= timestamp <= drain):
            raise ValueError("Request event outside observation interval")
        if event == "GENERATED":
            if identity in generated or timestamp != send:
                raise ValueError("Duplicate or inconsistent GENERATED event")
            generated[identity] = row
            continue
        if identity not in generated or any(
                row[key] != generated[identity][key] for key in identity_fields):
            raise ValueError("Event has no matching generated request: " + identity)
        if event in TERMINALS:
            if identity in terminals:
                raise ValueError("Multiple terminal events: " + identity)
            if event == "DATA" and timestamp > deadline:
                raise ValueError("Successful DATA after deadline")
            if event == "TIMEOUT" and timestamp < deadline:
                raise ValueError("TIMEOUT before deadline")
            terminals[identity] = event
            outcome_counts[event] += 1
            if event == "DATA":
                success_sum += timestamp - send
        elif event in ("DUPLICATE_DATA", "LATE_DATA", "POST_TERMINAL_DATA"):
            if event == "LATE_DATA" and timestamp <= deadline:
                raise ValueError("LATE_DATA before deadline")
            if event == "DUPLICATE_DATA" and terminals.get(identity) != "DATA":
                raise ValueError("DUPLICATE_DATA without an earlier success")
            if event == "POST_TERMINAL_DATA" and (
                    terminals.get(identity) not in ("NACK", "TIMEOUT", "STOPPED") or
                    timestamp > deadline or (
                    terminals.get(identity) == "TIMEOUT" and timestamp != deadline)):
                raise ValueError("POST_TERMINAL_DATA requires a prior failure within deadline")
            diagnostics[event] += 1
        else:
            raise ValueError("Unknown request event: " + event)
    if not generated or generated.keys() != terminals.keys():
        raise ValueError("Request cohort must be nonempty and terminal-closed")
    for key, expected in (("generated", len(generated)), ("terminal", len(terminals)),
                          ("planned", len(generated))):
        if integer(completion.get(key), "recorder " + key) != expected:
            raise ValueError("recorder count mismatch: " + key)
    if integer(effective.get("expected_requests"), "expected_requests") != len(generated):
        raise ValueError("C++ expected request count does not match generated cohort")
    vehicles = {row["vehicle_id"] for row in generated.values()}
    if not isinstance(effective.get("vehicle_ids"), list) or (
            len(set(effective["vehicle_ids"])) != len(effective["vehicle_ids"])) or (
            set(effective["vehicle_ids"]) != vehicles):
        raise ValueError("C++ planned vehicles do not match generated cohort")

    if "request_plan" in config:
        plan_path = Path(config["request_plan"])
        if not plan_path.is_absolute():
            plan_path = run / plan_path
        plan = read_json(plan_path)
        if plan.get("schema_version") != 1 or not isinstance(plan.get("requests"), list):
            raise ValueError("Invalid request plan")
        expected = {}
        for item in plan["requests"]:
            key = "{}:{}".format(item["vehicle_id"], integer(item["sequence"], "sequence", 1))
            if key in expected:
                raise ValueError("Duplicate request in plan")
            expected[key] = integer(item["send_time_ns"], "planned send_time_ns")
        if expected != {key: int(value["send_ns"]) for key, value in generated.items()}:
            raise ValueError("Generated cohort differs from the frozen request plan")

    mobility = summarize_mobility(
        run / "raw/mobility-events.csv", vehicles, start, end, drain)

    attempts, attempt_counts = set(), Counter()
    unknown_targets = 0
    names = {row["name"] for row in generated.values()}
    if len(names) != len(generated):
        raise ValueError("Generated business Names are not unique")
    for row in rows(run / "raw/data-attempts.csv"):
        timestamp = integer(row["time_ns"], "attempt time_ns")
        integer(row["source_node"], "attempt source")
        target = integer(row["target_node"], "attempt target", -1)
        if row["stage"] != "APP_SUBMIT" or row["reason"] not in REASONS:
            raise ValueError("Unknown attempt stage/reason")
        if row["attempt_id"] in attempts:
            raise ValueError("Duplicate attempt_id")
        if row["name"] not in names:
            raise ValueError("Extra attempt does not match a generated cohort Name")
        attempts.add(row["attempt_id"])
        if start <= timestamp < drain:
            attempt_counts[row["reason"]] += 1
            unknown_targets += target == -1
    if integer(completion.get("extra_attempts"), "recorder extra_attempts") != len(attempts):
        raise ValueError("recorder extra_attempts does not match all recorded attempt rows")

    byte_counts, packet_counts = Counter(), Counter()
    network = control = relay = relay_inner = nack_count = 0
    for row in rows(run / "raw/packet-l3.csv"):
        timestamp = integer(row["time_ns"], "L3 time")
        integer(row["node_id"], "L3 node")
        integer(row["face_id"], "L3 face")
        size = integer(row["wire_bytes"], "wire_bytes")
        inner = integer(row["inner_data_bytes"], "inner_data_bytes")
        category, packet_type = row["semantic_class"], row["packet_type"]
        if row["direction"] != "OUT" or category not in (CLASSES | {"native_nack"}):
            raise ValueError("Unknown L3 direction or semantic_class")
        if packet_type not in ("INTEREST", "DATA", "NACK"):
            raise ValueError("Unknown L3 packet type")
        if packet_type == "NACK":
            if category != "native_nack" or size or inner:
                raise ValueError("NACK must have zero bytes and be counted separately")
        elif size <= 0 or category == "native_nack":
            raise ValueError("INTEREST/DATA must have positive encoded bytes")
        if category == "relay_data":
            if packet_type != "DATA" or not (0 < inner < size):
                raise ValueError("Invalid relay inner/outer data lengths")
        elif inner != 0:
            raise ValueError("Unexpected inner_data_bytes outside relay_data")
        if not start <= timestamp < drain:
            continue
        if packet_type == "NACK":
            nack_count += 1
            continue
        network += size
        byte_counts[category] += size
        packet_counts[packet_type] += 1
        if category in CONTROL_CLASSES:
            control += size
        elif category == "relay_data":
            relay += size
            relay_inner += inner
    if network != sum(byte_counts.values()) or control > network:
        raise ValueError("Network byte partition does not close")

    count, success = len(generated), outcome_counts["DATA"]
    result = {
        "schema_version": 1, "measurement_scope": MEASUREMENT_SCOPE,
        "scenario": config["scenario"], "run_id": config["run_id"],
        "generated": count, "satisfied": success, "terminal_counts": dict(outcome_counts),
        "diagnostic_counts": dict(diagnostics), "isr_percent": 100.0 * success / count,
        "sum_success_rtt_ns": success_sum,
        "mean_success_rtt_ms": success_sum / success / 1000000.0 if success else None,
        "extra_data_app_attempts": sum(attempt_counts.values()),
        "unknown_target_app_attempts": unknown_targets,
        "extra_attempts_by_reason": dict(attempt_counts),
        "extra_attempts_per_interest": sum(attempt_counts.values()) / count,
        "network_l3_bytes": network, "control_l3_bytes": control,
        "relay_l3_bytes": relay, "relay_inner_data_bytes": relay_inner,
        "relay_encapsulation_bytes": relay - relay_inner,
        "l3_bytes_by_class": dict(byte_counts), "l3_packet_counts": dict(packet_counts),
        "out_nack_count": nack_count,
        "network_mbit": network * 8 / 1000000.0, "control_mbit": control * 8 / 1000000.0,
        "network_bytes_per_interest": network / count,
        "control_bytes_per_interest": control / count,
        "network_bytes_per_satisfied_interest": network / success if success else None,
        "measurement_start_ns": start, "measurement_end_ns": end, "drain_end_ns": drain,
    }
    result.update(mobility)
    if manifest is not None:
        result.update(block_id=manifest["block_id"], strategy=manifest["strategy"],
                      validation_only=manifest["validation_only"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = summarize_run(args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, KeyError, OSError) as error:
        print("Cannot summarize experiment: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
