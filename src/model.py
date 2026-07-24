"""Neural network models used by the baseline experiment."""

import torch
from torch import nn


class SimpleMLP(nn.Module):
    """A lightweight multilayer perceptron for 28x28 MNIST images."""

    def __init__(self) -> None:
        super().__init__()
        self.flatten = nn.Flatten()
        self.hidden = nn.Linear(28 * 28, 128)
        self.activation = nn.ReLU()
        self.output = nn.Linear(128, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.flatten(x)
        x = self.activation(self.hidden(x))
        return self.output(x)

