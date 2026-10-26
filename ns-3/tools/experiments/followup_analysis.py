#!/usr/bin/env python3.8
"""Read-only analysis of the frozen 99-run supplementary experiment.

No training or simulations. Historical primary data remain immutable; evaluation
accepts missing target classes and reports exclusions rather than inventing data.
"""
import argparse
from collections import Counter, defaultdict
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / 'contrib/vndn-nn-rd/ai-training'
sys.path.insert(0, str(AI))
import formal_data as data

SCENES = ('circle', 'grid', 'spidermap')
STATE_FIELDS = ('present_vehicles', 'cache_vehicle_entries', 'cache_name_entries',
                'cache_edges', 'reverse_cache_edges', 'mac_entries', 'next_rsu_entries',
                'history_vehicles', 'history_records', 'history_timestamp_records')
METRICS = ('isr_percent', 'mean_success_rtt_ms', 'network_mbit', 'control_mbit',
           'extra_data_app_attempts')
CONTROL_CLASSES = {'hello', 'p2p_handshake', 'search', 'find', 'neural_route', 'neural_pit'}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_csv(path, records):
    records = list(records)
    keys = list(dict.fromkeys(key for row in records for key in row))
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, keys)
        writer.writeheader()
        for row in records:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                             if isinstance(value, (dict, list, tuple)) else value
                             for key, value in row.items()})


def csv_rows(path):
    with Path(path).open(newline='', encoding='utf-8') as stream:
        yield from csv.DictReader(stream)


def repeat_statistics(values):
    values = list(values)
    defined = [float(value) for value in values if value is not None]
    if any(not math.isfinite(value) for value in defined):
        raise ValueError('nonfinite per-run metric')
    return dict(n_runs=len(values), n_defined=len(defined),
                mean=float(np.mean(defined)) if defined else None,
                sd=float(np.std(defined, ddof=1)) if len(defined) > 1 else None,
                run_values=values)


def histogram_statistics(histogram):
    histogram = {data.integer(k, 'histogram value'): data.integer(v, 'histogram count')
                 for k, v in histogram.items() if v}
    count = sum(histogram.values())
    if not count:
        return dict(count=0, total=0, mean=None, median=None, p95=None, maximum=None)
    ordered = sorted(histogram.items())
    def element(index):
        cumulative = 0
        for value, repetitions in ordered:
            cumulative += repetitions
            if index < cumulative:
                return value
        raise AssertionError('histogram rank outside range')
    def quantile(q):
        rank = (count - 1) * q
        lo, hi = math.floor(rank), math.ceil(rank)
        return element(lo) + (element(hi) - element(lo)) * (rank - lo)
    total = sum(value * repetitions for value, repetitions in ordered)
    return dict(count=count, total=total, mean=total / count, median=quantile(.5),
                p95=quantile(.95), maximum=ordered[-1][0])


