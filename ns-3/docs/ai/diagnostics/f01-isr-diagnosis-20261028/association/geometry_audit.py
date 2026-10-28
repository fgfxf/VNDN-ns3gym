"""Read-only geometry evidence, not a packet reception or ISR estimator.

Run from ns-3: python3.8 build/validation/f01-isr-diagnosis-20261028/association/geometry_audit.py
Uses actual recorded 0.1 s positions; no new SUMO/ns-3 execution.
"""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
OUT = ROOT / 'build/validation/f01-isr-diagnosis-20261028/association'
BATCH = ROOT / 'data/experiments/quick-fixed-model-20261022'
WAVELENGTH = 299792458.0 / 5.150e9
RADIO = {'grid': (12.0, -69.8), 'spidermap': (13.0, -69.8)}
TRACES = {'grid': 'grid-vanet-test', 'spidermap': 'fgfxf-spider-map'}
RSU_Z, OBU_Z, HEIGHT = 12.0, 1.5, 1.5


def rx_power(tx, distance):
    # Faithfully transcribed necessary geometric condition from this repository's
    # TwoRayGroundPropagationLossModel; does not include interference/MAC drops.
    if distance <= 50.0:
        return tx
    crossover = 4.0 * math.pi * (RSU_Z + HEIGHT) * (OBU_Z + HEIGHT) / WAVELENGTH
    if distance <= crossover:
        return tx + 10.0 * math.log10(WAVELENGTH ** 2 / (16.0 * math.pi ** 2 * distance ** 2))
    return tx + 10.0 * math.log10(((RSU_Z + HEIGHT) * (OBU_Z + HEIGHT)) ** 2 / distance ** 4)


