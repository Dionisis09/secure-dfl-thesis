"""Check dataset routing, RGB model dimensions and both partition schemes offline."""

import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from torchvision.datasets import FakeData
from torchvision.transforms import ToTensor

import mnist_network_demo as demo


class ImageDatasetTests(unittest.TestCase):
    def test_all_dataset_shapes_train_and_partition(self):
        for name, shape in (("mnist", (1, 28, 28)), ("fashion_mnist", (1, 28, 28)), ("cifar10", (3, 32, 32))):
            with self.subTest(dataset=name):
                data = FakeData(size=60, image_size=shape, num_classes=10, transform=ToTensor())
                data.targets = torch.tensor([data[i][1] for i in range(len(data))])
                spec = demo.get_dataset_spec(name)
                with patch.object(demo, "get_datasets", return_value=(data, data, spec)) as loader:
                    train, test = demo.load_demo_datasets(dataset_name=name, data_dir=Path("unused"), max_train_samples=30, max_test_samples=12, seed=42)
                loader.assert_called_once_with(name, "unused")
                self.assertEqual((len(train), len(test)), (30, 12))
                for partition in (demo.create_iid_client_loaders, demo.create_non_iid_client_loaders):
                    clients = partition(train, 3, 4, seed=42)
                    images, labels = next(iter(clients[0]))
                    model = demo.SimpleMLP(input_shape=spec.input_shape, num_classes=spec.num_classes)
                    output = model(images)
                    self.assertEqual(tuple(output.shape), (len(images), 10))
                    torch.nn.functional.cross_entropy(output, labels).backward()


if __name__ == "__main__":
    unittest.main()
