#!/usr/bin/env python3.8
"""Generate immutable, explicit SUMO vehicles and exact VNDN request schedules.

This prepares inputs, not a simulation or a claim that traffic can attain its
configured speed. Actual admission, speed and handovers must be checked in each
run. Existing trace resources and existing output directories are never changed.
"""

import argparse
from collections import deque
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import xml.etree.ElementTree as ET


SCENARIOS = {
    "circle": ("circle-simple", "circle.net.xml", "circle.rou.xml"),
    "grid": ("grid-vanet-test", "map.net.xml", "passenger_routes.rou.xml"),
    "spidermap": ("fgfxf-spider-map", "map.net.xml", "passenger_routes.rou.xml"),
}


def _nanoseconds(value, field):
    try:
        exact = Decimal(str(value)) * 1_000_000_000
        if not exact.is_finite() or exact < 0 or exact != exact.to_integral_value():
            raise ValueError("{} must be nonnegative and representable in nanoseconds".format(field))
        result = int(exact)
        if result > 2**63 - 1:
            raise ValueError("{} exceeds ns-3 time range".format(field))
        return result
    except (InvalidOperation, TypeError) as error:
        raise ValueError("invalid {}".format(field)) from error


def _positive_integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("{} must be a positive integer".format(field))
    return value


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _close_route(route, connections):
    """Close a route using actual SUMO edge-to-edge connections, never teleport."""
    for first, second in zip(route, route[1:]):
        if second not in connections.get(first, ()):
            raise ValueError("source route has no legal connection {} -> {}".format(first, second))
    if route[0] in connections.get(route[-1], ()):
        return list(route)
    queue = deque([(route[-1], [])])
    visited = {route[-1]}
    while queue:
        edge, path = queue.popleft()
        for successor in sorted(connections.get(edge, ())):
            if successor == route[0]:
                return list(route) + path
            if successor not in visited:
                visited.add(successor)
                queue.append((successor, path + [successor]))
    raise ValueError("source route cannot be closed using legal road connections")


def _source_routes(route_root):
    named = {item.attrib["id"]: item.attrib["edges"].split()
             for item in route_root.findall("route")}
    vehicle_types = {item.attrib["id"]: item for item in route_root.findall("vType")}
    routes = []
    for vehicle in route_root.findall("vehicle"):
        embedded = vehicle.find("route")
        edges = (embedded.attrib["edges"].split() if embedded is not None
                 else named[vehicle.attrib["route"]])
        original_type = vehicle_types.get(vehicle.attrib.get("type"))
        routes.append((edges, original_type))
    if not routes:
        raise ValueError("source route must contain explicit vehicles")
    return routes


