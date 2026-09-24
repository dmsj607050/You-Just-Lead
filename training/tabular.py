"""A reproducible PyTorch adapter for CSV binary or multiclass competitions."""

from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Any


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if not fields:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader), fields


def _features(rows: list[dict[str, str]], columns: list[str], path: Path) -> list[list[float]]:
    matrix: list[list[float]] = []
    for index, row in enumerate(rows, 2):
        values: list[float] = []
        for column in columns:
            try:
                values.append(float(row[column]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Non-numeric or missing feature '{column}' in {path} row {index}") from exc
        matrix.append(values)
    if not matrix:
        raise ValueError(f"CSV contains no data rows: {path}")
    return matrix


def _evaluate(model: Any, features: Any, labels: Any, criterion: Any) -> tuple[float, float]:
    import torch

    model.eval()
    with torch.no_grad():
        logits = model(features)
        loss = float(criterion(logits, labels).item())
        accuracy = float((logits.argmax(dim=1) == labels).float().mean().item())
    return loss, accuracy


def run_tabular_classification(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Train an MLP on a numeric CSV and optionally create a local submission CSV."""
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("tabular_classification requires the optional training dependency (torch).") from exc

    data = config["data"]
    model_config = config.get("model", {})
    training = config["training"]
    optimizer_config = config.get("optimizer", {})
    train_path = Path(str(data.get("train_csv", ""))).expanduser().resolve()
    if not train_path.is_file():
        raise FileNotFoundError(f"data.train_csv must point to an existing CSV: {train_path}")
    target_column = str(data.get("target_column", "")).strip()
    if not target_column:
        raise ValueError("data.target_column is required for tabular_classification")

    rows, fields = _read_rows(train_path)
    if target_column not in fields:
        raise ValueError(f"Target column '{target_column}' is not present in {train_path}")
    id_column = data.get("id_column")
    configured_features = data.get("feature_columns")
    feature_columns = list(configured_features) if isinstance(configured_features, list) else [field for field in fields if field not in {target_column, id_column}]
    if not feature_columns:
        raise ValueError("No numeric feature columns remain after excluding target/id columns")
    matrix = _features(rows, feature_columns, train_path)
    label_values = [row[target_column] for row in rows]
    label_map = {label: index for index, label in enumerate(sorted(set(label_values)))}
    if len(label_map) < 2:
        raise ValueError("Classification requires at least two target classes")

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
    labels = torch.tensor([label_map[value] for value in label_values], dtype=torch.long)
    mean = features[train_indices].mean(dim=0)
    std = features[train_indices].std(dim=0).clamp_min(1e-6)
    normalized = (features - mean) / std
    train_features, train_labels = normalized[train_indices].to(device), labels[train_indices].to(device)
    validation_features, validation_labels = normalized[validation_indices].to(device), labels[validation_indices].to(device)

    hidden_dim = int(model_config.get("hidden_dim", 64))
    dropout = float(model_config.get("dropout", 0.0))
    if hidden_dim < 1 or not 0 <= dropout < 1:
        raise ValueError("model.hidden_dim must be positive and model.dropout must be in [0, 1)")
    layers: list[Any] = [torch.nn.Linear(len(feature_columns), hidden_dim), torch.nn.ReLU()]
    if dropout:
        layers.append(torch.nn.Dropout(dropout))
    layers.append(torch.nn.Linear(hidden_dim, len(label_map)))
    model = torch.nn.Sequential(*layers).to(device)
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(optimizer_config.get("learning_rate", 1e-3)), weight_decay=float(optimizer_config.get("weight_decay", 0.0)))
    epochs = int(training.get("epochs", 20))
    batch_size = int(training.get("batch_size", 64))
    if epochs < 1 or batch_size < 1:
        raise ValueError("training.epochs and training.batch_size must be positive")

    history: list[dict[str, float]] = []
    best_accuracy, best_epoch, best_state = -1.0, 1, None
    batch_generator = torch.Generator(device="cpu").manual_seed(seed)
    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(train_features), generator=batch_generator)
        for start in range(0, len(order), batch_size):
            batch = order[start : start + batch_size].to(device)
            logits = model(train_features[batch])
            loss = criterion(logits, train_labels[batch])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        train_loss, train_accuracy = _evaluate(model, train_features, train_labels, criterion)
        validation_loss, validation_accuracy = _evaluate(model, validation_features, validation_labels, criterion)
        history.append({"epoch": float(epoch), "train_loss": train_loss, "train_accuracy": train_accuracy, "val_loss": validation_loss, "val_accuracy": validation_accuracy})
        if validation_accuracy > best_accuracy:
            best_accuracy, best_epoch = validation_accuracy, epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training did not produce a model state")
    model.load_state_dict(best_state)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.pt"
    torch.save({"state_dict": best_state, "feature_columns": feature_columns, "label_map": label_map, "mean": mean.cpu(), "std": std.cpu()}, model_path)
    artifact_paths = [str(model_path)]

    test_csv = data.get("test_csv")
    if test_csv:
        test_path = Path(str(test_csv)).expanduser().resolve()
        test_rows, _ = _read_rows(test_path)
        test_features = torch.tensor(_features(test_rows, feature_columns, test_path), dtype=torch.float32)
        model.eval()
        with torch.no_grad():
            predictions = model(((test_features - mean) / std).to(device)).argmax(dim=1).cpu().tolist()
        inverse_labels = {index: label for label, index in label_map.items()}
        submission_path = artifact_dir / "submission.csv"
        prediction_column = str(data.get("prediction_column", target_column))
        submission_id = str(id_column) if id_column else "row_id"
        with submission_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[submission_id, prediction_column])
            writer.writeheader()
            for index, (row, prediction) in enumerate(zip(test_rows, predictions)):
                writer.writerow({submission_id: row.get(submission_id, index), prediction_column: inverse_labels[prediction]})
        artifact_paths.append(str(submission_path))

    peak_memory = round(torch.cuda.max_memory_allocated(device) / 1024**3, 4) if device.type == "cuda" else None
    return {
        "history": history,
        "best_epoch": best_epoch,
        "validation_metric": best_accuracy,
        "metrics": {"val_accuracy": best_accuracy, "train_accuracy_at_best": history[best_epoch - 1]["train_accuracy"], "val_loss_at_best_accuracy": history[best_epoch - 1]["val_loss"]},
        "peak_gpu_memory_gb": peak_memory,
        "artifact_paths": artifact_paths,
    }
