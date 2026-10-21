"""Controlled-data training. Legacy scene entry points and model classes remain usable.

Training and normalization never open evaluation feature arrays. Arrays are mapped
per run with a bounded LRU, not concatenated into a campaign-sized tensor.
"""
import argparse
import bisect
from collections import OrderedDict, defaultdict
import copy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import uuid

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from formal_data import (FEATURE_NAMES, LABEL_CONTRACT, OBSERVATION_CONTRACT,
                         SCENARIO_LABELS, load_dataset_manifest, read_json,
                         sha256_file, verify_hash, write_json)


def normalization_statistics(manifest_path):
    """Stable merge of training-only input moments, including online padding."""
    path = Path(manifest_path)
    manifest = load_dataset_manifest(path)
    count, mean, m2 = 0, np.zeros(6, dtype=np.float64), np.zeros(6, dtype=np.float64)
    for shard in manifest["shards"]:
        if shard["split"] != "train":
            continue
        values = np.load(path.parent / shard["features"], mmap_mode="r")
        for start in range(0, len(values), 4096):
            batch = np.asarray(values[start:start + 4096], dtype=np.float64).reshape(-1, 6)
            if not len(batch):
                continue
            current_mean = batch.mean(axis=0)
            current_m2 = np.square(batch - current_mean).sum(axis=0)
            total = count + len(batch)
            difference = current_mean - mean
            m2 += current_m2 + difference * difference * count * len(batch) / total
            mean += difference * len(batch) / total
            count = total
    if not count:
        raise ValueError("no training samples for normalization")
    std = np.sqrt(m2 / count)
    std[std < 1e-8] = 1
    if not np.isfinite(mean).all() or not np.isfinite(std).all():
        raise ValueError("nonfinite train normalization")
    return mean.astype(np.float32), std.astype(np.float32)


class MmapSnapshots(Dataset):
    def __init__(self, manifest_path, manifest, split, mean, std, shards=None):
        self.directory = Path(manifest_path).parent
        self.shards = (list(shards) if shards is not None else
                       [s for s in manifest["shards"] if s["split"] == split])
        self.ends = np.cumsum([s["sample_count"] for s in self.shards]).tolist()
        self.mean, self.std = np.asarray(mean, dtype=np.float32), np.asarray(std, dtype=np.float32)
        self.cache = OrderedDict()

    def __len__(self):
        return self.ends[-1] if self.ends else 0

    def __getitem__(self, index):
        if not 0 <= index < len(self):
            raise IndexError(index)
        shard_index = bisect.bisect_right(self.ends, index)
        local = index - (self.ends[shard_index - 1] if shard_index else 0)
        if shard_index not in self.cache:
            shard = self.shards[shard_index]
            self.cache[shard_index] = (
                np.load(self.directory / shard["features"], mmap_mode="r"),
                np.load(self.directory / shard["targets"], mmap_mode="r"))
            if len(self.cache) > 8:
                self.cache.popitem(last=False)
        self.cache.move_to_end(shard_index)
        features, targets = self.cache[shard_index]
        values = np.array((features[local] - self.mean) / self.std, dtype=np.float32, copy=True)
        return torch.from_numpy(values), int(targets[local])


def selected_targets(probabilities):
    """Mirror float32 subtraction followed by the C++ double threshold comparison."""
    probabilities = np.asarray(probabilities, dtype=np.float32)
    order = np.argsort(-probabilities, axis=1, kind="stable")
    if probabilities.shape[1] == 1:
        return order[:, 0], order[:, 0], np.zeros(len(probabilities), dtype=bool)
    first, second = order[:, 0], order[:, 1]
    rows = np.arange(len(probabilities))
    gap = (probabilities[rows, first] - probabilities[rows, second]).astype(np.float64)
    extra = (gap <= .1) | (probabilities[rows, second].astype(np.float64) >= .1)
    return first, second, extra


def selection_for_candidates(probabilities, candidates):
    """Use the same candidate renormalization as the online controller."""
    ids = np.asarray(candidates, dtype=np.int64)
    values = np.asarray(probabilities, dtype=np.float32)[ids]
    mass = float(values.sum())
    if not math.isfinite(mass) or mass <= 0:
        raise ValueError("candidate probability mass must be finite and positive")
    values = values / mass
    first, second, extra = selected_targets(values.reshape(1, -1))
    return int(ids[first[0]]), int(ids[second[0]]), bool(extra[0])