def generate_inputs(*, scenario, output_dir, vehicles, speed_kmh, requests,
                    measurement_start=20.0, measurement_duration=300.0,
                    drain_seconds=3.5, seed=1, ns3_root=None):
    """Return paths to a generated experiment template and its input summary."""
    if scenario not in SCENARIOS:
        raise ValueError("scenario must be circle, grid or spidermap")
    vehicles = _positive_integer(vehicles, "vehicles")
    requests = _positive_integer(requests, "requests")
    seed = _positive_integer(seed, "seed")
    if seed > 2**31 - 1:
        raise ValueError("seed exceeds the supported SUMO seed range")
    if requests < vehicles:
        raise ValueError("each experimental vehicle must generate at least one request")
    if not math.isfinite(speed_kmh) or speed_kmh <= 0:
        raise ValueError("speed_kmh must be finite and positive")
    start_ns = _nanoseconds(measurement_start, "measurement_start")
    duration_ns = _nanoseconds(measurement_duration, "measurement_duration")
    drain_ns = _nanoseconds(drain_seconds, "drain_seconds")
    if duration_ns == 0 or drain_ns < 3_000_000_000:
        raise ValueError("measurement duration must be positive and drain at least 3 seconds")
    end_ns = start_ns + duration_ns
    stop_ns = end_ns + drain_ns
    if stop_ns > 2**63 - 1:
        raise ValueError("end of experiment exceeds ns-3 time range")
    if (requests + vehicles - 1) // vehicles > duration_ns:
        raise ValueError("request rate exceeds one request per vehicle per nanosecond")

    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError("refusing to overwrite {}".format(output))
    project = Path(ns3_root).resolve() if ns3_root else Path(__file__).resolve().parents[2]
    scene_directory, net_name, route_name = SCENARIOS[scenario]
    source = project / "contrib" / "vndn-nn-rd" / "traces" / scene_directory
    network = ET.parse(source / net_name).getroot()
    route_root = ET.parse(source / route_name).getroot()
    edges = {item.attrib["id"]: item for item in network.findall("edge")
             if item.attrib.get("function") != "internal"}
    lengths = {name: float(item.find("lane").attrib["length"])
               for name, item in edges.items()}
    connections = {}
    for item in network.findall("connection"):
        first, second = item.attrib["from"], item.attrib["to"]
        if first in edges and second in edges:
            connections.setdefault(first, set()).add(second)
    sources = _source_routes(route_root)
    closed = [(_close_route(route, connections), original_type)
              for route, original_type in sources]
    random_source = random.Random(seed)
    new_routes = ET.Element("routes")
    planned_vehicles = []
    speed_mps = speed_kmh / 3.6
    # Keep enough remaining distance at maxSpeed, including after a free
    # insertion position skips part of the first edge. This does not guarantee
    # that SUMO admits all vehicles before t0, which the runtime must verify.
    minimum_distance = speed_mps * (stop_ns / 1e9) + max(10.0, speed_mps)
    for index in range(vehicles):
        cycle, source_type = closed[index % len(closed)]
        offset = random_source.randrange(len(cycle))
        cycle = cycle[offset:] + cycle[:offset]
        cycle_length = sum(lengths[edge] for edge in cycle)
        if cycle_length <= 0:
            raise ValueError("route has no positive road length")
        required_distance = minimum_distance + lengths[cycle[0]]
        repeat = max(1, math.floor(required_distance / cycle_length) + 1)
        route = cycle * repeat
        vehicle_id = "exp-{:05d}".format(index)
        type_id = "experiment-type-{:05d}".format(index)
        vehicle_type = (copy.deepcopy(source_type) if source_type is not None
                        else ET.Element("vType", {"vClass": "passenger"}))
        vehicle_type.attrib.update(id=type_id, maxSpeed=format(speed_mps, ".15g"),
                                   speedFactor="1", speedDev="0")
        new_routes.append(vehicle_type)
        vehicle = ET.SubElement(new_routes, "vehicle",
                                {"id": vehicle_id, "type": type_id, "depart": "0",
                                 "departLane": "best", "departPos": "free",
                                 "departSpeed": "0"})
        ET.SubElement(vehicle, "route", {"edges": " ".join(route)})
        planned_vehicles.append({"vehicle_id": vehicle_id,
                                 "source_route_index": index % len(closed),
                                 "route_length_m": sum(lengths[edge] for edge in route)})

    plan = []
    quotient, remainder = divmod(requests, vehicles)
    for index, vehicle in enumerate(planned_vehicles):
        count = quotient + (index < remainder)
        # A reproducible phase spreads traffic without turning nominal rate into
        # a random number of requests. Integer arithmetic preserves boundaries.
        phase = random_source.randrange(1_000_000)
        for sequence in range(1, count + 1):
            relative = ((sequence - 1) * 1_000_000 + phase) * duration_ns // (count * 1_000_000)
            plan.append({"vehicle_id": vehicle["vehicle_id"], "sequence": sequence,
                         "send_time_ns": start_ns + relative})
    plan.sort(key=lambda item: (item["send_time_ns"], item["vehicle_id"], item["sequence"]))

    sumo = ET.Element("configuration")
    inputs = ET.SubElement(sumo, "input")
    ET.SubElement(inputs, "net-file", {"value": "network.net.xml"})
    ET.SubElement(inputs, "route-files", {"value": "routes.rou.xml"})
    time = ET.SubElement(sumo, "time")
    ET.SubElement(time, "begin", {"value": "0"})
    ET.SubElement(time, "end", {"value": format(stop_ns / 1e9 + 1, ".9f")})
    processing = ET.SubElement(sumo, "processing")
    ET.SubElement(processing, "time-to-teleport", {"value": "-1"})

    config = {
        "schema_version": 1, "scenario": scenario, "run_id": "input-template",
        "sumo_config": "simulation.sumocfg", "route_file": "routes.rou.xml",
        "request_plan": "request-plan.json", "output_dir": "unassigned-run-output",
        "measurement_start_s": start_ns / 1e9, "measurement_end_s": end_ns / 1e9,
        "drain_end_s": stop_ns / 1e9,
        "seeds": {"rng_seed": 1, "rng_run": seed, "sumo_seed": seed, "srand_seed": seed},
        "input_files": ["network.net.xml", "routes.rou.xml", "simulation.sumocfg",
                        "request-plan.json", "input-summary.json"],
    }
    summary = {
        "schema_version": 1, "scenario": scenario, "vehicles": planned_vehicles,
        "requested_speed_kmh": speed_kmh, "requested_count": requests,
        "source_network": str(source / net_name),
        "source_routes": str(source / route_name),
        "source_network_sha256": hashlib.sha256((source / net_name).read_bytes()).hexdigest(),
        "source_routes_sha256": hashlib.sha256((source / route_name).read_bytes()).hexdigest(),
        "seed": seed,
        "limitations": ["Actual speed, admission before t0 and handover coverage require runtime validation.",
                        "Routes are closed and extended; this is a new experimental mobility input.",
                        "Route families follow source inputs, so full RSU coverage is not guaranteed."],
    }
    output.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copyfile(source / net_name, output / "network.net.xml")
        ET.ElementTree(new_routes).write(str(output / "routes.rou.xml"), encoding="UTF-8",
                                        xml_declaration=True)
        ET.ElementTree(sumo).write(str(output / "simulation.sumocfg"), encoding="UTF-8",
                                  xml_declaration=True)
        _write_json(output / "request-plan.json", {"schema_version": 1, "requests": plan})
        _write_json(output / "input-summary.json", summary)
        _write_json(output / "experiment-template.json", config)
    except Exception:
        # Only this newly created directory is ours to remove.
        shutil.rmtree(str(output))
        raise
    return {"experiment_config": str(output / "experiment-template.json"),
            "input_summary": str(output / "input-summary.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--vehicles", type=int, required=True)
    parser.add_argument("--speed-kmh", type=float, required=True)
    parser.add_argument("--requests", type=int, required=True)
    parser.add_argument("--measurement-start", type=float, default=20.0)
    parser.add_argument("--measurement-duration", type=float, default=300.0)
    parser.add_argument("--drain-seconds", type=float, default=3.5)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ns3-root", type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = generate_inputs(**vars(arguments))
    except (ValueError, OSError, ET.ParseError) as error:
        parser.exit(2, "generate_inputs: {}\n".format(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
