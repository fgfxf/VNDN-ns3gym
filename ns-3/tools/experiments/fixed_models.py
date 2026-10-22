"""Read-only provenance binding for historical models and a new runtime source.

This path deliberately keeps each checkpoint's training contract unchanged. It
is distinct from local-training freeze, whose source-equality rule stays strict.
"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENES = ('circle', 'grid', 'spidermap')
PROFILE = 'quick-fixed-model-v1'
POLICY = 'training-seed-reuse-exploratory'


def _read(path):
    with Path(path).open() as stream:
        return json.load(stream)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _record(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=_sha(path))


def _verify(record):
    path = Path(record['path'])
    if not path.is_absolute() or not path.is_file() or _sha(path) != record['sha256']:
        raise ValueError('external model dependency hash changed: ' + str(path))
    return path


def load_checkpoint(path, scene):
    """Use the actual controller's formal loader, without opening Gym or training."""
    import runpy
    import torch
    loader = runpy.run_path(str(ROOT / 'scratch/vndn-circle-simulator/vndn-circle-tkan-gym.py'))['load_model']
    _, checkpoint, _ = loader(Path(path), torch.device('cpu'), expected_scenario=scene,
                              require_formal=True, allow_validation_only=False)
    return checkpoint


def create_binding(plan, source_root, runtime_source_sha256):
    source_root = Path(source_root).resolve()
    source_design = _record(source_root / 'plan/design.json')
    historical = _read(source_design['path'])
    if historical.get('status') != 'formal-frozen' or historical.get('validation_only') is not False:
        raise ValueError('historical model campaign is not frozen non-validation evidence')
    if set(historical.get('models', {})) != set(SCENES):
        raise ValueError('historical source must freeze exactly three models')
    training_source = historical['source_sha256']
    binding = dict(schema_version=1, source_root=str(source_root), source_design=source_design,
                   training_source_sha256=training_source, runtime_source_sha256=runtime_source_sha256,
                   seed_policy=POLICY, dependencies={source_design['path']: source_design['sha256']}, scenes={})
    for scene in SCENES:
        checkpoint_record = copy.deepcopy(historical['models'][scene])
        checkpoint_path = _verify(checkpoint_record)
        manifest_record = _record(checkpoint_path.parent / 'model-manifest.json')
        manifest = _read(manifest_record['path'])
        if (manifest.get('scenario') != scene or manifest.get('frozen') is not True or
                manifest.get('validation_only') is not False or
                Path(manifest['checkpoint_path']).resolve() != checkpoint_path.resolve() or
                manifest['checkpoint_sha256'] != checkpoint_record['sha256']):
            raise ValueError('historical model manifest disagrees with frozen checkpoint: ' + scene)
        dataset_record = dict(path=str(Path(manifest['dataset_manifest']).resolve()),
                              sha256=manifest['dataset_manifest_sha256'])
        dataset = _read(_verify(dataset_record))
        specification = dict(path=str(Path(dataset['source_specification']).resolve()),
                             sha256=dataset['source_specification_sha256'])
        _verify(specification)
        if (dataset.get('scenario') != scene or dataset.get('validation_only') is not False or
                dataset.get('source_code_sha256') != training_source):
            raise ValueError('historical dataset scenario/source differs: ' + scene)
        checkpoint = load_checkpoint(checkpoint_path, scene)
        contract = checkpoint['formal_contract']
        if (contract['source_code_sha256'] != training_source or
                contract['dataset_manifest_sha256'] != dataset_record['sha256']):
            raise ValueError('historical checkpoint training source/dataset contract differs: ' + scene)
        if (any(contract[k] != dataset[k] for k in ('observation_contract', 'label_contract', 'split_version')) or
                checkpoint['feature_names'] != dataset['feature_names'] or
                checkpoint['label_values'] != dataset['label_values'] or
                checkpoint['model_parameters']['sequence_length'] != dataset['sequence_length']):
            raise ValueError('historical dataset and model input/label contract differ: ' + scene)
        training_seeds = dataset['splits']['train']['seed_families']
        reused = plan['test_seeds_by_scene'][scene]
        approved_seeds = {r['seed_family'] for r in historical.get('sampling_jobs', {}).get('train', [])
                          if r['scene'] == scene}
        if not set(reused).issubset(training_seeds) or not set(reused).issubset(approved_seeds):
            raise ValueError('requested reused seeds are absent from actual historical training: ' + scene)
        record = dict(checkpoint=checkpoint_record, model_manifest=manifest_record,
                      dataset_manifest=dataset_record, source_specification=specification,
                      training_source_sha256=training_source, train_seed_families=training_seeds,
                      reused_seed_families=copy.deepcopy(reused), formal_contract=copy.deepcopy(contract))
        binding['scenes'][scene] = record
        for name in ('checkpoint', 'model_manifest', 'dataset_manifest', 'source_specification'):
            artifact = record[name]
            binding['dependencies'][artifact['path']] = artifact['sha256']
    return binding


