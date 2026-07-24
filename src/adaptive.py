"""Risk scoring and target selection for adaptive hybrid DFL security."""

import math
from typing import Dict, Mapping, Sequence, Set

import torch


StateDict = Mapping[str, torch.Tensor]


def compute_selected_update_norm(
    before_state: StateDict,
    after_state: StateDict,
    selected_param_names: Sequence[str],
) -> float:
    """Compute one L2 norm over updates to the selected parameters."""

    if not selected_param_names:
        raise ValueError("selected_param_names cannot be empty")

    squared_norm = 0.0
    for name in selected_param_names:
        if name not in before_state or name not in after_state:
            raise KeyError(f"selected parameter missing from client state: {name}")
        before = before_state[name]
        after = after_state[name]
        if before.shape != after.shape:
            raise ValueError(f"before/after shapes differ for parameter: {name}")
        difference = after.detach().cpu().double() - before.detach().cpu().double()
        squared_norm += difference.square().sum().item()
    return math.sqrt(squared_norm)


def compute_target_risk_scores(
    round_start_states: Mapping[int, StateDict],
    previous_states: Mapping[int, StateDict],
    topology: Mapping[int, Sequence[int]],
    selected_param_names: Sequence[str],
    split_type: str = "iid",
) -> Dict[int, float]:
    """Score each local aggregation neighborhood from selected-layer updates."""

    if set(round_start_states) != set(previous_states):
        raise ValueError("before/after state collections must contain the same clients")

    update_norms = {
        client_id: compute_selected_update_norm(
            round_start_states[client_id],
            previous_states[client_id],
            selected_param_names,
        )
        for client_id in previous_states
    }
    split_multiplier = 1.2 if split_type == "non_iid" else 1.0

    risk_scores: Dict[int, float] = {}
    for target_client_id, neighbors in topology.items():
        contributor_ids = [target_client_id, *neighbors]
        contributor_norms = [update_norms[client_id] for client_id in contributor_ids]
        maximum = max(contributor_norms)
        mean = sum(contributor_norms) / len(contributor_norms)
        risk_scores[target_client_id] = split_multiplier * (
            0.7 * maximum + 0.3 * mean
        )
    return risk_scores


def select_he_targets(
    risk_scores: Mapping[int, float],
    policy: str = "topk_risk",
    he_target_ratio: float = 0.4,
    threshold: float = 0.0,
    min_he_targets: int = 1,
    round_idx: int = 0,
    he_every_n_rounds: int = 5,
) -> Set[int]:
    """Select target neighborhoods for HE using a deterministic policy."""

    if not risk_scores:
        return set()
    if policy not in {"topk_risk", "threshold", "periodic"}:
        raise ValueError(f"unsupported adaptive policy: {policy}")
    if not 0.0 <= he_target_ratio <= 1.0:
        raise ValueError("he_target_ratio must be between 0 and 1")
    if min_he_targets < 0:
        raise ValueError("min_he_targets cannot be negative")
    if he_every_n_rounds <= 0:
        raise ValueError("he_every_n_rounds must be greater than zero")

    ordered_targets = sorted(
        risk_scores,
        key=lambda client_id: (-risk_scores[client_id], client_id),
    )

    if policy == "topk_risk":
        requested = math.ceil(len(risk_scores) * he_target_ratio)
        target_count = min(
            len(risk_scores), max(min_he_targets, requested)
        )
        return set(ordered_targets[:target_count])

    if policy == "threshold":
        selected = {
            client_id
            for client_id, risk_score in risk_scores.items()
            if risk_score >= threshold
        }
        return selected or {ordered_targets[0]}

    # round_idx is zero-based for the policy API.
    if (round_idx + 1) % he_every_n_rounds == 0:
        return set(risk_scores)
    return set()