def state_statistics(rows, start_ns, end_ns, expected_rsus=None):
    """Integrate post-event held counts; network peaks use simultaneous states."""
    if not 0 <= start_ns < end_ns:
        raise ValueError('invalid state observation window')
    histories = defaultdict(list)
    for row in rows:
        timestamp = data.integer(row['time_ns'], 'state time')
        rsu = data.integer(row['rsu_id'], 'rsu_id')
        event = row['event']
        if event not in ('START', 'CHANGE', 'STOP'):
            raise ValueError('unknown state event')
        values = {field: data.integer(row[field], field) for field in STATE_FIELDS}
        if histories[rsu] and timestamp < histories[rsu][-1][0]:
            raise ValueError('state event times must be ordered')
        histories[rsu].append((timestamp, event, values))
    if not histories or (expected_rsus is not None and set(histories) != set(expected_rsus)):
        raise ValueError('state RSU set differs from expected RSUs')
    events = defaultdict(dict)
    for rsu, history in histories.items():
        if (history[0][1] != 'START' or history[0][0] > start_ns or
                history[-1][1] != 'STOP' or history[-1][0] < end_ns or
                sum(row[1] == 'START' for row in history) != 1 or
                sum(row[1] == 'STOP' for row in history) != 1):
            raise ValueError('state START/STOP does not cover observation window')
        if any(history[0][2].values()):
            raise ValueError('START must record zero initial state')
        for timestamp, _, values in history:
            events[timestamp][rsu] = values  # Last post-event state at an equal timestamp.
    duration = end_ns - start_ns
    states = {rsu: dict.fromkeys(STATE_FIELDS, 0) for rsu in histories}
    integrals = {rsu: dict.fromkeys(STATE_FIELDS, 0) for rsu in histories}
    peaks = {rsu: dict.fromkeys(STATE_FIELDS, 0) for rsu in histories}
    network_integral = dict.fromkeys(STATE_FIELDS, 0)
    network_peak = dict.fromkeys(STATE_FIELDS, 0)
    times = sorted(set(events) | {start_ns, end_ns})
    for index, timestamp in enumerate(times[:-1]):
        states.update(events.get(timestamp, {}))
        left, right = max(timestamp, start_ns), min(times[index + 1], end_ns)
        if right <= left:
            continue
        for field in STATE_FIELDS:
            total = sum(state[field] for state in states.values())
            network_integral[field] += total * (right - left)
            network_peak[field] = max(network_peak[field], total)
            for rsu, state in states.items():
                integrals[rsu][field] += state[field] * (right - left)
                peaks[rsu][field] = max(peaks[rsu][field], state[field])
    result = []
    for rsu in sorted(histories) + ['network']:
        integral = network_integral if rsu == 'network' else integrals[rsu]
        peak = network_peak if rsu == 'network' else peaks[rsu]
        result.append(dict(rsu_id=rsu, start_ns=start_ns, end_ns=end_ns,
                           **{field + '_mean': integral[field] / duration for field in STATE_FIELDS},
                           **{field + '_peak': peak[field] for field in STATE_FIELDS}))
    return result


def phase_for(timestamp, start, end, drain):
    if not 0 <= timestamp <= drain:
        raise ValueError('observation outside whole simulation window')
    return 'startup' if timestamp < start else 'measurement' if timestamp < end else 'drain'


def payload_statistics(rows, start_ns, end_ns, drain_ns):
    groups = defaultdict(lambda: dict(content=Counter(), wire=Counter(), cache=Counter(),
                                      added=0, removed=0))
    allowed = {'registration', 'delta', 'unchanged', 'cache_disabled'}
    for row in rows:
        phase = phase_for(data.integer(row['time_ns'], 'payload time'), start_ns, end_ns, drain_ns)
        category = row['category']
        if category not in allowed:
            raise ValueError('unknown hello payload category')
        content, wire, cache, added, removed = [data.integer(row[field], field) for field in
            ('content_bytes', 'wire_bytes', 'cache_items', 'added_items', 'removed_items')]
        if wire < content:
            raise ValueError('wire bytes smaller than content bytes')
        item = groups[phase, category]
        item['content'][content] += 1
        item['wire'][wire] += 1
        item['cache'][cache] += 1
        item['added'] += added
        item['removed'] += removed
    result = []
    for (phase, category), item in sorted(groups.items()):
        stats = {key: histogram_statistics(item[key]) for key in ('content', 'wire', 'cache')}
        result.append(dict(phase=phase, category=category, count=stats['wire']['count'],
            scope='application encoded hello Data submission; not network/MAC transmission',
            added_items_total=item['added'], removed_items_total=item['removed'],
            **{prefix + '_' + metric: value for key, prefix in
               (('content', 'content_bytes'), ('wire', 'wire_bytes'), ('cache', 'cache_items'))
               for metric, value in stats[key].items() if metric != 'count'}))
    return result


def packet_statistics(rows, start_ns, drain_ns):
    groups = defaultdict(Counter)
    for row in rows:
        time_ns = data.integer(row['time_ns'], 'packet time')
        if (start_ns <= time_ns < drain_ns and row['direction'] == 'OUT' and
                row['packet_type'] in ('INTEREST', 'DATA') and
                row['semantic_class'] in CONTROL_CLASSES):
            groups[row['semantic_class'], row['packet_type']][
                data.integer(row['wire_bytes'], 'wire bytes')] += 1
    return [dict(semantic_class=key[0], packet_type=key[1],
                 scope='network Face NDN L3 outgoing; excludes LP/MAC',
                 **histogram_statistics(histogram)) for key, histogram in sorted(groups.items())]


