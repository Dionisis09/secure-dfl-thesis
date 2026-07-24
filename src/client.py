"""Client-side local training and evaluation logic."""

from collections import OrderedDict
from typing import Dict, Optional, Tuple

import torch
from torch import nn
from torch.utils.data import DataLoader


class Client:
    """A peer that owns local data and a complete model replica."""

    def __init__(
        self,
        client_id: int,
        model: nn.Module,
        train_loader: DataLoader,
        device: str,
        learning_rate: float,
        test_loader: Optional[DataLoader] = None,
    ) -> None:
        self.client_id = client_id
        self.device = torch.device(device)
        self.model = model.to(self.device)
        self.train_loader = train_loader
        self.test_loader = test_loader
        self.optimizer = torch.optim.SGD(self.model.parameters(), lr=learning_rate)
        self.criterion = nn.CrossEntropyLoss()

    def train_local(self, local_epochs: int) -> float:
        """Train on local data and return sample-weighted mean training loss."""

        if local_epochs <= 0:
            raise ValueError("local_epochs must be greater than zero")

        self.model.train()
        total_loss = 0.0
        total_samples = 0

        for _ in range(local_epochs):
            for inputs, targets in self.train_loader:
                inputs = inputs.to(self.device)
                targets = targets.to(self.device)

                self.optimizer.zero_grad()
                outputs = self.model(inputs)
                loss = self.criterion(outputs, targets)
                loss.backward()
                self.optimizer.step()

                batch_size = targets.size(0)
                total_loss += loss.item() * batch_size
                total_samples += batch_size

        return total_loss / total_samples if total_samples else 0.0

    @torch.no_grad()
    def evaluate(self, data_loader: Optional[DataLoader] = None) -> Tuple[float, float]:
        """Evaluate the local model and return sample-weighted loss and accuracy."""

        loader = data_loader or self.test_loader
        if loader is None:
            raise ValueError("a data loader is required for evaluation")

        self.model.eval()
        total_loss = 0.0
        total_correct = 0
        total_samples = 0

        for inputs, targets in loader:
            inputs = inputs.to(self.device)
            targets = targets.to(self.device)
            outputs = self.model(inputs)
            loss = self.criterion(outputs, targets)

            batch_size = targets.size(0)
            total_loss += loss.item() * batch_size
            total_correct += (outputs.argmax(dim=1) == targets).sum().item()
            total_samples += batch_size

        if total_samples == 0:
            return 0.0, 0.0
        return total_loss / total_samples, 100.0 * total_correct / total_samples

    def get_state_dict(self) -> OrderedDict:
        """Return an independent CPU snapshot of the current model state."""

        return OrderedDict(
            (key, value.detach().cpu().clone())
            for key, value in self.model.state_dict().items()
        )

    def set_state_dict(self, state_dict: Dict[str, torch.Tensor]) -> None:
        """Replace the local model state with an aggregated state."""

        self.model.load_state_dict(state_dict, strict=True)

