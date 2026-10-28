#!/usr/bin/env python3
"""Read-only, streamed attribution of saved Spider F01 low/high load runs.

Only outputs under this script's directory; no simulation or source modification.
RSU upstream Interest OUT is explicitly a proxy, not a recorded RSU Interest RX.
"""
import argparse
import bisect
import collections
import csv
import hashlib
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'waf').is_file() and (p / 'contrib/vndn-nn-rd').is_dir())
OUT = Path(__file__).resolve().parent
DETAILS = ROOT / 'data/experiments/quick-fixed-model-20261022/workflow/figures/all/attempt-001/analysis/run-details.json'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def rows(path):
    with path.open() as stream:
        yield from csv.DictReader(stream)


def write_csv(name, records):
    fields = list(dict.fromkeys(k for r in records for k in r))
    with (OUT / name).open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def diagnose(run):
    raw = Path(run['run_path']) / 'raw'
    config = json.loads((raw / 'effective-experiment-config.json').read_text())
    assert config['scenario'] == run['scene']
    assert config['vehicle_ids'] == ['exp-%05d' % n for n in range(10)]
    log = (raw.parent / 'simulation.log').read_text()
    assert '# Road Side Units (RSUs): 7' in log
    assert '# nodes (vehicles) detected in SUMO scenario: 10' in log
    assert all(('Node %d: added Face id=257 uri=netdev://' % n) in log for n in range(17))
    selected = [raw / n for n in ('request-events.csv', 'packet-l3.csv', 'data-rx.csv', 'mobility-events.csv', 'neural-decisions.jsonl')]
    fingerprints = {str(p.relative_to(ROOT)): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in selected}
    manifest = json.loads((raw.parent / 'manifest.json').read_text())
    assert manifest['status'] == 'complete'
    for path, fp in fingerprints.items():
        key = str((ROOT / path).relative_to(raw.parent))
        assert fp['sha256'] == manifest['artifact_hashes'][key], 'Sealed source mismatch: ' + key
    requests, terminals = {}, {}
    diagnostics = collections.Counter()
    for row in rows(raw / 'request-events.csv'):
        if row['event'] == 'GENERATED':
            assert row['name'] not in requests
            requests[row['name']] = row
        elif row['event'] in {'DATA', 'TIMEOUT', 'NACK', 'STOPPED'}:
            assert row['name'] not in terminals
            terminals[row['name']] = row
        else:
            diagnostics[row['event']] += 1
    assert len(requests) == run['generated']
    assert set(requests) == set(terminals)
    assert dict(diagnostics) == run['diagnostic_counts']
    assert dict(collections.Counter(r['event'] for r in terminals.values())) == run['terminal_counts']
    assert {int(r['node_id']) for r in requests.values()} == set(range(7, 17))
    start, end = run['measurement_start_ns'], run['measurement_end_ns']
    stage_names = ['obu_interest_out', 'rsu_upstream_interest_out_proxy', 'server_data_out',
                   'any_rsu_complete_data_rx', 'source_rsu_complete_data_rx', 'rsu_wireless_data_out',
                   'target_obu_complete_data_rx', 'satisfied']
    stages = {name: set() for name in stage_names}
    event_counts = collections.Counter()
    directions = collections.Counter()
    unknown_business = collections.Counter()
    hello = collections.defaultdict(list)
    wire_faces = set()
    for row in rows(raw / 'packet-l3.csv'):
        node, face, t = int(row['node_id']), int(row['face_id']), int(row['time_ns'])
        directions[row['direction']] += 1
        assert row['direction'] == 'OUT', 'Unexpected RX trace: revise stage mapping'
        if row['semantic_class'] == 'hello' and row['packet_type'] == 'DATA' and 7 <= node <= 16:
            hello[node].append(t)
        if row['semantic_class'] != 'business':
            continue
        name = row['name']
        if name not in requests:
            unknown_business[row['packet_type']] += 1
            continue
        target = int(requests[name]['node_id'])
        stage = None
        if row['packet_type'] == 'INTEREST' and node == target:
            stage = 'obu_interest_out'
        elif row['packet_type'] == 'INTEREST' and 0 <= node <= 6:
            stage = 'rsu_upstream_interest_out_proxy'
        elif row['packet_type'] == 'DATA' and node == 18:
            stage = 'server_data_out'
        elif row['packet_type'] == 'DATA' and 0 <= node <= 6 and face == 257:
            stage = 'rsu_wireless_data_out'
            wire_faces.add(face)
        if stage:
            stages[stage].add(name)
            event_counts[stage] += 1
    receive_times = collections.defaultdict(list)
    for row in rows(raw / 'data-rx.csv'):
        name, node = row['name'], int(row['node_id'])
        if name not in requests:
            continue
        req = requests[name]
        if 0 <= node <= 6:
            stages['any_rsu_complete_data_rx'].add(name)
            event_counts['any_rsu_complete_data_rx'] += 1
            if node == int(req['rsu_id']):
                stages['source_rsu_complete_data_rx'].add(name)
                event_counts['source_rsu_complete_data_rx'] += 1
        if node == int(req['node_id']):
            stages['target_obu_complete_data_rx'].add(name)
            event_counts['target_obu_complete_data_rx'] += 1
            receive_times[name].append(int(row['time_ns']))
    for name, row in terminals.items():
        if row['event'] == 'DATA':
            stages['satisfied'].add(name)
    assert len(stages['satisfied']) == run['satisfied']
    assert stages['satisfied'] <= stages['target_obu_complete_data_rx']
    assert stages['obu_interest_out'] == set(requests)
    for ts in hello.values():
        ts.sort()
    decisions = collections.Counter()
    with (raw / 'neural-decisions.jsonl').open() as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                decisions[int(row['obu_node_id'])] += 1
    latest_associations = collections.defaultdict(list)
    positions = collections.defaultdict(list)
    for row in rows(raw / 'mobility-events.csv'):
        node = int(row['node_id'])
        if row['event'] == 'ASSOCIATION':
            latest_associations[node].append({'time_ns': int(row['time_ns']), 'rsu_id': int(row['rsu_id'])})
        if row['event'] == 'SAMPLE' and start <= int(row['time_ns']) < end:
            positions[node].append((float(row['x']), float(row['y']), int(row['rsu_id'])))
    vehicle, timebins = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    missing, failed_reached = collections.Counter(), collections.Counter()
    ordered = [n for n in stage_names if n not in ['source_rsu_complete_data_rx', 'satisfied']]
    for name, req in requests.items():
        node, sent = int(req['node_id']), int(req['send_ns'])
        v = vehicle[node]
        groups = [v, timebins[(sent // 10**10) * 10]]
        for group in groups:
            group['generated'] += 1
            for stage in stage_names:
                group[stage] += int(name in stages[stage])
            group['rsu_id_negative_at_send'] += int(int(req['rsu_id']) < 0)
        # Packet collection starts at 20s: do not infer pre-window hello history.
        if sent >= start + 2_000_000_000:
            i = bisect.bisect_right(hello[node], sent)
            no_recent_reply = i == 0 or sent - hello[node][i - 1] > 2_000_000_000
            for group in groups:
                group['hello_reply_freshness_observable_requests'] += 1
                group['no_observed_hello_reply_in_prior_2s'] += int(no_recent_reply)
                group['failed_and_no_observed_hello_reply_in_prior_2s'] += int(no_recent_reply and name not in stages['satisfied'])
        if name not in stages['satisfied']:
            failed_reached.update(n for n in stage_names if name in stages[n])
            missing[next((n for n in ordered if name not in stages[n]), 'received_but_not_satisfied')] += 1
    ident = {'scene': run['scene'], 'condition': run['condition_id'], 'seed': run['seed_family'], 'strategy': run['strategy']}
    vehicle_rows = []
    for node, counts in sorted(vehicle.items()):
        p = positions[node]
        history = latest_associations[node]
        vehicle_rows.append(dict(ident, node=node, vehicle_id='exp-%05d' % (node - 7), **dict(counts),
                                 hello_reply_out_events=len(hello[node]),
                                 hello_reply_first_ns=hello[node][0] if hello[node] else None,
                                 hello_reply_last_ns=hello[node][-1] if hello[node] else None,
                                 neural_decision_events=decisions[node],
                                 association_changes_in_measurement=sum(start <= a['time_ns'] < end for a in history),
                                 last_association_ns=history[-1]['time_ns'] if history else None,
                                 last_association_rsu=history[-1]['rsu_id'] if history else None,
                                 x_min=min(x[0] for x in p), x_max=max(x[0] for x in p),
                                 y_min=min(x[1] for x in p), y_max=max(x[1] for x in p)))
    ordered_chain = [n for n in stage_names if n != 'source_rsu_complete_data_rx']
    non_nested = {a+'->'+b: len(stages[b] - stages[a]) for a, b in zip(ordered_chain, ordered_chain[1:])}
    late_received = [(name, min(ts)) for name, ts in receive_times.items() if name not in stages['satisfied']]
    delays = [(time-int(requests[name]['send_ns']))/1e6 for name, time in late_received]
    late_summary = {'count': len(late_received),
                    'first_complete_rx_at_or_before_deadline': sum(time <= int(requests[name]['deadline_ns']) for name, time in late_received),
                    'first_complete_rx_min_delay_ms': min(delays) if delays else None,
                    'first_complete_rx_max_delay_ms': max(delays) if delays else None}
    # Confirm inputs were unchanged by read-only analysis.
    for path, fp in fingerprints.items():
        assert sha(ROOT / path) == fp['sha256']
    return dict(ident, generated=run['generated'], satisfied=run['satisfied'], isr_percent=run['isr_percent'],
                unique_requests_by_stage={n: len(v) for n, v in stages.items()},
                packet_events_by_stage=dict(event_counts), failed_first_unobserved_stage=dict(missing),
                failed_requests_observed_by_stage=dict(failed_reached), non_nested_stage_counts=non_nested,
                complete_rx_but_unsatisfied=late_summary,
                direction_event_counts=dict(directions), unmatched_business_out_events=dict(unknown_business),
                rsu_wireless_faces=sorted(wire_faces), run_path=run['run_path'], input_fingerprints=fingerprints,
                all_inputs_match_sealed_manifest=True, diagnostic_counts=dict(diagnostics),
                terminal_counts=dict(collections.Counter(r['event'] for r in terminals.values()))), vehicle_rows, [dict(ident, bin_start_s=b, **dict(c)) for b,c in sorted(timebins.items())]


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['spidermap', 'grid'], default='spidermap')
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.output.resolve()
    assert not (OUT == ROOT / 'data' or ROOT / 'data' in OUT.parents), 'Do not write into original data'
    OUT.mkdir(parents=True, exist_ok=True)
    runs = json.loads(DETAILS.read_text())['runs']
    selected = [r for r in runs if r['scene'] == args.scenario and r['condition_id'] in ['n10-v30-k1500', 'n10-v30-k12000']]
    assert len(selected) == 16
    results, vehicles, bins = [], [], []
    for run in selected:
        result, vehicle, time = diagnose(run)
        results.append(result); vehicles.extend(vehicle); bins.extend(time)
        print(result['condition'], result['seed'], result['strategy'], result['unique_requests_by_stage'], flush=True)
    payload = {'schema_version': 1, 'source_details': str(DETAILS), 'source_details_sha256': sha(DETAILS),
               'script_sha256': sha(Path(__file__)), 'runs': results,
               'definitions': {
                   'counts': 'Unique generated business request names per stage; event counts separate.',
                   'rsu_interest': 'No Interest RX collector exists. RSU upstream OUT proves forwarding, absence does not prove absence of reception.',
                   'data_rx': 'Saved network-face complete Data ingress; does not alone imply application satisfaction.',
                   'hello': 'Only OBU hello response DATA OUT observed after 20s; no per-hello input trace or MAC target in saved CSV.',
                   'radio': 'No MAC attempts, retry reasons, signal samples or airtime counters: loss mechanism not proven by L3 absence.',
                   'freshness': 'No observed OBU hello DATA response in preceding 2s; only requests >=22s used to avoid left censoring.',
                   'source_rsu': 'GENERATED.rsu_id; may be stale, is not proof of current coverage.',
                   'failures': 'Earliest unobserved stage for failed requests is descriptive, not a causal attribution.'}}
    prefix = 'spider' if args.scenario == 'spidermap' else args.scenario
    (OUT / (prefix + '-funnel.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    write_csv('vehicle-funnel.csv', vehicles)
    write_csv('time-bin-funnel.csv', bins)
    write_csv('run-funnel.csv', [dict({k:r[k] for k in ['scene','condition','seed','strategy','generated','satisfied','isr_percent']}, **r['unique_requests_by_stage']) for r in results])


if __name__ == '__main__':
    main()
