"""Checkpoint-only validation: never opens evaluation data or connects Gym."""
import math
import re

from formal_data import LABEL_CONTRACT, OBSERVATION_CONTRACT


def validate_formal_contract(checkpoint, require_formal=False, allow_validation_only=False):
    contract = checkpoint.get("formal_contract")
    if contract is None:
        if require_formal:
            raise ValueError("formal model contract is required; legacy model rejected")
        return
    if not isinstance(contract, dict):
        raise ValueError("formal contract must be a dictionary")
    expected = dict(schema_version=1, observation_contract=OBSERVATION_CONTRACT,
                    label_contract=LABEL_CONTRACT, normalization_split="train",
                    calibration="none", threshold_gap=.1, threshold_min_second_probability=.1)
    for key, value in expected.items():
        if contract.get(key) != value or isinstance(contract.get(key), bool):
            raise ValueError("formal contract mismatch: {}".format(key))
    for key in ("dataset_manifest_sha256", "source_code_sha256"):
        if not isinstance(contract.get(key), str) or not re.fullmatch("[0-9a-f]{64}", contract[key]):
            raise ValueError("formal contract requires {}".format(key))
    if not isinstance(contract.get("split_version"), str) or not contract["split_version"]:
        raise ValueError("formal contract requires split_version")
    seed = contract.get("training_seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("formal contract training seed is invalid")
    tolerance = contract.get("selection_tolerance")
    if (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or
            not math.isfinite(tolerance) or tolerance < 0):
        raise ValueError("formal contract selection tolerance is invalid")
    if not isinstance(contract.get("validation_only"), bool):
        raise ValueError("formal contract requires explicit validation_only")
    if contract["validation_only"] and not allow_validation_only:
        raise ValueError("validation_only model requires an explicit development override")
    if checkpoint.get("forward_strategy") != "NoForward":
        raise ValueError("formal contract requires NoForward training")
