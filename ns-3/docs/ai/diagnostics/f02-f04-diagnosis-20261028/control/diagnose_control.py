#!/usr/bin/env python3
"""Reconcile saved F03/F04 control subsets without simulation or source edits."""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'waf').is_file() and (p / 'contrib/vndn-nn-rd').is_dir())
OUT = Path(__file__).resolve().parent
FIGURES = ROOT / 'data/experiments/paper-figures-followup-20261026/figures-paper-20261026'
DETAILS = ROOT / 'data/experiments/quick-fixed-model-20261022/workflow/figures/all/attempt-001/analysis/run-details.json'
CONTROL = ('hello', 'p2p_handshake', 'search', 'find', 'neural_route', 'neural_pit')
CLASSES = CONTROL + ('business', 'relay_data')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open() as handle:
        return list(csv.DictReader(handle))


def write_csv(name, data):
    with (OUT / name).open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader(); writer.writerows(data)


def main():
    index = json.loads((FIGURES / 'figure-index.json').read_text())
    names = ['source-tables/aggregate.json', 'source-tables/run-metrics.csv',
             'source-tables/plot-summary.csv', 'baseline-decomposition.csv',
             'historical-control-packet-sizes.csv']
    hashes = {}
    for name in names:
        path = FIGURES / name
        digest = sha(path)
        assert digest == index['artifact_hashes'][name]
        hashes[str(path.relative_to(ROOT))] = digest
    aggregate = json.loads((FIGURES / 'source-tables/aggregate.json').read_text())
    assert sha(DETAILS) == aggregate['artifacts']['run-details.json']
    hashes[str(DETAILS.relative_to(ROOT))] = sha(DETAILS)
    runs = json.loads(DETAILS.read_text())['runs']
    lookup = {(r['scene'], r['condition_id'], r['strategy'], r['metric']): r
              for r in read_csv(FIGURES / 'source-tables/plot-summary.csv')}
    means, selected = [], []
    for scene in ['circle', 'grid', 'spidermap']:
        for k in [1500, 3000, 6000, 9000, 12000]:
            condition = 'baseline' if k == 6000 else 'n10-v30-k%d' % k
            for strategy in ['0', '1', '2', '3']:
                group = [r for r in runs if (r['scene'], r['condition_id'], r['strategy']) == (scene, condition, strategy)]
                assert len(group) == 2
                for r in group:
                    c = r['l3_bytes_by_class']
                    assert set(c) <= set(CLASSES)
                    assert sum(c.values()) == r['network_l3_bytes']
                    assert sum(c.get(key, 0) for key in CONTROL) == r['control_l3_bytes']
                    assert r['control_l3_bytes'] <= r['network_l3_bytes']
                    if strategy == '0':
                        assert r['control_l3_bytes'] == c.get('hello', 0)
                        assert r['relay_l3_bytes'] == 0
                    selected.append(dict(scene=scene, requests=k, strategy=strategy, seed=r['seed_family'],
                                         network_l3_bytes=r['network_l3_bytes'], control_l3_bytes=r['control_l3_bytes'],
                                         **{key+'_bytes': c.get(key, 0) for key in CLASSES}))
                values = {key+'_mbit': sum(r['l3_bytes_by_class'].get(key, 0) for r in group) * 4 / 1e6 for key in CLASSES}
                network = sum(r['network_l3_bytes'] for r in group) * 4 / 1e6
                control = sum(r['control_l3_bytes'] for r in group) * 4 / 1e6
                assert math.isclose(network, float(lookup[(scene, condition, strategy, 'network_mbit')]['estimate']), abs_tol=1e-9)
                assert math.isclose(control, float(lookup[(scene, condition, strategy, 'control_mbit')]['estimate']), abs_tol=1e-9)
                means.append(dict(scene=scene, requests=k, strategy=strategy, repetitions=2,
                                  network_mbit=network, control_mbit=control,
                                  control_fraction_percent=100*control/network,
                                  isr_percent=sum(r['isr_percent'] for r in group)/2,
                                  **values))
    packets = read_csv(FIGURES / 'historical-control-packet-sizes.csv')
    baseline = [r for r in packets if r['scenario']=='circle' and r['strategy'] in ['0','3']]
    for strategy in ['0', '3']:
        actual = sum(int(r['total']) for r in baseline if r['strategy']==strategy)*4/1e6
        expected = next(r['control_mbit'] for r in means if r['scene']=='circle' and r['requests']==6000 and r['strategy']==strategy)
        assert math.isclose(actual, expected, abs_tol=1e-9)
    for path, digest in hashes.items():
        assert sha(ROOT/path) == digest
    write_csv('control-network-runs.csv', selected)
    write_csv('control-network-means.csv', means)
    write_csv('circle-baseline-control-packet-sizes.csv', baseline)
    verification = {'status': 'passed', 'selected_runs': len(selected), 'mean_points': len(means),
                    'matching_f03_f04_values': len(means)*2, 'naive_control_all_hello': True,
                    'all_byte_partitions_close': True, 'all_sealed_sources_unchanged': True,
                    'source_sha256': hashes, 'script_sha256': sha(Path(__file__)),
                    'control_classes': CONTROL,
                    'scope': 'Network Face NDN L3 OUT INTEREST+DATA bytes, [20s,143.5s); no LP/MAC/retry bytes.',
                    'metric_relation': 'network = business + relay_data + control; control includes both hello request and response.'}
    (OUT/'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in verification.items() if k not in ['source_sha256','script_sha256']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
