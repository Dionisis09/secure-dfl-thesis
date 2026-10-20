"""Inspectable data partitions and final learning diagnostics, outside round timers."""
import hashlib
import numpy as np
import torch
from torch.utils.data import DataLoader
from data_utils import _extract_targets
from aggregation import average_state_dicts


def partition_metadata(dataset, loaders, topology):
    labels = _extract_targets(dataset)
    classes = sorted(int(c) for c in np.unique(labels))
    partitions = []
    all_indices = []
    for client_id, loader in enumerate(loaders):
        indices = np.asarray(loader.dataset.indices, dtype=np.int64)
        all_indices.extend(indices.tolist())
        counts = {str(c): int(np.count_nonzero(labels[indices] == c)) for c in classes}
        partitions.append({"client_id": client_id, "samples": len(indices),
                           "class_counts": counts,
                           "classes_present": sum(v > 0 for v in counts.values()),
                           "indices_sha256": hashlib.sha256(indices.astype('<i8').tobytes()).hexdigest()})
    degree_mass = [len(topology[i]) + 1 for i in range(len(loaders))]
    return {"partition_clients": partitions, "partition_complete": sorted(all_indices) == list(range(len(dataset))),
            "topology_adjacency": topology,
            "directed_transmissions_per_round": sum(map(len, topology.values())),
            "aggregation": "uniform_self_and_neighbors (equal model weight, not sample weight)",
            "fixed_graph_stationary_weights": [d / sum(degree_mass) for d in degree_mass],
            "stationary_weight_note": "For repeated mixing without training on an undirected graph. Irregular degrees do not yield uniform consensus weights."}


@torch.no_grad()
def _classification(client, loader, num_classes):
    confusion = torch.zeros((num_classes, num_classes), dtype=torch.long, device=client.device)
    client.model.eval()
    for x, y in loader:
        y = y.to(client.device)
        predicted = client.model(x.to(client.device)).argmax(1)
        confusion += torch.bincount(y * num_classes + predicted,
                                    minlength=num_classes ** 2).reshape(num_classes, num_classes)
    confusion = confusion.cpu()
    totals = confusion.sum(1)
    return {"accuracy_percent": float(100 * confusion.diag().sum().double() / confusion.sum()),
            "per_class_recall_percent": [float(100 * good / total) if total else None
                                         for good, total in zip(confusion.diag(), totals)],
            "confusion_matrix_true_by_predicted": confusion.tolist()}


def final_diagnostics(clients, dataset, test_loader):
    num_classes = clients[0].model.output.out_features
    rows = []
    for c in clients:
        # A separate sequential loader leaves the training sampler RNG intact.
        local_loader = DataLoader(c.train_loader.dataset, batch_size=test_loader.batch_size, shuffle=False)
        rows.append({"client_id": c.client_id,
                     "global_test": _classification(c, test_loader, num_classes),
                     "local_train": _classification(c, local_loader, num_classes)})
    original = clients[0].get_state_dict()
    try:
        clients[0].set_state_dict(average_state_dicts(c.get_state_dict() for c in clients))
        probe = _classification(clients[0], test_loader, num_classes)
    finally:
        clients[0].set_state_dict(original)
    return {"per_client": rows, "virtual_mean_model_test": probe,
            "note": "Virtual mean model is a diagnostic, not a central server or the reported mean-client accuracy."}