def main():
    assert rx_power(13.0, 50.0) == 13.0
    assert rx_power(13.0, 50.001) < -60.0
    result = {'scope': 'grid/spider F01, 40 completed runs each', 'caveat':
              'Recorded samples, not exact request instants. Within sensitivity distance is necessary, not sufficient, for reception. No fading/interference/MAC inference.',
              'constants': {'frequency_hz': 5.15e9, 'min_distance_m': 50.0,
                            'rsu_z_m': RSU_Z, 'obu_z_m': OBU_Z, 'antenna_above_z_m': HEIGHT},
              'radio': {}, 'source_checks': {}, 'trajectory_groups': {}, 'runs': []}
    positions = {}
    for scene, (tx, threshold) in RADIO.items():
        path = ROOT / ('contrib/vndn-nn-rd/traces/' + TRACES[scene] + '/settings.xml')
        positions[scene] = [(float(x.get('centerX')), float(x.get('centerY'))) for x in ET.parse(path).findall('.//decal') if x.get('type') == 'rsu']
        distance = WAVELENGTH / (4.0 * math.pi) * 10.0 ** ((tx - threshold) / 20.0)
        assert math.isclose(rx_power(tx, distance), threshold)
        result['radio'][scene] = {'tx_dbm': tx, 'sensitivity_dbm': threshold,
                                  'max_distance_3d_m': distance,
                                  'max_distance_horizontal_m': math.sqrt(distance ** 2 - (RSU_Z - OBU_Z) ** 2),
                                  'rsu_xy': positions[scene]}
    source_paths = ['contrib/ndn4ivc/helper/wifi-setup-helper.cc',
                    'contrib/ndn4ivc/helper/wifi-setup-helper.h',
                    'src/propagation/model/propagation-loss-model.cc',
                    'src/traci/model/traci-client.cc']
    groups = collections.defaultdict(set)
    source_revisions = collections.Counter()
    source_fingerprints = collections.Counter()
    vehicle_rows = []
    for path in sorted((BATCH / 'runs').glob('test-*')):
        if not re.match(r'test-(grid|spidermap)-(baseline|n10-v30-k(1500|3000|9000|12000))-s\d+-a[0-3]$', path.name):
            continue
        configs = list(path.glob('attempt-001/runs/*/experiment.json'))
        assert len(configs) == 1
        config = json.loads(configs[0].read_text())
        scene, strategy, seed = config['scenario'], config['strategy'], config['seeds']['sumo_seed']
        raw = Path(config['output_dir'])
        summary = json.loads((Path(config['route_file']).parent / 'input-summary.json').read_text())
        manifest = json.loads((configs[0].parent / 'manifest.json').read_text())
        assert manifest['status'] == 'complete'
        source_revisions[manifest['source']['git_revision']] += 1
        source_fingerprints[manifest['source']['sha256']] += 1
        start = round(config['measurement_start_s'] * 1e9)
        end = round(config['measurement_end_s'] * 1e9)
        tx, threshold = RADIO[scene]
        per_vehicle = collections.defaultdict(collections.Counter)
        samples = []
        example_distances = []
        for row in csv.DictReader((raw / 'mobility-events.csv').open()):
            if row['event'] != 'SAMPLE' or not start <= int(row['time_ns']) < end:
                continue
            x, y = float(row['x']), float(row['y'])
            powers = [rx_power(tx, math.sqrt((x-rx)**2 + (y-ry)**2 + (RSU_Z-OBU_Z)**2)) for rx, ry in positions[scene]]
            selected = int(row['rsu_id'])
            any_reachable = max(powers) >= threshold
            selected_reachable = selected >= 0 and powers[selected] >= threshold
            stats = per_vehicle[row['vehicle_id']]
            stats['samples'] += 1
            stats['any_rsu_within_sensitivity'] += any_reachable
            stats['selected_rsu_within_sensitivity'] += selected_reachable
            stats['selected_outside_any_inside'] += selected >= 0 and not selected_reachable and any_reachable
            stats['unassociated_any_inside'] += selected < 0 and any_reachable
            samples.append(tuple(row[k] for k in ('time_ns','vehicle_id','x','y','speed_mps')))
            if scene == 'spidermap' and seed == 23018 and strategy == 3 and summary['requested_count'] == 1500 and row['vehicle_id'] == 'exp-00001':
                example_distances.append(min(math.hypot(x-rx,y-ry) for rx,ry in positions[scene]))
        samples.sort()
        digest = hashlib.sha256(json.dumps(samples).encode()).hexdigest()
        groups[(scene, seed)].add(digest)
        total = sum((s for s in per_vehicle.values()), collections.Counter())
        r = {'run_id': config['run_id'], 'scene': scene, 'strategy': strategy, 'seed': seed,
             'requests': summary['requested_count'], 'mobility_path': str(raw / 'mobility-events.csv'),
             'trajectory_sha256': digest, **dict(total)}
        r['geometric_coverage_sample_percent'] = total['any_rsu_within_sensitivity'] / total['samples'] * 100.0
        result['runs'].append(r)
        if example_distances:
            result['example_all_window_outside_sensitivity'] = {
                'run_id': config['run_id'], 'scene': scene, 'seed': seed,
                'strategy': strategy, 'requests': summary['requested_count'],
                'vehicle': 'exp-00001', 'samples': len(example_distances),
                'nearest_rsu_horizontal_min_m': min(example_distances),
                'nearest_rsu_horizontal_max_m': max(example_distances),
                'samples_within_sensitivity': per_vehicle['exp-00001']['any_rsu_within_sensitivity']}
        for vehicle, counts in per_vehicle.items():
            vehicle_rows.append({'scene': scene, 'strategy': strategy, 'seed': seed,
                                 'requests': summary['requested_count'], 'vehicle': vehicle, **dict(counts)})
    assert len(result['runs']) == 80, len(result['runs'])
    result['run_source_revisions'] = dict(source_revisions)
    result['run_source_fingerprints'] = dict(source_fingerprints)
    for path in source_paths:
        current = (ROOT / path).read_bytes()
        checks = {}
        for revision in sorted(source_revisions):
            historical_revision = subprocess.check_output(['git', 'show', revision + ':./' + path])
            assert historical_revision == current
            checks[revision] = True
        result['source_checks'][path] = {'matches_each_observed_run_git_revision': checks,
                                         'sha256': hashlib.sha256(current).hexdigest(),
                                         'note': 'These dependencies are outside old source.tar.gz scope; git revision equality is weaker than full historical binary provenance.'}
    tar_paths = ['scratch/vndn-spidermap-simulator/vndn-spidermap-main.cc',
                 'scratch/vndn-grid-simulator/vndn-grid-main.cc',
                 'contrib/vndn-nn-rd/helper/vndn-utils-helper.cc',
                 'contrib/vndn-nn-rd/traces/fgfxf-spider-map/settings.xml',
                 'contrib/vndn-nn-rd/traces/grid-vanet-test/settings.xml']
    result['sealed_source_tar_checks'] = {}
    with tarfile.open(BATCH / 'plan/source.tar.gz') as archive:
        for path in tar_paths:
            saved = archive.extractfile(path).read()
            assert saved == (ROOT / path).read_bytes()
            result['sealed_source_tar_checks'][path] = {'matches_current': True, 'sha256': hashlib.sha256(saved).hexdigest()}
    result['coverage_summary'] = {}
    for key, digests in groups.items():
        assert len(digests) == 1, key
        result['trajectory_groups']['%s/seed%d' % key] = {'hash': next(iter(digests)), 'all_20_runs_identical': True}
        same_group = [r for r in result['runs'] if (r['scene'],r['seed']) == key]
        coverages = {r['geometric_coverage_sample_percent'] for r in same_group}
        assert len(coverages) == 1
        result['coverage_summary']['%s/seed%d' % key] = {'sample_percent': next(iter(coverages)), 'runs': len(same_group)}
    for scene in RADIO:
        per_seed = [v['sample_percent'] for k,v in result['coverage_summary'].items() if k.startswith(scene + '/')]
        result['coverage_summary'][scene + '/seed_mean'] = {'sample_percent': sum(per_seed)/len(per_seed), 'seed_count':len(per_seed)}
    with (OUT / 'geometry-per-vehicle.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(vehicle_rows[0]))
        writer.writeheader()
        writer.writerows(vehicle_rows)
    (OUT / 'geometry-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'runs': len(result['runs']), 'trajectory_groups': result['trajectory_groups'],
                      'radio': result['radio'], 'sample_runs': result['runs'][:4]}, indent=2))


if __name__ == '__main__':
    main()