class MetricAccumulator:
    def __init__(self, classes):
        self.classes = classes
        self.confusion = np.zeros((classes, classes), dtype=np.int64)
        self.count = self.covered = self.candidates = 0
        self.nll = self.brier = 0.0
        self.bin_count = np.zeros(15, dtype=np.int64)
        self.bin_confidence = np.zeros(15, dtype=np.float64)
        self.bin_correct = np.zeros(15, dtype=np.float64)

    def update(self, probabilities, targets, cross_entropy_sum=None, selections=None):
        probs = np.asarray(probabilities, dtype=np.float32)
        targets = np.asarray(targets)
        if (probs.ndim != 2 or probs.shape[1] != self.classes or
                targets.shape != (len(probs),) or not np.issubdtype(targets.dtype, np.integer) or
                np.any(targets < 0) or np.any(targets >= self.classes) or
                not np.isfinite(probs).all() or np.any(probs < 0) or
                not np.allclose(probs.sum(axis=1), 1, atol=1e-6)):
            raise ValueError("invalid probabilities/labels for metrics")
        first, second, extra = selected_targets(probs)
        rows = np.arange(len(probs))
        np.add.at(self.confusion, (targets, first), 1)
        self.count += len(probs)
        selection_first, selection_second, selection_extra = (
            (first, second, extra) if selections is None else selections)
        self.covered += int(((targets == selection_first) |
                            (selection_extra & (targets == selection_second))).sum())
        self.candidates += len(probs) + int(selection_extra.sum())
        self.nll += (float(cross_entropy_sum) if cross_entropy_sum is not None else
                     float(-np.log(np.maximum(probs[rows, targets].astype(np.float64),
                                              np.finfo(np.float64).tiny)).sum()))
        differences = probs.astype(np.float64)
        differences[rows, targets] -= 1
        self.brier += float(np.square(differences).sum())
        confidence = probs[rows, first].astype(np.float64)
        bins = np.minimum((confidence * 15).astype(np.int64), 14)
        np.add.at(self.bin_count, bins, 1)
        np.add.at(self.bin_confidence, bins, confidence)
        np.add.at(self.bin_correct, bins, first == targets)

    def merge(self, other):
        self.confusion += other.confusion
        for field in ("count", "covered", "candidates", "nll", "brier"):
            setattr(self, field, getattr(self, field) + getattr(other, field))
        for field in ("bin_count", "bin_confidence", "bin_correct"):
            setattr(self, field, getattr(self, field) + getattr(other, field))

    def metrics(self):
        support = self.confusion.sum(axis=1)
        predicted = self.confusion.sum(axis=0)
        true_positive = self.confusion.diagonal()
        precision = np.divide(true_positive, predicted, out=np.zeros(self.classes), where=predicted > 0)
        recall = np.divide(true_positive, support, out=np.zeros(self.classes), where=support > 0)
        f1 = np.divide(2 * true_positive, support + predicted,
                       out=np.zeros(self.classes), where=(support + predicted) > 0)
        nonempty = self.bin_count > 0
        ece = float(np.abs(self.bin_confidence[nonempty] - self.bin_correct[nonempty]).sum())
        return dict(
            sample_count=self.count, confusion_matrix=self.confusion.tolist(),
            class_support=support.tolist(), precision=precision.tolist(), recall=recall.tolist(),
            class_f1=f1.tolist(), macro_f1=float(f1.mean()) if self.count else None,
            balanced_accuracy=float(recall.mean()) if self.count else None,
            accuracy=float(true_positive.sum() / self.count) if self.count else None,
            cross_entropy=self.nll / self.count if self.count else None,
            brier_score=self.brier / self.count if self.count else None,
            ece_15_equal_width=ece / self.count if self.count else None,
            target_set_coverage=self.covered / self.count if self.count else None,
            mean_candidate_count=self.candidates / self.count if self.count else None,
            threshold_gap=.1, threshold_min_second_probability=.1,
            tie_order="candidate order; same fixed 2/7 candidate order as current C++")


def classification_metrics(probabilities, targets):
    accumulator = MetricAccumulator(np.asarray(probabilities).shape[1])
    accumulator.update(probabilities, targets)
    return accumulator.metrics()


def is_better(candidate, incumbent, tolerance=1e-10):
    if incumbent is None:
        return True
    for field, direction in (("macro_f1", 1), ("cross_entropy", -1)):
        difference = (candidate[field] - incumbent[field]) * direction
        if abs(difference) > tolerance:
            return difference > 0
    return (candidate["epoch"], candidate["seed"]) < (incumbent["epoch"], incumbent["seed"])