def materialize_evaluation_run(run, output, manifest_sha256, scenario, seed_family,
                               condition_id, allow_validation_only=False):
    """Reuse the established causal labels without training-only split/class gates."""
    run, output = Path(run).resolve(), Path(output).resolve()
    entry = dict(path=str(run), manifest_sha256=manifest_sha256, split='evaluation',
                 seed_family=seed_family, condition_id=condition_id)
    spec = dict(scenario=scenario, validation_only=allow_validation_only)
    run, manifest, _, complete = data._source(entry, spec, run.parent)
    identity = dict(manifest_sha256=manifest_sha256, scenario=scenario,
                    seed_family=seed_family, condition_id=condition_id,
                    label_contract=data.LABEL_CONTRACT,
                    formal_data_sha256=data.sha256_file(Path(data.__file__)))
    if (output / 'shard.json').is_file():
        saved = data.read_json(output / 'shard.json')
        if saved.get('identity') != identity:
            raise ValueError('evaluation shard identity changed')
        for filename, digest in saved['hashes'].items():
            data.verify_hash(output / filename, digest)
        return saved
    if output.exists():
        output.rename(output.with_name(output.name + '-interrupted-' + str(time.time_ns())))
    output.mkdir(parents=True)
    audit = dict(observation_count=0, generated_count=0, excluded=Counter(), runs=[])
    shard = data._materialize_run(run, manifest, complete, entry, scenario, output, 0, audit)
    data._source(entry, spec, run.parent)
    shard['identity'] = identity
    shard['missing_label_values'] = [i for i, count in enumerate(shard['class_counts']) if not count]
    write_json(output / 'shard.json', shard)
    return shard


def prediction_statistics(probabilities, targets, records, label_values):
    targets = np.asarray(targets, dtype=np.int64)
    values = np.asarray(probabilities, dtype=np.float64)
    if len(targets) != len(records) or (len(targets) and values.shape != (len(targets), len(label_values))):
        raise ValueError('prediction/target/evidence length mismatch')
    if len(targets) and (not np.isfinite(values).all() or np.any(values < 0) or
                        not np.allclose(values.sum(axis=1), 1, atol=1e-5)):
        raise ValueError('invalid prediction probabilities')
    native = sorted(label_values)
    if native != list(range(len(native))) or any(int(target) not in native for target in targets):
        raise ValueError('invalid scene target labels')
    predicted = np.asarray(label_values)[np.argmax(values, axis=1)] if len(targets) else np.array([])
    correct = predicted == targets
    handover = np.asarray([bool(record['handover']) for record in records])
    history = np.asarray([int(record['actual_history_length']) for record in records])
    confusion = np.zeros((len(native), len(native)), dtype=int)
    for target, guess in zip(targets, predicted):
        confusion[int(target), int(guess)] += 1
    return dict(sample_count=len(targets), correct_count=int(correct.sum()),
        accuracy_percent=float(correct.mean() * 100) if len(targets) else None,
        handover_count=int(handover.sum()),
        handover_correct_count=int(correct[handover].sum()) if len(targets) else 0,
        handover_accuracy_percent=float(correct[handover].mean() * 100) if handover.any() else None,
        empty_history_count=int((history == 0).sum()),
        short_history_count=int(((history > 0) & (history < 10)).sum()),
        full_history_count=int((history == 10).sum()),
        unique_evaluable_requests=len({record['request_id'] for record in records}),
        class_support=confusion.sum(axis=1).tolist(), confusion_matrix=confusion.tolist())


def controller_module():
    return load_module('followup_controller', ROOT / 'scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py')


