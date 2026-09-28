"""Neural network models used by the baseline experiment."""

import math
from typing import Sequence

import torch
from torch import nn


class SimpleMLP(nn.Module):
    """A lightweight MLP for image-classification FL experiments."""

    def __init__(
        self,
        input_shape: Sequence[int] = (1, 28, 28),
        num_classes: int = 10,
    ) -> None:
        super().__init__()
        input_features = math.prod(input_shape)
        self.flatten = nn.Flatten()
        self.hidden = nn.Linear(input_features, 128)
        self.activation = nn.ReLU()
        self.output = nn.Linear(128, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.flatten(x)
        x = self.activation(self.hidden(x))
        return self.output(x)
