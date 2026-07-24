"""Peer-to-peer topology construction for decentralized learning."""

import random
from typing import Dict, List


Topology = Dict[int, List[int]]


def create_ring_topology(num_clients: int) -> Topology:
    """Connect each client to its predecessor and successor in a ring."""

    if num_clients <= 0:
        raise ValueError("num_clients must be greater than zero")
    if num_clients == 1:
        return {0: []}
    if num_clients == 2:
        return {0: [1], 1: [0]}
    topology = {
        client_id: [
            (client_id - 1) % num_clients,
            (client_id + 1) % num_clients,
        ]
        for client_id in range(num_clients)
    }
    # Match the conventional presentation: client 0 -> [1, last client].
    topology[0] = [1, num_clients - 1]
    return topology


def create_fully_connected_topology(num_clients: int) -> Topology:
    """Connect every client directly to every other client."""

    if num_clients <= 0:
        raise ValueError("num_clients must be greater than zero")
    return {
        client_id: [other for other in range(num_clients) if other != client_id]
        for client_id in range(num_clients)
    }


def create_random_topology(
    num_clients: int, degree: int = 2, seed: int = 42
) -> Topology:
    """Create a reproducible undirected topology with up to ``degree`` peers."""

    if num_clients <= 0:
        raise ValueError("num_clients must be greater than zero")
    if degree < 0:
        raise ValueError("degree cannot be negative")
    degree = min(degree, num_clients - 1)

    topology = {client_id: set() for client_id in range(num_clients)}
    if degree == 0:
        return {client_id: [] for client_id in range(num_clients)}

    # Start with a shuffled path so non-trivial random graphs are connected.
    nodes = list(range(num_clients))
    rng = random.Random(seed)
    rng.shuffle(nodes)
    if degree >= 2:
        for index, client_id in enumerate(nodes):
            neighbor_id = nodes[(index + 1) % num_clients]
            topology[client_id].add(neighbor_id)
            topology[neighbor_id].add(client_id)

    # Add random undirected edges without allowing either endpoint to exceed degree.
    candidate_edges = [
        (left, right)
        for left in range(num_clients)
        for right in range(left + 1, num_clients)
    ]
    rng.shuffle(candidate_edges)
    for left, right in candidate_edges:
        if len(topology[left]) < degree and len(topology[right]) < degree:
            topology[left].add(right)
            topology[right].add(left)

    return {
        client_id: sorted(neighbors)
        for client_id, neighbors in topology.items()
    }

