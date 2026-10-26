#!/usr/bin/env python3.8
"""One independent CPU inference benchmark process; never runs ns-3 or training."""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import time


def measure(operation, warmup=100, repetitions=1000, clock=time.perf_counter_ns):
    if warmup < 0 or repetitions < 1:
        raise ValueError('invalid benchmark repetition count')
    for _ in range(warmup):
        operation()
    durations = []
    for _ in range(repetitions):
        start = clock()
        operation()
        durations.append((clock() - start) / 1000.)
    if any(value < 0 for value in durations):
        raise ValueError('nonmonotonic benchmark clock')
    return durations


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def benchmark(model_file, scenario, input_file, output_file, repetition,
              warmup=100, iterations=1000, allow_validation_only=False):
    import numpy as np
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    root = Path(__file__).resolve().parents[2]
    controller_path = root / 'scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py'
    spec = importlib.util.spec_from_file_location('benchmark_controller', controller_path)
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    model_sha, input_sha = sha(model_file), sha(input_file)
    observation = json.loads(Path(input_file).read_text())
    model, checkpoint, _ = controller.load_model(Path(model_file), torch.device('cpu'),
        expected_scenario=scenario, require_formal=True, allow_validation_only=allow_validation_only)
    features = np.asarray(observation['features'], dtype=np.float32)
    if features.shape != (10, 6) or not np.isfinite(features).all():
        raise ValueError('benchmark must use one finite actual 10x6 observation')
    values = (features - np.asarray(checkpoint['normalization_mean'], dtype=np.float32)) / np.asarray(
        checkpoint['normalization_std'], dtype=np.float32)
    tensor = torch.from_numpy(values).unsqueeze(0)
    with torch.no_grad():
        forward = measure(lambda: model(tensor), warmup, iterations)
        complete = measure(lambda: controller.probabilities_for_candidates(
            observation, model, checkpoint, torch.device('cpu')), warmup, iterations)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    samples = output_file.with_suffix('.csv')
    with samples.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['operation', 'iteration', 'microseconds'])
        for name, durations in (('forward', forward), ('controller_compute', complete)):
            writer.writerows((name, index, value) for index, value in enumerate(durations))
    cpu = platform.processor()
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        cpu = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                    if line.startswith('model name')), cpu)
    result = dict(schema_version=1, status='complete', scenario=scenario, repetition=repetition,
        model_path=str(Path(model_file).resolve()), model_sha256=model_sha,
        input_path=str(Path(input_file).resolve()), input_sha256=input_sha,
        controller_sha256=sha(controller_path), benchmark_sha256=sha(__file__),
        pid=os.getpid(), cpu=cpu, python=sys.version, pytorch=torch.__version__,
        numpy=np.__version__, platform=platform.platform(), device='cpu', threads=1,
        interop_threads=1, batch_size=1, warmup=warmup, timed_iterations=iterations,
        clock='perf_counter_ns', samples_csv=samples.name, samples_sha256=sha(samples),
        scope='wall-clock compute only; excludes model loading, Gym, printing, file I/O; not simulation RTT',
        operations={name: dict(median_us=float(np.median(durations)),
            p95_us=float(np.percentile(durations, 95)), mean_us=float(np.mean(durations)),
            count=len(durations)) for name, durations in
            (('forward', forward), ('controller_compute', complete))})
    if sha(model_file) != model_sha or sha(input_file) != input_sha:
        raise ValueError('benchmark input changed during measurement')
    temporary = output_file.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    temporary.replace(output_file)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-file', required=True, type=Path)
    parser.add_argument('--scenario', required=True, choices=['circle', 'grid', 'spidermap'])
    parser.add_argument('--input-file', required=True, type=Path)
    parser.add_argument('--output-file', required=True, type=Path)
    parser.add_argument('--repetition', type=int, required=True)
    parser.add_argument('--allow-validation-only', action='store_true')
    args = parser.parse_args(argv)
    benchmark(args.model_file, args.scenario, args.input_file, args.output_file,
              args.repetition, allow_validation_only=args.allow_validation_only)


if __name__ == '__main__':
    main()
