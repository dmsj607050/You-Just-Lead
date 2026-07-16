"""A fast deterministic binary-classification runner used to verify the workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_synthetic_binary_classification(
    config: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    """Train a tiny PyTorch baseline and return metrics plus epoch history.

    This is an executable reference adapter, not a claim that every competition is
    a classification task. Future task adapters use the same result contract.
    """
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for the synthetic reference runner. "
            "Install the training optional dependency."
        ) from exc

    data = config.get("data", {})
    model_config = config.get("model", {})
    training = config.get("training", {})
    optimizer_config = config.get("optimizer", {})
    seed = int(training.get("seed", 42))
    samples = int(data.get("synthetic_samples", 256))
    features = int(data.get("synthetic_features", 8))
    noise = float(data.get("synthetic_label_noise", 0.25))
    epochs = int(training.get("epochs", 8))
    batch_size = int(training.get("batch_size", 32))
    learning_rate = float(optimizer_config.get("learning_rate", 0.01))
    hidden_dim = int(model_config.get("hidden_dim", 16))

    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    inputs = torch.randn(samples, features, generator=generator)
    weights = torch.randn(features, generator=generator)
    labels = (inputs @ weights + noise * torch.randn(samples, generator=generator) > 0).long()

    split = max(1, int(samples * 0.8))
    train_x, valid_x = inputs[:split], inputs[split:]
    train_y, valid_y = labels[:split], labels[split:]
    if valid_x.numel() == 0:
        raise ValueError("synthetic_samples must leave at least one validation sample")

    requested_device = str(training.get("device", "cpu"))
    if requested_device == "cuda" and not torch.cuda.is_available():
        requested_device = "cpu"
    device = torch.device(requested_device)

    network = nn.Sequential(
        nn.Linear(features, hidden_dim),
        nn.ReLU(),
        nn.Linear(hidden_dim, 2),
    ).to(device)
    optimiser = torch.optim.AdamW(network.parameters(), lr=learning_rate)
    criterion = nn.CrossEntropyLoss()
    history: list[dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        network.train()
        order = torch.randperm(train_x.shape[0], generator=generator)
        total_loss = 0.0
        correct = 0
        seen = 0
        for start in range(0, train_x.shape[0], batch_size):
            indices = order[start : start + batch_size]
            batch_x = train_x[indices].to(device)
            batch_y = train_y[indices].to(device)
            optimiser.zero_grad()
            logits = network(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimiser.step()
            total_loss += float(loss.item()) * len(indices)
            correct += int((logits.argmax(dim=1) == batch_y).sum().item())
            seen += len(indices)

        network.eval()
        with torch.no_grad():
            valid_logits = network(valid_x.to(device))
            valid_loss = float(criterion(valid_logits, valid_y.to(device)).item())
            valid_accuracy = float(
                (valid_logits.argmax(dim=1) == valid_y.to(device)).float().mean().item()
            )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": total_loss / seen,
                "train_accuracy": correct / seen,
                "val_loss": valid_loss,
                "val_accuracy": valid_accuracy,
            }
        )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = artifact_dir / "model.pt"
    torch.save(
        {
            "state_dict": network.state_dict(),
            "seed": seed,
            "config": config,
        },
        checkpoint_path,
    )
    peak_memory_gb = None
    if device.type == "cuda":
        peak_memory_gb = torch.cuda.max_memory_allocated(device) / (1024**3)

    best = max(history, key=lambda point: point["val_accuracy"])
    return {
        "history": history,
        "metrics": {
            "val_accuracy": best["val_accuracy"],
            "val_loss_at_best_accuracy": best["val_loss"],
            "train_accuracy_at_best": best["train_accuracy"],
        },
        "best_epoch": int(best["epoch"]),
        "validation_metric": best["val_accuracy"],
        "peak_gpu_memory_gb": peak_memory_gb,
        "artifact_paths": [str(checkpoint_path)],
    }
