"""Dataset loading, reproducibility, and client partitioning utilities."""

import random
from typing import List, Tuple

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Subset
from torchvision import datasets, transforms


def set_seed(seed: int) -> None:
    """Seed Python, NumPy, and PyTorch for reproducible experiments."""

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    # These settings favor repeatability over maximum CUDA throughput.
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def get_mnist_datasets(data_dir: str) -> Tuple[Dataset, Dataset]:
    """Download (when necessary) and return MNIST train/test datasets."""

    transform = transforms.ToTensor()
    train_dataset = datasets.MNIST(
        root=data_dir, train=True, download=True, transform=transform
    )
    test_dataset = datasets.MNIST(
        root=data_dir, train=False, download=True, transform=transform
    )
    return train_dataset, test_dataset


def _balanced_partition_sizes(dataset_size: int, num_clients: int) -> List[int]:
    if num_clients <= 0:
        raise ValueError("num_clients must be greater than zero")
    if dataset_size < num_clients:
        raise ValueError("dataset must contain at least one sample per client")

    base_size, remainder = divmod(dataset_size, num_clients)
    return [base_size + (client_id < remainder) for client_id in range(num_clients)]


def create_iid_client_loaders(
    train_dataset: Dataset,
    num_clients: int,
    batch_size: int,
    seed: int = 42,
) -> List[DataLoader]:
    """Randomly divide training samples into balanced IID client partitions."""

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    generator = torch.Generator().manual_seed(seed)
    indices = torch.randperm(len(train_dataset), generator=generator).tolist()
    partition_sizes = _balanced_partition_sizes(len(train_dataset), num_clients)

    loaders: List[DataLoader] = []
    offset = 0
    for client_id, partition_size in enumerate(partition_sizes):
        client_indices = indices[offset : offset + partition_size]
        offset += partition_size
        loader_generator = torch.Generator().manual_seed(seed + client_id)
        loaders.append(
            DataLoader(
                Subset(train_dataset, client_indices),
                batch_size=batch_size,
                shuffle=True,
                generator=loader_generator,
            )
        )
    return loaders


def _extract_targets(dataset: Dataset) -> np.ndarray:
    """Extract labels from MNIST-like datasets, including Subset wrappers."""

    if isinstance(dataset, Subset):
        parent_targets = _extract_targets(dataset.dataset)
        return parent_targets[np.asarray(dataset.indices)]
    if not hasattr(dataset, "targets"):
        raise ValueError("non-IID partitioning requires a dataset with 'targets'")
    targets = getattr(dataset, "targets")
    if isinstance(targets, torch.Tensor):
        targets = targets.cpu().numpy()
    return np.asarray(targets)


def create_non_iid_client_loaders(
    train_dataset: Dataset,
    num_clients: int,
    batch_size: int,
    shards_per_client: int = 2,
    seed: int = 42,
) -> List[DataLoader]:
    """Create deterministic label-skewed partitions using sorted shards."""

    if num_clients <= 0 or shards_per_client <= 0:
        raise ValueError("num_clients and shards_per_client must be greater than zero")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    num_shards = num_clients * shards_per_client
    if len(train_dataset) < num_shards:
        raise ValueError("dataset must contain at least one sample per shard")

    labels = _extract_targets(train_dataset)
    sorted_indices = np.argsort(labels, kind="stable")
    shards = np.array_split(sorted_indices, num_shards)

    rng = np.random.default_rng(seed)
    shard_order = rng.permutation(num_shards)
    loaders: List[DataLoader] = []

    for client_id in range(num_clients):
        start = client_id * shards_per_client
        assigned = shard_order[start : start + shards_per_client]
        client_indices = np.concatenate([shards[index] for index in assigned]).tolist()
        loader_generator = torch.Generator().manual_seed(seed + client_id)
        loaders.append(
            DataLoader(
                Subset(train_dataset, client_indices),
                batch_size=batch_size,
                shuffle=True,
                generator=loader_generator,
            )
        )
    return loaders


def get_test_loader(test_dataset: Dataset, batch_size: int) -> DataLoader:
    """Return the shared, non-shuffled global test loader."""

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    return DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