def check_external_models(plan):
    """Revalidate frozen artifacts and provenance without rewriting or retraining.

    Hashing includes the real checkpoint bytes; the formal controller reloads it
    on each neural run. The binding stores the contract validated by that loader
    during creation, together with the unchanged historical manifest identities.
    """
    if plan.get('design_profile') != PROFILE:
        raise ValueError('external model binding requires the fixed-model profile')
    binding = plan.get('external_models', {})
    if (binding.get('schema_version') != 1 or binding.get('seed_policy') != POLICY or
            set(binding.get('scenes', {})) != set(SCENES)):
        raise ValueError('missing or invalid external model binding')
    current = plan.get('source_sha256', plan.get('required_source_sha256'))
    if current != binding.get('runtime_source_sha256'):
        raise ValueError('external model runtime source differs from campaign')
    source_root = Path(binding['source_root'])
    design_record = binding['source_design']
    if Path(design_record['path']) != source_root / 'plan/design.json':
        raise ValueError('external model source root disagrees with design')
    required = {design_record['path']: design_record['sha256']}
    historical = _read(_verify(design_record))
    if (historical.get('status') != 'formal-frozen' or historical.get('validation_only') is not False or
            historical.get('source_sha256') != binding['training_source_sha256']):
        raise ValueError('historical model source identity changed')
    if set(plan.get('models', {})) != set(SCENES):
        raise ValueError('external campaign must retain all three models')
    for scene in SCENES:
        record = binding['scenes'][scene]
        if plan['models'][scene] != record['checkpoint'] or historical['models'][scene] != record['checkpoint']:
            raise ValueError('model is not the frozen historical checkpoint: ' + scene)
        for name in ('checkpoint', 'model_manifest', 'dataset_manifest', 'source_specification'):
            artifact = record[name]
            _verify(artifact)
            required[artifact['path']] = artifact['sha256']
        dataset = _read(record['dataset_manifest']['path'])
        manifest = _read(record['model_manifest']['path'])
        contract = record['formal_contract']
        training_source = binding['training_source_sha256']
        if (record['training_source_sha256'] != training_source or contract['source_code_sha256'] != training_source or
                dataset['source_code_sha256'] != training_source or dataset['scenario'] != scene or
                manifest['scenario'] != scene or dataset['validation_only'] is not False or
                manifest['frozen'] is not True or manifest['validation_only'] is not False):
            raise ValueError('external provenance scenario/training source differs: ' + scene)
        if (manifest['checkpoint_sha256'] != record['checkpoint']['sha256'] or
                Path(manifest['checkpoint_path']).resolve() != Path(record['checkpoint']['path']) or
                manifest['dataset_manifest_sha256'] != record['dataset_manifest']['sha256'] or
                Path(manifest['dataset_manifest']).resolve() != Path(record['dataset_manifest']['path']) or
                contract['dataset_manifest_sha256'] != record['dataset_manifest']['sha256'] or
                dataset['source_specification_sha256'] != record['source_specification']['sha256'] or
                Path(dataset['source_specification']).resolve() != Path(record['source_specification']['path'])):
            raise ValueError('external provenance dependency chain differs: ' + scene)
        if (record['reused_seed_families'] != plan['test_seeds_by_scene'][scene] or
                record['train_seed_families'] != dataset['splits']['train']['seed_families'] or
                not set(record['reused_seed_families']).issubset(record['train_seed_families'])):
            raise ValueError('external training-seed reuse differs: ' + scene)
        approved = {r['seed_family'] for r in historical.get('sampling_jobs', {}).get('train', []) if r['scene'] == scene}
        if not set(record['reused_seed_families']).issubset(approved):
            raise ValueError('external seeds were not historical training jobs: ' + scene)
        if any(contract[k] != dataset[k] for k in ('observation_contract', 'label_contract', 'split_version')):
            raise ValueError('external model observation/label contracts differ: ' + scene)
        if contract.get('threshold_gap') != .1 or contract.get('threshold_min_second_probability') != .1:
            raise ValueError('external model thresholds changed: ' + scene)
    if required != binding.get('dependencies'):
        raise ValueError('external model dependency inventory differs')
    return dict(required)