def evaluate_loader(model, loader, device, classes):
    model.eval()
    accumulator = MetricAccumulator(classes)
    with torch.no_grad():
        for inputs, targets in loader:
            inputs, targets = inputs.to(device), targets.to(device)
            logits = model(inputs)
            if not torch.isfinite(logits).all():
                raise ValueError("nonfinite evaluation logits")
            loss = nn.functional.cross_entropy(logits, targets, reduction="sum")
            accumulator.update(torch.softmax(logits, dim=1).cpu().numpy(),
                               targets.cpu().numpy(), loss.item())
    if not accumulator.count:
        raise ValueError("evaluation split is empty")
    return accumulator.metrics()


def formal_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--session-dir", type=Path,
                        help="stable, identity-checked session; resume committed complete epochs")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--grid-size", type=int, default=5)
    parser.add_argument("--spline-order", type=int, default=3)
    parser.add_argument("--dropout", type=float, default=.1)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=.001)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--initialization-seeds", nargs="+", type=int,
                        default=[20261021, 20261022, 20261023])
    parser.add_argument("--selection-tolerance", type=float, default=1e-10)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--allow-validation-only", action="store_true")
    return parser.parse_args(argv)


def _device(name):
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    return torch.device("cuda" if name == "cuda" or (
        name == "auto" and torch.cuda.is_available()) else "cpu")


def _checkpoint(model, args, manifest, mean, std, best):
    classes = SCENARIO_LABELS[manifest["scenario"]]
    return dict(
        model_type="TKAN-LSTM", scenario=manifest["scenario"], forward_strategy="NoForward",
        feature_names=list(FEATURE_NAMES), label_name="serving_rsu_at_source_return",
        label_values=classes, normalization_mean=mean.tolist(), normalization_std=std.tolist(),
        model_parameters=dict(input_size=6, hidden_size=args.hidden_size, output_size=len(classes),
                              sequence_length=10, grid_size=args.grid_size,
                              spline_order=args.spline_order, dropout=args.dropout),
        best_epoch=best["epoch"], validation_accuracy=best["accuracy"],
        validation_metrics=best, state_dict=model.state_dict(),
        formal_contract=dict(
            schema_version=1, observation_contract=OBSERVATION_CONTRACT,
            label_contract=LABEL_CONTRACT, normalization_split="train", calibration="none",
            dataset_manifest_sha256=args.dataset_sha256,
            source_code_sha256=manifest["source_code_sha256"], split_version=manifest["split_version"],
            training_seed=best["seed"], validation_only=manifest["validation_only"],
            threshold_gap=.1, threshold_min_second_probability=.1,
            selection_tolerance=args.selection_tolerance))


