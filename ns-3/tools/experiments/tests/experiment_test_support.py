"""Small deterministic logs for experiment tool behavioral tests."""
import csv
import json
from pathlib import Path


REQUEST_FIELDS = (
    "time_ns,event,request_id,name,vehicle_id,node_id,sequence,send_ns,deadline_ns,rsu_id"
).split(",")
ATTEMPT_FIELDS = (
    "time_ns,attempt_id,parent_attempt_id,name,source_node,target_node,reason,stage"
).split(",")
PACKET_FIELDS = (
    "time_ns,node_id,face_id,direction,packet_type,name,semantic_class,wire_bytes,inner_data_bytes"
).split(",")
MOBILITY_FIELDS = (
    "time_ns,event,vehicle_id,node_id,x,y,speed_mps,rsu_id,previous_rsu_id"
).split(",")


def write_csv(path, fields, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)


def valid_run(path, all_timeout=False, preserve_config=False):
    """Four requests: one success, timeout, Nack, and stopped request."""
    path = Path(path)
    raw = path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1, "scenario": "circle", "run_id": path.name,
        "measurement_start_s": 1, "measurement_end_s": 2, "drain_end_s": 5.5,
    }
    if not preserve_config:
        (path / "experiment.json").write_text(json.dumps(config), encoding="utf-8")
    else:
        config = json.loads((path / "experiment.json").read_text())
    rows = []
    for sequence, terminal in enumerate(
            ("TIMEOUT",) * 4 if all_timeout else ("DATA", "TIMEOUT", "NACK", "STOPPED"), 1):
        send = 1000000000 + sequence * 10000000
        base = ["veh0:" + str(sequence), "/com/baidu/" + str(sequence),
                "veh0", 2, sequence, send, send + 3000000000, 0]
        rows.append([send, "GENERATED"] + base)
        end = send + (3000000000 if terminal == "TIMEOUT" else 100000000)
        rows.append([end, terminal] + base)
    write_csv(raw / "request-events.csv", REQUEST_FIELDS, rows)
    write_csv(raw / "data-attempts.csv", ATTEMPT_FIELDS, [
        [1200000000, "extra-1", "primary-1", "/com/baidu/1", 4, 1,
         "PREDICTIVE_EXTRA", "APP_SUBMIT"],
        [1250000000, "extra-2", "primary-2", "/com/baidu/2", 0, 1,
         "REACTIVE_RELAY", "APP_SUBMIT"],
    ])
    write_csv(raw / "packet-l3.csv", PACKET_FIELDS, [
        [1100000000, 2, 257, "OUT", "INTEREST", "/com/baidu/1", "business", 40, 0],
        [1200000000, 4, 258, "OUT", "DATA", "/com/baidu/1", "business", 100, 0],
        [1250000000, 0, 258, "OUT", "DATA", "/vndn/control/rsu-relay/forward/1",
         "relay_data", 130, 100],
        [1300000000, 0, 257, "OUT", "INTEREST", "/vndn/control/hello", "hello", 20, 0],
        [1300000001, 2, 257, "OUT", "DATA", "/vndn/control/hello", "hello", 30, 0],
        [1300000002, 4, 258, "OUT", "DATA", "/vndn/control/neural-pit", "neural_pit", 80, 0],
        [1400000000, 2, 257, "OUT", "NACK", "/com/baidu/3", "native_nack", 0, 0],
        # A send after t1 is still part of the drain interval.
        [2100000000, 1, 257, "OUT", "DATA", "/com/baidu/1", "business", 100, 0],
    ])
    write_csv(raw / "mobility-events.csv", MOBILITY_FIELDS, [
        [0, "ENTER", "veh0", 2, 1, 2, 5, -1, -1],
        [1000000000, "SAMPLE", "veh0", 2, 1, 2, 5, 0, -1],
        [1500000000, "ASSOCIATION", "veh0", 2, 1, 2, 5, 1, 0],
        [2000000000, "SAMPLE", "veh0", 2, 1, 2, 5, 1, 0],
        [5500000000, "SAMPLE", "veh0", 2, 1, 2, 5, 1, 0],
    ])
    (raw / "recorder-complete.json").write_text(json.dumps({
        "schema_version": 1, "complete": True, "generated": 4, "terminal": 4,
        "planned": 4, "extra_attempts": 2, "final_time_ns": 5500000001,
    }), encoding="utf-8")
    (raw / "simulation-result.json").write_text(json.dumps({
        "schema_version": 1, "run_id": config["run_id"], "scenario": config["scenario"],
        "complete": True, "simulated_end_ns": 5500000001, "expected_end_ns": 5500000000,
    }), encoding="utf-8")
    effective = {key: config[key] for key in (
        "schema_version", "run_id", "scenario", "sumo_config", "route_file",
        "request_plan", "output_dir", "seeds", "strategy") if key in config}
    effective.update(measurement_start_ns=1000000000, measurement_end_ns=2000000000,
                     drain_end_ns=5500000000, vehicle_ids=["veh0"], expected_requests=4)
    (raw / "effective-experiment-config.json").write_text(json.dumps(effective), encoding="utf-8")
    return path
