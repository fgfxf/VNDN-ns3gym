#!/usr/bin/env python3
"""Read-only F01 cohort audit; writes derived evidence, never edits inputs."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(project, output):
    project, output = project.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    campaign = project / 'data/experiments/quick-fixed-model-20261022'
    analysis = campaign / 'workflow/figures/all/attempt-001/analysis'
    figures = project / 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026'
    aggregate = read(analysis / 'aggregate.json')
    assert sha(analysis / 'run-details.json') == aggregate['artifacts']['run-details.json']
    assert sha(analysis / 'aggregate.json') == sha(figures / 'source-tables/aggregate.json')
    selected = [r for r in read(analysis / 'run-details.json')['runs']
                if r['condition_id'] in aggregate['scans']['interest']]
    assert len(selected) == 120
    provenance = {}
    runs, vehicles, bins = [], [], []
    signatures = defaultdict(set)
    request_plans = defaultdict(set)
    total_requests = 0
    for index, run in enumerate(selected):
        folder = Path(run['run_path'])
        manifest = read(folder / 'manifest.json')
        assert sha(folder / 'manifest.json') == run['manifest_sha256']
        provenance[str(folder / 'manifest.json')] = run['manifest_sha256']
        for relative in ('raw/request-events.csv', 'raw/mobility-events.csv', 'raw/effective-experiment-config.json'):
            path = folder / relative
            actual = sha(path)
            assert actual == manifest['artifact_hashes'][relative], str(path)
            provenance[str(path)] = actual
        for name, expected in manifest['input_hashes'].items():
            if name not in provenance:
                assert sha(name) == expected, name
                provenance[name] = expected
            assert provenance[name] == expected
            if name.endswith('/request-plan.json'):
                request_plans[run['scene'], run['condition_id'], run['seed_family']].add(expected)
        generated, terminals = {}, {}
        diagnostics = Counter()
        with (folder / 'raw/request-events.csv').open() as stream:
            for row in csv.DictReader(stream):
                identity = row['request_id']
                if row['event'] == 'GENERATED':
                    assert identity not in generated
                    assert int(row['deadline_ns']) - int(row['send_ns']) == 3_000_000_000
                    generated[identity] = row
                elif row['event'] in ('DATA', 'TIMEOUT', 'NACK', 'STOPPED'):
                    assert identity in generated and identity not in terminals
                    terminals[identity] = row
                    if row['event'] == 'DATA':
                        assert int(row['time_ns']) <= int(row['deadline_ns'])
                else:
                    diagnostics[row['event']] += 1
        assert set(generated) == set(terminals)
        outcomes = Counter(row['event'] for row in terminals.values())
        assert len(generated) == run['generated']
        assert outcomes['DATA'] == run['satisfied']
        assert dict(outcomes) == run['terminal_counts']
        assert dict(diagnostics) == run['diagnostic_counts']
        assert math.isclose(100 * outcomes['DATA'] / len(generated), run['isr_percent'], abs_tol=1e-12)
        total_requests += len(generated)
        base = {key: run[key] for key in ('scene', 'condition_id', 'strategy', 'seed_family')}
        groups, timegroups = defaultdict(Counter), defaultdict(Counter)
        no_rsu = 0
        for identity, row in generated.items():
            outcome = terminals[identity]['event']
            no_rsu += int(int(row['rsu_id']) < 0)
            bucket = (int(row['send_ns']) - run['measurement_start_ns']) // 20_000_000_000
            for counter in (groups[row['vehicle_id']], timegroups[bucket]):
                counter['generated'] += 1
                counter['satisfied'] += int(outcome == 'DATA')
                counter['send_rsu_missing'] += int(int(row['rsu_id']) < 0)
        signature = hashlib.sha256()
        associations = Counter()
        with (folder / 'raw/mobility-events.csv').open() as stream:
            for row in csv.DictReader(stream):
                if row['event'] == 'SAMPLE':
                    signature.update(json.dumps([row[k] for k in ('time_ns', 'vehicle_id', 'x', 'y', 'speed_mps')],
                                                separators=(',', ':')).encode())
                elif row['event'] == 'ASSOCIATION':
                    associations[row['vehicle_id']] += 1
        mobility_sha = signature.hexdigest()
        signatures[run['scene'], run['seed_family']].add(mobility_sha)
        runs.append(dict(base, generated=len(generated), satisfied=outcomes['DATA'],
                         isr_percent=run['isr_percent'], send_rsu_missing=no_rsu,
                         network_mbit=run['network_mbit'], rtt_ms=run['mean_success_rtt_ms'],
                         mobility_signature=mobility_sha, run_path=str(folder)))
        for vehicle, c in sorted(groups.items()):
            vehicles.append(dict(base, vehicle_id=vehicle, **dict(c),
                                 isr_percent=100 * c['satisfied'] / c['generated'],
                                 association_events=associations[vehicle]))
        for bucket, c in sorted(timegroups.items()):
            bins.append(dict(base, start_s=20 + bucket * 20, end_s=40 + bucket * 20, **dict(c),
                             isr_percent=100 * c['satisfied'] / c['generated']))
        if (index + 1) % 20 == 0:
            print('Verified {}/120 runs'.format(index + 1), flush=True)
    assert all(len(value) == 1 for value in request_plans.values())
    points = []
    for point in aggregate['points']:
        if point['metric'] != 'isr_percent' or point['condition_id'] not in aggregate['scans']['interest']:
            continue
        matches = [r for r in runs if all(r[key] == point[key] for key in ('scene', 'condition_id', 'strategy'))]
        assert len(matches) == 2
        actual = sum(r['satisfied'] for r in matches) / sum(r['generated'] for r in matches) * 100
        assert math.isclose(actual, point['estimate'], abs_tol=1e-12)
        points.append(dict(scene=point['scene'], condition_id=point['condition_id'], strategy=point['strategy'],
                           estimate=point['estimate'], run_sd=point['run_sd'], generated=sum(r['generated'] for r in matches),
                           satisfied=sum(r['satisfied'] for r in matches)))
    for name, rows in [('run-overview.csv', runs), ('per-vehicle.csv', vehicles),
                       ('time-bins-20s.csv', bins), ('f01-points.csv', points)]:
        write_csv(output / name, rows)
    report = dict(status='pass', runs=len(runs), requests=total_requests, plotted_points=len(points),
                  paired_request_plan_groups=len(request_plans), all_four_strategies_same_plan=True,
                  mobility_signatures=[dict(scene=key[0], seed_family=key[1], distinct=len(value),
                                             hashes=sorted(value)) for key, value in signatures.items()],
                  source_hashes=provenance, note='Identical geometry does not imply identical association or radio reception.')
    (output / 'overview-report.json').write_text(json.dumps(report, indent=2) + '\n')
    for name, expected in provenance.items():
        assert sha(name) == expected, 'Input changed during audit: ' + name
    print(json.dumps({k: v for k, v in report.items() if k not in ('source_hashes', 'mobility_signatures')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    main(arguments.project, arguments.output)