def _atomic_write(path, writer):
    """Publish a file only after its contents are durable, without truncating the old one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path, value):
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    _atomic_write(path, lambda stream: stream.write(encoded))


def _save_epoch(output, seed, state):
    """The small pointer is the commit; an unreferenced epoch file is never resumed."""
    relative = "resume-{}/epoch-{:05d}-{}.pt".format(seed, state["epoch"], uuid.uuid4().hex)
    checkpoint = output / relative
    _atomic_write(checkpoint, lambda stream: torch.save(state, stream))
    pointer = dict(schema_version=1, identity=state["identity"], seed=seed,
                   epoch=state["epoch"], complete=state["complete"],
                   path=relative, sha256=sha256_file(checkpoint))
    _atomic_json(output / "resume-{}.json".format(seed), pointer)
    return pointer


def _load_epoch(output, seed, identity):
    path = output / "resume-{}.json".format(seed)
    if not path.exists():
        return None
    pointer = read_json(path)
    checkpoint = (output / pointer["path"]).resolve()
    if output.resolve() not in checkpoint.parents:
        raise ValueError("resume checkpoint is outside the training session")
    if pointer.get("schema_version") != 1 or pointer.get("identity") != identity or pointer.get("seed") != seed:
        raise ValueError("resume identity differs from training configuration")
    verify_hash(checkpoint, pointer["sha256"])
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    if (state.get("identity"), state.get("seed"), state.get("epoch"), state.get("complete")) != (
            identity, seed, pointer["epoch"], pointer["complete"]):
        raise ValueError("resume state does not match committed epoch")
    if len(state["history"]) != state["epoch"]:
        raise ValueError("resume history/epoch mismatch")
    return state


def _random_state(generator, device):
    return dict(python=random.getstate(), numpy=np.random.get_state(),
                torch=torch.get_rng_state().clone(), loader=generator.get_state().clone(),
                cuda=torch.cuda.get_rng_state_all() if device.type == "cuda" else None)


def _restore_random_state(state, generator, device):
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    generator.set_state(state["loader"])
    if device.type == "cuda":
        torch.cuda.set_rng_state_all(state["cuda"])


def _session_identity(args, scenario, model_class, device):
    settings = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
                if k not in ("output_root", "session_dir")}
    model_file = Path(inspect.getfile(model_class)).resolve()
    value = dict(schema_version=1, scenario=scenario, arguments=settings,
                 actual_device=str(device), python=sys.version, numpy=np.__version__,
                 torch=str(torch.__version__), model_class=model_class.__qualname__,
                 model_source_sha256=sha256_file(model_file),
                 trainer_source_sha256=sha256_file(Path(__file__)))
    identity = hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return identity, value


def _publish_candidate(output, seed, state):
    """Export the independent best weights; current weights remain in the resume package."""
    complete_path = output / "candidate-{}.complete.json".format(seed)
    if complete_path.exists():
        committed = read_json(complete_path)
        if committed["identity"] != state["identity"] or not state["complete"]:
            raise ValueError("completed candidate identity/state mismatch")
        candidate = committed["candidate"]
        verify_hash(candidate["checkpoint_path"], candidate["checkpoint_sha256"])
        verify_hash(candidate["history_path"], candidate["history_sha256"])
        return candidate
    model_path = output / "candidate-{}.pt".format(seed)
    history_path = output / "history-{}.jsonl".format(seed)
    _atomic_write(model_path, lambda stream: torch.save(state["best_checkpoint"], stream))
    history = "".join(json.dumps(row, allow_nan=False) + "\n" for row in state["history"]).encode()
    _atomic_write(history_path, lambda stream: stream.write(history))
    candidate = dict(seed=seed, checkpoint_path=str(model_path), checkpoint_sha256=sha256_file(model_path),
                     metrics=state["best_checkpoint"]["validation_metrics"],
                     history_path=str(history_path), history_sha256=sha256_file(history_path))
    _atomic_json(complete_path, dict(identity=state["identity"], candidate=candidate))
    return candidate


def _train_session(args, scenario, model_class, manifest, mean, std, weights,
                   train_set, validation_loader, device):
    output = args.session_dir.expanduser().resolve()
    identity, definition = _session_identity(args, scenario, model_class, device)
    session_path = output / "training-session.json"
    if session_path.exists():
        session = read_json(session_path)
        if session != dict(identity=identity, definition=definition):
            raise ValueError("training session identity/configuration mismatch")
    else:
        if output.exists() and any(output.iterdir()):
            raise ValueError("nonempty session directory has no committed training identity")
        output.mkdir(parents=True, exist_ok=True)
        _atomic_json(session_path, dict(identity=identity, definition=definition))
        _atomic_json(output / "training-config.json", definition)
    classes = len(SCENARIO_LABELS[scenario])
    candidates, best_overall = [], None
    for seed in args.initialization_seeds:
        state = _load_epoch(output, seed, identity)
        if state is None or not state["complete"]:
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)
            if device.type == "cuda":
                torch.cuda.manual_seed_all(seed)
            generator = torch.Generator().manual_seed(seed)
            loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True, generator=generator)
            model = model_class(6, args.hidden_size, classes, args.grid_size,
                                args.spline_order, args.dropout).to(device)
            criterion = nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32, device=device))
            optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
            if state is None:
                state = dict(identity=identity, seed=seed, epoch=0, complete=False, stop_reason=None,
                             current_state=copy.deepcopy(model.state_dict()),
                             optimizer=copy.deepcopy(optimizer.state_dict()), best_checkpoint=None,
                             history=[], stalled=0, rng=_random_state(generator, device))
                _save_epoch(output, seed, state)
            else:
                model.load_state_dict(state["current_state"])
                optimizer.load_state_dict(state["optimizer"])
            # Construction/loading may consume RNG. Restore last, immediately
            # before the next loader iteration, including validation's CPU RNG.
            _restore_random_state(state["rng"], generator, device)
            for epoch in range(state["epoch"] + 1, args.epochs + 1):
                model.train()
                loss_sum, loss_weight = 0.0, 0.0
                for inputs, targets in loader:
                    inputs, targets = inputs.to(device), targets.to(device)
                    optimizer.zero_grad()
                    loss = criterion(model(inputs), targets)
                    if not torch.isfinite(loss):
                        raise ValueError("nonfinite training loss")
                    loss.backward()
                    if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()):
                        raise ValueError("nonfinite training gradient")
                    optimizer.step()
                    weight = criterion.weight[targets].sum().item()
                    loss_sum += loss.item() * weight
                    loss_weight += weight
                metrics = evaluate_loader(model, validation_loader, device, classes)
                metrics.update(epoch=epoch, seed=seed, train_loss=loss_sum / loss_weight)
                best = state["best_checkpoint"]
                if is_better(metrics, best["validation_metrics"] if best else None, args.selection_tolerance):
                    best = copy.deepcopy(_checkpoint(model, args, manifest, mean, std, metrics))
                    stalled = 0
                else:
                    stalled = state["stalled"] + 1
                stop = "early_stopping" if args.patience and stalled >= args.patience else (
                    "maximum_epochs" if epoch == args.epochs else None)
                state = dict(identity=identity, seed=seed, epoch=epoch, complete=stop is not None,
                             stop_reason=stop, current_state=copy.deepcopy(model.state_dict()),
                             optimizer=copy.deepcopy(optimizer.state_dict()), best_checkpoint=best,
                             history=state["history"] + [metrics], stalled=stalled,
                             rng=_random_state(generator, device))
                verify_hash(args.dataset_manifest, args.dataset_sha256)
                _save_epoch(output, seed, state)
                print("{} seed={} committed_epoch={} train_loss={:.6f} val_macro_f1={:.6f}".format(
                    scenario, seed, epoch, metrics["train_loss"], metrics["macro_f1"]), flush=True)
                if state["complete"]:
                    break
        if not state["complete"] or state["best_checkpoint"] is None:
            raise ValueError("candidate did not reach a committed stopping condition")
        candidate = _publish_candidate(output, seed, state)
        candidates.append(candidate)
        if is_better(candidate["metrics"], best_overall["metrics"] if best_overall else None,
                     args.selection_tolerance):
            best_overall = candidate
    verify_hash(args.dataset_manifest, args.dataset_sha256)
    load_dataset_manifest(args.dataset_manifest)
    frozen_path = output / "model-manifest.json"
    if frozen_path.exists():
        result = read_json(frozen_path)
        if result["candidates"] != candidates or result["dataset_manifest_sha256"] != args.dataset_sha256:
            raise ValueError("frozen model differs from completed training candidates")
        verify_hash(result["checkpoint_path"], result["checkpoint_sha256"])
        verify_hash(result["training_history"]["path"], result["training_history"]["sha256"])
        return result
    final_path = output / "checkpoint.pt"
    _atomic_write(final_path, lambda stream: stream.write(Path(best_overall["checkpoint_path"]).read_bytes()))
    selected_history = output / "training-history.csv"
    lines = ["epoch,train_loss,validation_loss,validation_macro_f1\r\n"]
    for line in Path(best_overall["history_path"]).read_text().splitlines():
        row = json.loads(line)
        lines.append("{epoch},{train_loss},{cross_entropy},{macro_f1}\r\n".format(**row))
    _atomic_write(selected_history, lambda stream: stream.write("".join(lines).encode()))
    result = dict(schema_version=1, scenario=scenario, frozen=True,
                  validation_only=manifest["validation_only"], checkpoint_path=str(final_path),
                  checkpoint_sha256=sha256_file(final_path), dataset_manifest=str(args.dataset_manifest),
                  dataset_manifest_sha256=args.dataset_sha256, selected_seed=best_overall["seed"],
                  validation_metrics=best_overall["metrics"], candidates=candidates, evaluation_opened=False,
                  training_history=dict(path=str(selected_history), sha256=sha256_file(selected_history)))
    _atomic_json(frozen_path, result)
    print("Frozen model: {}".format(final_path), flush=True)
    return result


def train(argv, scenario, model_class):
    args = formal_arguments(argv)
    args.dataset_manifest = args.dataset_manifest.resolve()
    manifest = load_dataset_manifest(args.dataset_manifest)
    args.dataset_sha256 = sha256_file(args.dataset_manifest)
    if manifest["scenario"] != scenario:
        raise ValueError("training scenario does not match dataset")
    if manifest["validation_only"] and not args.allow_validation_only:
        raise ValueError("validation_only dataset requires explicit --allow-validation-only")
    for name in ("epochs", "hidden_size", "grid_size", "spline_order", "batch_size", "threads"):
        if getattr(args, name) < 1:
            raise ValueError("{} must be positive".format(name))
    if (not math.isfinite(args.learning_rate) or args.learning_rate <= 0 or
            not 0 <= args.dropout < 1 or args.patience < 0 or
            not math.isfinite(args.selection_tolerance) or args.selection_tolerance < 0 or
            len(set(args.initialization_seeds)) != len(args.initialization_seeds) or
            any(seed < 0 or seed > 2**32 - 1 for seed in args.initialization_seeds)):
        raise ValueError("invalid optimization/selection settings")
    torch.set_num_threads(args.threads)
    device = _device(args.device)
    mean, std = normalization_statistics(args.dataset_manifest)
    classes = len(SCENARIO_LABELS[scenario])
    counts = np.asarray(manifest["splits"]["train"]["class_counts"], dtype=np.float64)
    if counts.shape != (classes,) or np.any(counts <= 0):
        raise ValueError("training is missing target classes")
    weights = counts.sum() / (classes * counts)
    train_set = MmapSnapshots(args.dataset_manifest, manifest, "train", mean, std)
    validation_set = MmapSnapshots(args.dataset_manifest, manifest, "validation", mean, std)
    validation_loader = DataLoader(validation_set, batch_size=args.batch_size, shuffle=False)
    if args.session_dir is not None:
        return _train_session(args, scenario, model_class, manifest, mean, std, weights,
                              train_set, validation_loader, device)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = args.output_root.resolve() / timestamp
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "training-config.json", dict(
        scenario=scenario, arguments={k: str(v) if isinstance(v, Path) else v
                                     for k, v in vars(args).items()},
        dataset_manifest_sha256=sha256_file(args.dataset_manifest),
        class_counts=counts.astype(np.int64).tolist(), class_weights=weights.tolist(),
        selection_rule="macro_f1 descending; unweighted CE ascending; epoch then seed ascending",
        normalization_mean=mean.tolist(), normalization_std=std.tolist()))
    candidates, best_overall = [], None
    for seed in args.initialization_seeds:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        generator = torch.Generator().manual_seed(seed)
        loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True, generator=generator)
        model = model_class(6, args.hidden_size, classes, args.grid_size,
                            args.spline_order, args.dropout).to(device)
        criterion = nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32, device=device))
        optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
        model_path = output / ("candidate-{}.pt".format(seed))
        history_path = output / ("history-{}.jsonl".format(seed))
        best, stalled = None, 0
        with history_path.open("w", encoding="utf-8") as history:
            for epoch in range(1, args.epochs + 1):
                model.train()
                loss_sum, loss_weight = 0.0, 0.0
                for inputs, targets in loader:
                    inputs, targets = inputs.to(device), targets.to(device)
                    optimizer.zero_grad()
                    loss = criterion(model(inputs), targets)
                    if not torch.isfinite(loss):
                        raise ValueError("nonfinite training loss")
                    loss.backward()
                    if any(p.grad is not None and not torch.isfinite(p.grad).all()
                           for p in model.parameters()):
                        raise ValueError("nonfinite training gradient")
                    optimizer.step()
                    weight = criterion.weight[targets].sum().item()
                    loss_sum += loss.item() * weight
                    loss_weight += weight
                metrics = evaluate_loader(model, validation_loader, device, classes)
                metrics.update(epoch=epoch, seed=seed, train_loss=loss_sum / loss_weight)
                history.write(json.dumps(metrics, allow_nan=False) + "\n")
                history.flush()
                if is_better(metrics, best, args.selection_tolerance):
                    best, stalled = metrics, 0
                    verify_hash(args.dataset_manifest, args.dataset_sha256)
                    torch.save(_checkpoint(model, args, manifest, mean, std, best), model_path)
                else:
                    stalled += 1
                print("{} seed={} epoch={} train_loss={:.6f} val_macro_f1={:.6f} val_ce={:.6f}".format(
                    scenario, seed, epoch, metrics["train_loss"], metrics["macro_f1"],
                    metrics["cross_entropy"]), flush=True)
                if args.patience and stalled >= args.patience:
                    break
        candidate = dict(seed=seed, checkpoint_path=str(model_path),
                         checkpoint_sha256=sha256_file(model_path), metrics=best,
                         history_path=str(history_path), history_sha256=sha256_file(history_path))
        candidates.append(candidate)
        if is_better(best, best_overall["metrics"] if best_overall else None, args.selection_tolerance):
            best_overall = candidate
    verify_hash(args.dataset_manifest, args.dataset_sha256)
    load_dataset_manifest(args.dataset_manifest)  # Recheck shards, raw evidence and inputs before freezing.
    final_path = output / "checkpoint.pt"
    shutil.copyfile(best_overall["checkpoint_path"], final_path)
    selected_history = output / "training-history.csv"
    with Path(best_overall["history_path"]).open(encoding="utf-8") as source:
        with selected_history.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("epoch", "train_loss", "validation_loss", "validation_macro_f1"))
            for line in source:
                row = json.loads(line)
                writer.writerow((row["epoch"], row["train_loss"], row["cross_entropy"], row["macro_f1"]))
    result = dict(
        schema_version=1, scenario=scenario, frozen=True,
        validation_only=manifest["validation_only"], checkpoint_path=str(final_path),
        checkpoint_sha256=sha256_file(final_path),
        dataset_manifest=str(args.dataset_manifest),
        dataset_manifest_sha256=sha256_file(args.dataset_manifest),
        selected_seed=best_overall["seed"], validation_metrics=best_overall["metrics"],
        candidates=candidates, evaluation_opened=False,
        training_history={"path": str(selected_history), "sha256": sha256_file(selected_history)})
    write_json(output / "model-manifest.json", result)
    print("Frozen model: {}".format(final_path), flush=True)
    return result


def evaluate_frozen_model(model_manifest_path, output_dir, allow_validation_only=False,
                          bootstrap_repetitions=10000, analysis_seed=20261021):
    """Explicit evaluation operation, never called by training or model selection."""
    model_manifest_path = Path(model_manifest_path).resolve()
    frozen = read_json(model_manifest_path)
    if frozen.get("schema_version") != 1 or frozen.get("frozen") is not True:
        raise ValueError("evaluation requires a frozen model manifest")
    if frozen.get("validation_only") and not allow_validation_only:
        raise ValueError("validation_only model cannot enter formal evaluation")
    if bootstrap_repetitions < 1 or analysis_seed < 0:
        raise ValueError("bootstrap repetitions and analysis seed must be positive/nonnegative")
    checkpoint_path = Path(frozen["checkpoint_path"])
    dataset_path = Path(frozen["dataset_manifest"])
    verify_hash(checkpoint_path, frozen["checkpoint_sha256"])
    verify_hash(dataset_path, frozen["dataset_manifest_sha256"])
    manifest = load_dataset_manifest(dataset_path)
    if manifest["scenario"] != frozen["scenario"]:
        raise ValueError("evaluation scenario differs from frozen model")
    controller_path = (Path(__file__).resolve().parents[3] / "scratch" /
                       "vndn-circle-simulator/vndn-circle-tkan-gym.py")
    spec = importlib.util.spec_from_file_location("_formal_evaluation_controller", controller_path)
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    torch.set_num_threads(1)
    model, checkpoint, _ = controller.load_model(
        checkpoint_path, torch.device("cpu"), expected_scenario=frozen["scenario"],
        require_formal=True, allow_validation_only=allow_validation_only)
    if checkpoint["formal_contract"]["dataset_manifest_sha256"] != frozen["dataset_manifest_sha256"]:
        raise ValueError("checkpoint and frozen dataset hashes differ")
    verify_hash(frozen["training_history"]["path"], frozen["training_history"]["sha256"])
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    classes = len(manifest["label_values"])
    combined = MetricAccumulator(classes)
    seed_metrics = {}
    subsets = {key: MetricAccumulator(classes) for key in
               ("handover", "non_handover", "empty_history", "short_history", "full_history")}
    per_run, exclusion_counts = [], defaultdict(int)
    with (output / "predictions.jsonl").open("w", encoding="utf-8") as prediction_file:
        for shard in manifest["shards"]:
            if shard["split"] != "evaluation":
                continue
            dataset = MmapSnapshots(
                dataset_path, manifest, "evaluation", checkpoint["normalization_mean"],
                checkpoint["normalization_std"], shards=[shard])
            loader = DataLoader(dataset, batch_size=256, shuffle=False)
            records = []
            with (dataset_path.parent / shard["samples"]).open(encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    if record["exclusion_reason"] is None:
                        if record.get("sample_index") != len(records):
                            raise ValueError("sample evidence indices do not match mmap rows")
                        records.append(record)
            if len(records) != shard["sample_count"]:
                raise ValueError("sample evidence count does not match shard")
            run_metrics = MetricAccumulator(classes)
            offset = 0
            with torch.no_grad():
                for features, targets in loader:
                    logits = model(features)
                    if not torch.isfinite(logits).all():
                        raise ValueError("nonfinite evaluation logits")
                    losses = nn.functional.cross_entropy(logits, targets, reduction="none").numpy()
                    probabilities = torch.softmax(logits, dim=1).numpy()
                    true_targets = targets.numpy()
                    selection = [selection_for_candidates(probabilities[index], record["candidate_rsu_ids"])
                                 for index, record in enumerate(records[offset:offset + len(targets)])]
                    first = np.array([row[0] for row in selection], dtype=np.int64)
                    second = np.array([row[1] for row in selection], dtype=np.int64)
                    extra = np.array([row[2] for row in selection], dtype=bool)
                    run_metrics.update(probabilities, true_targets, float(losses.sum(dtype=np.float64)),
                                       (first, second, extra))
                    for index, record in enumerate(records[offset:offset + len(targets)]):
                        if record["label"] != int(true_targets[index]):
                            raise ValueError("sample evidence label differs from mmap target")
                        history = record["actual_history_length"]
                        groups = ["handover" if record["handover"] else "non_handover",
                                  "empty_history" if history == 0 else (
                                      "short_history" if history < 10 else "full_history")]
                        for group in groups:
                            subsets[group].update(probabilities[index:index + 1],
                                                  true_targets[index:index + 1], losses[index],
                                                  (first[index:index + 1], second[index:index + 1],
                                                   extra[index:index + 1]))
                        selected = [int(first[index])]
                        if extra[index]:
                            selected.append(int(second[index]))
                        prediction_file.write(json.dumps(dict(
                            run_id=shard["run_id"], seed_family=shard["seed_family"],
                            condition_id=shard["condition_id"], **record,
                            probabilities=probabilities[index].tolist(),
                            predicted_rsu_id=int(probabilities[index].argmax()), selected_rsu_ids=selected,
                        ), allow_nan=False) + "\n")
                    offset += len(targets)
            combined.merge(run_metrics)
            seed = shard["seed_family"]
            if seed not in seed_metrics:
                seed_metrics[seed] = MetricAccumulator(classes)
            seed_metrics[seed].merge(run_metrics)
            per_run.append(dict(run_id=shard["run_id"], seed_family=seed,
                                condition_id=shard["condition_id"], **run_metrics.metrics()))
            for reason, count in shard["excluded"].items():
                exclusion_counts[reason] += count
    if not combined.count:
        raise ValueError("no independent evaluation samples")
    fields = ("accuracy", "macro_f1", "balanced_accuracy", "cross_entropy",
              "target_set_coverage", "mean_candidate_count", "brier_score")
    bootstrap_values = {field: [] for field in fields}
    undefined_replicates = 0
    seed_ids = sorted(seed_metrics)
    rng = np.random.RandomState(analysis_seed)
    if len(seed_ids) > 1:
        for _ in range(bootstrap_repetitions):
            current = MetricAccumulator(classes)
            for index in rng.randint(len(seed_ids), size=len(seed_ids)):
                current.merge(seed_metrics[seed_ids[index]])
            if not current.count:
                undefined_replicates += 1
                continue
            metrics = current.metrics()
            for field in fields:
                bootstrap_values[field].append(metrics[field])
    result = dict(
        schema_version=1, scenario=frozen["scenario"], split="evaluation",
        validation_only=manifest["validation_only"], model_sha256=frozen["checkpoint_sha256"],
        model_manifest=str(model_manifest_path), model_manifest_sha256=sha256_file(model_manifest_path),
        dataset_manifest_sha256=sha256_file(dataset_path), label_values=manifest["label_values"],
        **combined.metrics(), per_run=per_run,
        per_seed=[dict(seed_family=seed, **seed_metrics[seed].metrics()) for seed in seed_ids],
        subsets={name: value.metrics() for name, value in subsets.items()},
        unknown_label_and_exclusion_counts=dict(exclusion_counts),
        training_history=frozen["training_history"],
        bootstrap=dict(unit="whole master seed family; all conditions and sources stay together",
                       analysis_seed=analysis_seed, repetitions=bootstrap_repetitions,
                       independent_seed_count=len(seed_ids),
                       undefined_replicates=undefined_replicates,
                       confidence_intervals_95={
                           field: np.percentile(values, [2.5, 97.5]).tolist()
                           if values and not undefined_replicates else None
                           for field, values in bootstrap_values.items()},
                       limitation="one seed cannot estimate across-seed uncertainty"
                       if len(seed_ids) == 1 else (
                           "undefined resamples from zero-sample seed families; intervals unavailable"
                           if undefined_replicates else "pointwise percentile intervals")),
        prediction_file_sha256=sha256_file(output / "predictions.jsonl"))
    result["classification_scope"] = "all scene classes; selection coverage uses recorded candidates"
    verify_hash(checkpoint_path, frozen["checkpoint_sha256"])
    verify_hash(dataset_path, frozen["dataset_manifest_sha256"])
    load_dataset_manifest(dataset_path)
    write_json(output / "evaluation.json", result)
    return result


def evaluation_main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate a frozen model once on held-out seed families")
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-validation-only", action="store_true")
    parser.add_argument("--bootstrap-repetitions", type=int, default=10000)
    parser.add_argument("--analysis-seed", type=int, default=20261021)
    args = parser.parse_args(argv)
    result = evaluate_frozen_model(args.model_manifest, args.output_dir, args.allow_validation_only,
                                   args.bootstrap_repetitions, args.analysis_seed)
    print("Independent evaluation: {}".format(args.output_dir / "evaluation.json"))
    print("macro-F1: {:.6f}".format(result["macro_f1"]))
    return 0


if __name__ == "__main__":
    sys.exit(evaluation_main())