def evaluate_shard(directory, shard, model_record, scenario, allow_validation_only=False):
    import torch
    directory = Path(directory)
    data.verify_hash(model_record['path'], model_record['sha256'])
    identity = dict(model_sha256=model_record['sha256'], shard_hashes=shard['hashes'],
                    analysis_sha256=data.sha256_file(Path(__file__)))
    destination = directory / 'evaluation.json'
    if destination.exists():
        saved = data.read_json(destination)
        if saved.get('identity') != identity:
            raise ValueError('cached evaluation identity changed')
        data.verify_hash(directory / 'predictions.jsonl', saved['predictions_sha256'])
        return saved
    torch.set_num_threads(1)
    controller = controller_module()
    model, checkpoint, _ = controller.load_model(Path(model_record['path']), torch.device('cpu'),
        expected_scenario=scenario, require_formal=True, allow_validation_only=allow_validation_only)
    features = np.load(directory / shard['features'], mmap_mode='r')
    targets = np.load(directory / shard['targets'], mmap_mode='r')
    records = []
    history_all = Counter()
    with (directory / shard['samples']).open() as stream:
        for line in stream:
            record = json.loads(line)
            length = record.get('actual_history_length')
            if isinstance(length, int):
                history_all['empty' if length == 0 else 'short' if length < 10 else 'full'] += 1
            if record['exclusion_reason'] is None:
                if record['sample_index'] != len(records):
                    raise ValueError('nonconsecutive sample evidence index')
                records.append(record)
    mean = np.asarray(checkpoint['normalization_mean'], dtype=np.float32)
    std = np.asarray(checkpoint['normalization_std'], dtype=np.float32)
    batches = []
    with torch.no_grad():
        for start in range(0, len(targets), 256):
            normalized = (np.asarray(features[start:start + 256]) - mean) / std
            logits = model(torch.from_numpy(normalized))
            if not torch.isfinite(logits).all():
                raise ValueError('nonfinite model logits')
            batches.append(torch.softmax(logits, dim=1).numpy())
    probabilities = np.concatenate(batches) if batches else np.empty((0, len(checkpoint['label_values'])))
    result = prediction_statistics(probabilities, targets, records, checkpoint['label_values'])
    with (directory / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
        for row, values in zip(records, probabilities):
            stream.write(json.dumps(dict(row, probabilities=values.tolist(),
                probability_label_order=checkpoint['label_values'],
                predicted_label=checkpoint['label_values'][int(values.argmax())]), allow_nan=False) + '\n')
    result.update(identity=identity, scenario=scenario,
        observation_count=shard['observation_count'], generated_count=shard['generated_count'],
        exclusions=shard['excluded'], observation_history_counts=dict(history_all),
        evaluable_observation_percent=100 * len(targets) / shard['observation_count']
            if shard['observation_count'] else None,
        evaluable_request_percent=100 * result['unique_evaluable_requests'] / shard['generated_count']
            if shard['generated_count'] else None,
        missing_label_values=shard['missing_label_values'],
        label_contract=data.LABEL_CONTRACT,
        handover_scope='association change in closed generated-request lifetime [send, deadline]',
        history_policy='retain online-equivalent padded empty/short histories and report separately',
        predictions_sha256=data.sha256_file(directory / 'predictions.jsonl'))
    # A valid full-history sample is preferred for the separate latency microbenchmark.
    if len(records):
        index = next((i for i, row in enumerate(records) if row['actual_history_length'] == 10), 0)
        write_json(directory / 'benchmark-input.json', dict(features=features[index].tolist(),
            rsu_ids=records[index]['candidate_rsu_ids'], sample_evidence=records[index],
            source_run=shard['source_path'], source_manifest_sha256=shard['source_manifest_sha256']))
        result['benchmark_input'] = str(directory / 'benchmark-input.json')
    data.verify_hash(model_record['path'], model_record['sha256'])
    write_json(destination, result)
    return result


def task_metadata(task, run):
    return dict(task_id=task['id'], stage=task['stage'], scenario=task['scenario'],
        strategy=task['strategy'], hello_interval_ms=task['hello_interval_ms'],
        rsu_timeout_ms=2 * task['hello_interval_ms'], vehicles=task['vehicles'],
        speed_kmh=task['speed_kmh'], requests=task['requests'], seed_family=task['seed'],
        run_path=str(run))



def validate_effective_period(effective, period):
    expected = dict(hello_interval_ms=period, rsu_timeout_ms=2 * period,
                    obu_neighbor_timeout_ms=2000, resource_observations=True)
    if any(effective.get(key) != value for key, value in expected.items()):
        raise ValueError('effective period/expiry/observation configuration differs from plan')


def verified_tasks(root, manifest, progress=None):
    tasks = manifest['tasks']
    if len(tasks) != 99 or Counter(task['stage'] for task in tasks) != dict(accuracy=36, online=36, state=27):
        raise ValueError('supplement requires exactly 36 accuracy + 36 online + 27 state runs')
    signatures, run_paths, sources, records = set(), set(), set(), []
    seeds = {scene: {task['seed'] for task in tasks if task['scenario'] == scene} for scene in SCENES}
    if any(len(value) != 3 for value in seeds.values()):
        raise ValueError('exactly three prespecified seeds required for each scene')
    expected = set()
    for scene in SCENES:
        for seed in seeds[scene]:
            for stage, strategy in (('accuracy', 0), ('online', 3)):
                for period in (20, 40, 80, 160):
                    expected.add((stage, scene, strategy, period, 10, 30, 6000, seed))
            for vehicles in (5, 15, 20):
                expected.add(('state', scene, 3, 20, vehicles, 30, vehicles * 600, seed))
    for index, task in enumerate(tasks):
        signature = tuple(task[key] for key in ('stage', 'scenario', 'strategy',
            'hello_interval_ms', 'vehicles', 'speed_kmh', 'requests', 'seed'))
        if signature in signatures:
            raise ValueError('duplicate supplementary run signature')
        signatures.add(signature)
        status = data.read_json(root / 'plan/tasks' / (task['id'] + '.json'))
        if status.get('status') != 'complete':
            raise ValueError('supplementary task not complete: ' + task['id'])
        run = Path(status.get('run_dir', status.get('path', ''))).resolve()
        if run in run_paths or root not in run.parents:
            raise ValueError('duplicate or outside-root supplementary run path')
        run_paths.add(run)
        data.verify_hash(run / 'manifest.json', status['manifest_sha256'])
        runtime = data.read_json(run / 'manifest.json')
        if runtime.get('status') != 'complete' or runtime.get('validation_only') is not False:
            raise ValueError('supplementary source is not a complete formal run')
        if (runtime.get('scenario') != task['scenario'] or runtime.get('strategy') != task['strategy'] or
                any(value.get('returncode') != 0 for value in runtime.get('processes', {}).values())):
            raise ValueError('supplementary runtime identity/process mismatch')
        required = {'experiment.json', 'run-metrics.json', 'raw/rsu-state.csv',
                    'raw/hello-payloads.csv', 'raw/recorder-complete.json'}
        if not required.issubset(runtime.get('artifact_hashes', {})):
            raise ValueError('resource or metric artifacts missing from frozen run')
        for filename, digest in runtime['artifact_hashes'].items():
            path = (run / filename).resolve()
            if run not in path.parents:
                raise ValueError('artifact path escapes run')
            data.verify_hash(path, digest)
        config = data.read_json(run / 'experiment.json')
        if (config.get('hello_interval_ms') != task['hello_interval_ms'] or
                config.get('resource_observations') is not True or
                config.get('training_snapshots', False) != (task['stage'] == 'accuracy')):
            raise ValueError('period/resource/snapshot configuration differs from task')
        validate_effective_period(data.read_json(run / 'raw/effective-experiment-config.json'),
                                  task['hello_interval_ms'])
        if (runtime['source']['sha256'] != manifest['source']['sha256'] or
                (task['strategy'] == 3 and runtime.get('model') != manifest['models'][task['scenario']])):
            raise ValueError('runtime source or online model differs from frozen follow-up plan')
        if any(config.get('seeds', {}).get(key) != task['seed']
               for key in ('rng_run', 'sumo_seed', 'srand_seed')):
            raise ValueError('actual seeds differ from frozen task')
        metrics = data.read_json(run / 'run-metrics.json')
        if metrics.get('generated') != task['requests']:
            raise ValueError('generated count differs from planned requests')
        sources.add(runtime['source']['sha256'])
        records.append((task, run, runtime, metrics, status))
        if progress:
            progress('verify-runs', index + 1, len(tasks), task['id'])
    if signatures != expected or len(sources) != 1:
        raise ValueError('incomplete approved matrix or mixed runtime source versions')
    return records


def resource_analysis(run, metrics, expected_rsus):
    marker = data.read_json(run / 'raw/recorder-complete.json')
    if marker.get('resource_observations') is not True:
        raise ValueError('resource observations are not complete')
    start, end, drain = [int(metrics[field]) for field in
        ('measurement_start_ns', 'measurement_end_ns', 'drain_end_ns')]
    counts = Counter()
    def counted(name):
        for row in csv_rows(run / 'raw' / name):
            counts[name] += 1
            yield row
    states = state_statistics(counted('rsu-state.csv'), start, end, expected_rsus)
    payloads = payload_statistics(counted('hello-payloads.csv'), start, end, drain)
    if (counts['rsu-state.csv'] != marker.get('rsu_state_rows') or
            counts['hello-payloads.csv'] != marker.get('hello_payload_rows')):
        raise ValueError('resource CSV row counts disagree with completion marker')
    packets = packet_statistics(csv_rows(run / 'raw/packet-l3.csv'), start, drain)
    if sum(row['total'] for row in packets) != metrics['control_l3_bytes']:
        raise ValueError('control packet histogram bytes disagree with existing metric')
    return dict(states=states, payloads=payloads, packets=packets, row_counts=dict(counts))


def grouped_table(rows, grouping, fields):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in grouping)].append(row)
    result = []
    for key, records in sorted(groups.items(), key=lambda item: str(item[0])):
        for field in fields:
            result.append(dict(zip(grouping, key), metric=field,
                **repeat_statistics([row.get(field) for row in records])))
    return result


