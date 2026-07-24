"""Model aggregation and communication accounting utilities."""

from collections import OrderedDict
from typing import Iterable, Mapping

import torch
from torch import nn


StateDict = Mapping[str, torch.Tensor]


def average_state_dicts(state_dicts: Iterable[StateDict]) -> OrderedDict:
    """Return a new state dict containing the element-wise tensor average."""

    states = list(state_dicts)
    if not states:
        raise ValueError("at least one state_dict is required")

    expected_keys = list(states[0].keys())
    for state in states[1:]:
        if list(state.keys()) != expected_keys:
            raise ValueError("all state_dicts must have identical ordered keys")

    averaged = OrderedDict()
    for key in expected_keys:
        first_tensor = states[0][key]
        if torch.is_floating_point(first_tensor) or torch.is_complex(first_tensor):
            value = torch.zeros_like(first_tensor)
            for state in states:
                value.add_(state[key].to(device=value.device, dtype=value.dtype))
            value.div_(len(states))
            averaged[key] = value
        else:
            averaged[key] = first_tensor.clone()
    return averaged


def estimate_model_size_bytes(model: nn.Module) -> int:
    """Estimate bytes transmitted when all model parameters are exchanged."""

    return sum(parameter.numel() * parameter.element_size() for parameter in model.parameters())

