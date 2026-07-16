"""Reproducible PyTorch baseline for numeric CSV regression competitions."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from training.tabular import _features, _read_rows


def _evaluate(model: Any, features: Any, targets: Any, criterion: Any) -> tuple[float, float]:
    import torch

    model.eval()
    with torch.no_grad():
        predictions = model(features).squeeze(1)
        mse = float(criterion(predictions, targets).item())
    return mse, float(torch.sqrt(torch.tensor(mse)).item())


def run_tabular_regression(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Fit a numeric MLP and optionally write a CSV prediction candidate."""
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("tabular_regression requires the optional training dependency (torch).") from exc

    data = config["data"]
    training = config["training"]
    model_config = config.get("model", {})
    optimizer_config = config.get("optimizer", {})
    train_path = Path(str(data.get("train_csv", ""))).expanduser().resolve()
    if not train_path.is_file():
        raise FileNotFoundError(f"data.train_csv must point to an existing CSV: {train_path}")
    target_column = str(data.get("target_column", "")).strip()
    rows, fields = _read_rows(train_path)
    if target_column not in fields:
        raise ValueError(f"Target column '{target_column}' is not present in {train_path}")
    id_column = data.get("id_column")
    configured_features = data.get("feature_columns")
    feature_columns = list(configured_features) if isinstance(configured_features, list) else [field for field in fields if field not in {target_column, id_column}]
    if not feature_columns:
        raise ValueError("No numeric feature columns remain after excluding target/id columns")
    matrix = _features(rows, feature_columns, train_path)
    try:
        targets_raw = [float(row[target_column]) for row in rows]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Target column '{target_column}' must be numeric for regression") from exc

    seed = int(training.get("seed", 42))
    random_generator = random.Random(seed)
    indices = list(range(len(rows)))
    random_generator.shuffle(indices)
    validation_fraction = float(data.get("validation_fraction", 0.2))
    if not 0.05 <= validation_fraction < 0.5:
        raise ValueError("data.validation_fraction must be between 0.05 and 0.5")
    validation_count = max(1, round(len(indices) * validation_fraction))
    train_indices, validation_indices = indices[validation_count:], indices[:validation_count]
    if not train_indices:
        raise ValueError("Training split is empty; provide more rows")

    torch.manual_seed(seed)
    device_name = str(training.get("device", "cpu"))
    if device_name.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(device_name)
    features = torch.tensor(matrix, dtype=torch.float32)
    targets = torch.tensor(targets_raw, dtype=torch.float32)
    mean = features[train_indices].mean(dim=0)
    std = features[train_indices].std(dim=0).clamp_min(1e-6)
    normalized = (features - mean) / std
    train_features, train_targets = normalized[train_indices].to(device), targets[train_indices].to(device)
    validation_features, validation_targets = normalized[validation_indices].to(device), targets[validation_indices].to(device)

    hidden_dim = int(model_config.get("hidden_dim", 64))
    dropout = float(model_config.get("dropout", 0.0))
    if hidden_dim < 1 or not 0 <= dropout < 1:
        raise ValueError("model.hidden_dim must be positive and model.dropout must be in [0, 1)")
    layers: list[Any] = [torch.nn.Linear(len(feature_columns), hidden_dim), torch.nn.ReLU()]
    if dropout:
        layers.append(torch.nn.Dropout(dropout))
    layers.append(torch.nn.Linear(hidden_dim, 1))
    model = torch.nn.Sequential(*layers).to(device)
    criterion = torch.nn.MSELoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(optimizer_config.get("learning_rate", 1e-3)), weight_decay=float(optimizer_config.get("weight_decay", 0.0)))
    epochs = int(training.get("epochs", 20))
    batch_size = int(training.get("batch_size", 64))
    if epochs < 1 or batch_size < 1:
        raise ValueError("training.epochs and training.batch_size must be positive")

    history: list[dict[str, float]] = []
    best_rmse, best_epoch, best_state = float("inf"), 1, None
    batch_generator = torch.Generator(device="cpu").manual_seed(seed)
    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(train_features), generator=batch_generator)
        for start in range(0, len(order), batch_size):
            batch = order[start : start + batch_size].to(device)
            prediction = model(train_features[batch]).squeeze(1)
            loss = criterion(prediction, train_targets[batch])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        train_loss, train_rmse = _evaluate(model, train_features, train_targets, criterion)
        validation_loss, validation_rmse = _evaluate(model, validation_features, validation_targets, criterion)
        history.append({"epoch": float(epoch), "train_loss": train_loss, "train_rmse": train_rmse, "val_loss": validation_loss, "val_rmse": validation_rmse})
        if validation_rmse < best_rmse:
            best_rmse, best_epoch = validation_rmse, epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training did not produce a model state")
    model.load_state_dict(best_state)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.pt"
    torch.save({"state_dict": best_state, "feature_columns": feature_columns, "mean": mean.cpu(), "std": std.cpu()}, model_path)
    artifact_paths = [str(model_path)]

    test_csv = data.get("test_csv")
    if test_csv:
        import csv

        test_path = Path(str(test_csv)).expanduser().resolve()
        test_rows, _ = _read_rows(test_path)
        test_features = torch.tensor(_features(test_rows, feature_columns, test_path), dtype=torch.float32)
        model.eval()
        with torch.no_grad():
            predictions = model(((test_features - mean) / std).to(device)).squeeze(1).cpu().tolist()
        submission_path = artifact_dir / "submission.csv"
        prediction_column = str(data.get("prediction_column", target_column))
        submission_id = str(id_column) if id_column else "row_id"
        with submission_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[submission_id, prediction_column])
            writer.writeheader()
            for index, (row, prediction) in enumerate(zip(test_rows, predictions)):
                writer.writerow({submission_id: row.get(submission_id, index), prediction_column: prediction})
        artifact_paths.append(str(submission_path))

    peak_memory = round(torch.cuda.max_memory_allocated(device) / 1024**3, 4) if device.type == "cuda" else None
    best = history[best_epoch - 1]
    return {"history": history, "best_epoch": best_epoch, "validation_metric": best_rmse, "metrics": {"val_rmse": best_rmse, "val_loss_at_best_rmse": best["val_loss"], "train_rmse_at_best": best["train_rmse"]}, "peak_gpu_memory_gb": peak_memory, "artifact_paths": artifact_paths}