def run_benchmarks(output, models, inputs, progress):
    result = []
    for scene in SCENES:
        for repetition in range(1, 6):
            progress('cpu-benchmark', len(result) // 2, 15, '{} process {}'.format(scene, repetition))
            path = output / '{}-process-{}.json'.format(scene, repetition)
            if path.exists():
                saved = data.read_json(path)
                if (saved['model_sha256'] != models[scene]['sha256'] or
                        saved['input_sha256'] != data.sha256_file(inputs[scene]) or
                        saved['benchmark_sha256'] != data.sha256_file(Path(__file__).with_name('followup_benchmark.py'))):
                    raise ValueError('benchmark cache identity changed')
                data.verify_hash(path.with_suffix('.csv'), saved['samples_sha256'])
            else:
                command = [sys.executable, str(Path(__file__).with_name('followup_benchmark.py')),
                    '--model-file', models[scene]['path'], '--scenario', scene,
                    '--input-file', inputs[scene], '--output-file', str(path),
                    '--repetition', str(repetition)]
                environment = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                                   MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
                output.mkdir(parents=True, exist_ok=True)
                with path.with_suffix('.log').open('w') as log:
                    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                                   env=environment, timeout=600)
                saved = data.read_json(path)
            for operation, metrics in saved['operations'].items():
                result.append(dict(scenario=scene, repetition=repetition, operation=operation,
                    benchmark_file=str(path), model_sha256=saved['model_sha256'],
                    input_sha256=saved['input_sha256'], pid=saved['pid'], cpu=saved['cpu'], **metrics))
    progress('cpu-benchmark', 15, 15, None)
    return result


