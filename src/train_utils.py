"""Experiment-level training and evaluation helpers."""

from collections import OrderedDict
from typing import List, Sequence, Tuple

from torch.utils.data import DataLoader

from aggregation import average_state_dicts
from client import Client


def evaluate_all_clients(
    clients: Sequence[Client], test_loader: DataLoader
) -> Tuple[float, float, List[float]]:
    """Evaluate each peer on the global test set and average its metrics."""

    if not clients:
        raise ValueError("at least one client is required")

    losses = []
    accuracies = []
    for client in clients:
        loss, accuracy = client.evaluate(test_loader)
        losses.append(loss)
        accuracies.append(accuracy)

    return (
        sum(losses) / len(losses),
        sum(accuracies) / len(accuracies),
        accuracies,
    )


def get_average_model_state(clients: Sequence[Client]) -> OrderedDict:
    """Return a virtual global average for reporting; no server is created."""

    if not clients:
        raise ValueError("at least one client is required")
    return average_state_dicts(client.get_state_dict() for client in clients)

