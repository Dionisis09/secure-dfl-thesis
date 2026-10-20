"""Regression checks for deterministic image caching and deferred CUDA metrics."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from client import Client
from data_utils import CachedImageDataset, create_iid_client_loaders, create_non_iid_client_loaders, create_dirichlet_client_loaders, set_seed
from model import SimpleMLP


class Images(Dataset):
    def __init__(self, shape):
        generator = torch.Generator().manual_seed(777)
        source_shape = (103, shape[1], shape[2]) if shape[0] == 1 else (103, shape[1], shape[2], shape[0])
        self.data = torch.randint(0, 256, source_shape, dtype=torch.uint8, generator=generator)
        if shape[0] != 1:
            self.data = self.data.numpy()
        self.targets = torch.arange(103) % 10
        self.transform = transforms.ToTensor()

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        return self.transform(Image.fromarray(np.asarray(self.data[index]))), int(self.targets[index])


class ExecutionProfiles(unittest.TestCase):
    def test_values_order_and_rng(self):
        for shape in [(1, 28, 28), (3, 32, 32)]:
            original = Images(shape)
            before = torch.get_rng_state().clone()
            cached = CachedImageDataset(original)
            self.assertTrue(torch.equal(before, torch.get_rng_state()))
            for index in range(len(original)):
                self.assertTrue(torch.equal(original[index][0], cached[index][0]))
                self.assertEqual(original[index][1], cached[index][1])
            for partition in [create_iid_client_loaders, create_non_iid_client_loaders, create_dirichlet_client_loaders]:
                left = partition(original, 3, 16, seed=42)
                right = partition(cached, 3, 16, seed=42)
                for a, b in zip(left, right):
                    for (x, y), (cx, cy) in zip(a, b):
                        self.assertTrue(torch.equal(x, cx))
                        self.assertTrue(torch.equal(y, cy))

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA regression requires a GPU")
    def test_cuda_weights_losses_and_accuracy_exact(self):
        for shape in [(1, 28, 28), (3, 32, 32)]:
            for partition in [create_iid_client_loaders, create_non_iid_client_loaders, create_dirichlet_client_loaders]:
                set_seed(42)
                original = Images(shape)
                cached = CachedImageDataset(original, "cuda")
                left = partition(original, 3, 16, seed=42)
                right = partition(cached, 3, 16, seed=42)
                initial = SimpleMLP(input_shape=shape, num_classes=10)
                for a, b in zip(left, right):
                    legacy = Client(0, copy.deepcopy(initial), a, "cuda", 0.01, DataLoader(original, batch_size=16))
                    fast = Client(0, copy.deepcopy(initial), b, "cuda", 0.01, DataLoader(cached, batch_size=16), defer_metrics=True)
                    for _ in range(3):
                        self.assertEqual(legacy.train_local(2), fast.train_local(2))
                        self.assertEqual(legacy.evaluate(), fast.evaluate())
                        for name, value in legacy.get_state_dict().items():
                            self.assertTrue(torch.equal(value, fast.get_state_dict()[name]), name)


if __name__ == "__main__":
    unittest.main()