def analyze(root):
    root = Path(root).resolve()
    output = root / 'analysis'
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    def progress(stage, completed=0, total=0, current=None, status='running'):
        write_json(output / 'status.json', dict(schema_version=1, status=status, stage=stage,
            current=current, completed=completed, total=total,
            elapsed_seconds=time.monotonic() - started))
        print('{} {}/{} {}'.format(stage, completed, total, current or ''), flush=True)
    try:
        manifest_path = root / 'plan/followup-manifest.json'
        manifest_sha = data.sha256_file(manifest_path)
        manifest = data.read_json(manifest_path)
        models = manifest['models']
        if set(models) != set(SCENES):
            raise ValueError('exactly three frozen models required')
        for model in models.values():
            data.verify_hash(model['path'], model['sha256'])
        records = verified_tasks(root, manifest, progress)
        accuracy, online, states, payloads, packets, benchmark_inputs, sources = [], [], [], [], [], {}, []
        for task, run, runtime, metrics, status in records:
            sources.append(dict(kind='run_manifest', path=str(run / 'manifest.json'),
                                sha256=status['manifest_sha256']))
            sources.extend(dict(kind='raw_or_metric', path=str(run / name), sha256=digest)
                           for name, digest in runtime['artifact_hashes'].items())
            meta = task_metadata(task, run)
            if task['stage'] == 'accuracy':
                progress('offline-prediction', len(accuracy), 36, task['id'])
                cache = output / 'evaluation' / task['id']
                shard = materialize_evaluation_run(run, cache, status['manifest_sha256'],
                    task['scenario'], task['seed'], task['condition_id'])
                evaluated = evaluate_shard(cache, shard, models[task['scenario']], task['scenario'])
                accuracy.append(dict(meta, **{k: v for k, v in evaluated.items()
                                               if k not in ('scenario', 'identity')}))
                if evaluated.get('benchmark_input') and task['scenario'] not in benchmark_inputs:
                    benchmark_inputs[task['scenario']] = evaluated['benchmark_input']
            else:
                progress('online-and-resources', len(online), 63, task['id'])
                online.append(dict(meta, **{key: value for key, value in metrics.items()
                    if key not in meta and not isinstance(value, dict)}))
                cache_path = output / 'resources' / (task['id'] + '.json')
                identity = dict(manifest_sha256=status['manifest_sha256'],
                    analysis_sha256=data.sha256_file(Path(__file__)))
                if cache_path.exists():
                    resource = data.read_json(cache_path)
                    if resource.get('identity') != identity:
                        raise ValueError('resource cache identity changed')
                else:
                    resource = resource_analysis(run, metrics, range(2 if task['scenario'] == 'circle' else 7))
                    resource['identity'] = identity
                    write_json(cache_path, resource)
                states.extend(dict(meta, **row) for row in resource['states'])
                payloads.extend(dict(meta, **row) for row in resource['payloads'])
                packets.extend(dict(meta, **row) for row in resource['packets'])
        for name, rows in (('accuracy-runs.csv', accuracy), ('online-runs.csv', online),
                           ('state-runs.csv', states), ('hello-payload-runs.csv', payloads),
                           ('control-packet-runs.csv', packets)):
            write_csv(output / name, rows)
        write_json(output / 'run-analysis.json', dict(accuracy=accuracy, online=online,
            states=states, payloads=payloads, packets=packets))
        if set(benchmark_inputs) != set(SCENES):
            raise ValueError('no valid observed input for a scene CPU benchmark; inspect exclusions')
        benchmarks = run_benchmarks(output / 'benchmark', models, benchmark_inputs, progress)
        write_csv(output / 'inference-processes.csv', benchmarks)
        tables = dict(
            accuracy=grouped_table(accuracy, ('scenario', 'hello_interval_ms'),
                ('accuracy_percent', 'handover_accuracy_percent', 'evaluable_observation_percent',
                 'evaluable_request_percent', 'sample_count', 'short_history_count', 'empty_history_count')),
            online=grouped_table([row for row in online if row['stage'] == 'online'],
                ('scenario', 'hello_interval_ms'), METRICS),
            state=grouped_table([row for row in states if row['hello_interval_ms'] == 20],
                ('scenario', 'vehicles', 'rsu_id'),
                tuple(field + suffix for field in STATE_FIELDS for suffix in ('_mean', '_peak'))))
        for name, rows in tables.items():
            write_csv(output / (name + '-summary.csv'), rows)
        progress('reuse-primary-and-render', 0, 1, 'verify historical aggregate and render')
        figures_module = load_module('followup_figures', Path(__file__).with_name('followup_figures.py'))
        figure_report = figures_module.render_all(root, Path(manifest['old_campaign_root']),
            accuracy, online, states, payloads, packets, benchmarks, progress)
        data.verify_hash(manifest_path, manifest_sha)
        for model in models.values():
            data.verify_hash(model['path'], model['sha256'])
            sources.append(dict(kind='fixed_model', path=model['path'], sha256=model['sha256']))
        sources.append(dict(kind='followup_manifest', path=str(manifest_path), sha256=manifest_sha))
        write_csv(output / 'source-index.csv', sources)
        result = dict(schema_version=1, status='complete', manifest_sha256=manifest_sha,
            analysis_code_sha256=data.sha256_file(Path(__file__)),
            counts=dict(accuracy=len(accuracy), online=len(online), cpu_processes=15),
            models=models, figure_index=str(root / 'figures/figure-index.json'),
            figures=figure_report['figure_count'],
            artifact_hashes={str(path.relative_to(root)): data.sha256_file(path)
                for path in [root / 'figures/figure-index.json', root / 'figures/index.html',
                             output / 'run-analysis.json', output / '方法与数据来源.md'] +
                            sorted(output.glob('*.csv'))},
            method='方法与数据来源.md', elapsed_seconds=time.monotonic() - started)
        write_json(output / 'summary.json', result)
        progress('complete', 99, 99, None, status='complete')
        return result
    except BaseException as error:
        progress('failed', 0, 99, str(error), status='failed')
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args(argv)
    analyze(args.root)
    return 0


if __name__ == '__main__':
    sys.exit(main())
