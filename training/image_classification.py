"""A compact image-classification baseline with auditable CSV predictions.

The adapter deliberately uses a small CNN and folder-per-class training data. It
is a reliable baseline for competition iteration, not a claim of a best model.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _dependencies() -> tuple[Any, Any, Any]:
    try:
        import torch
        from PIL import Image
        from torch import nn
    except ImportError as exc:
        raise RuntimeError(
            "image_classification requires the optional training dependency (torch) and Pillow."
        ) from exc
    return torch, Image, nn


def _parse_size(value: Any) -> tuple[int, int]:
    if isinstance(value, int):
        height = width = value
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        height, width = int(value[0]), int(value[1])
    else:
        raise ValueError("data.image_size must be an integer or [height, width]")
    if height < 16 or width < 16:
        raise ValueError("data.image_size dimensions must be at least 16")
    return height, width


def _image_tensor(path: Path, size: tuple[int, int]) -> Any:
    torch, Image, _ = _dependencies()
    with Image.open(path) as image:
        resized = image.convert("RGB").resize((size[1], size[0]), Image.Resampling.BILINEAR)
        values = torch.frombuffer(bytearray(resized.tobytes()), dtype=torch.uint8)
    return values.reshape(size[0], size[1], 3).permute(2, 0, 1).float().div(255)


def _class_samples(train_dir: Path) -> tuple[list[tuple[Path, int]], list[str]]:
    if not train_dir.is_dir():
        raise FileNotFoundError(f"Image training directory does not exist: {train_dir}")
    class_dirs = [path for path in sorted(train_dir.iterdir()) if path.is_dir()]
    if len(class_dirs) < 2:
        raise ValueError("data.train_images_dir must contain at least two class-named subdirectories")
    class_names = [path.name for path in class_dirs]
    samples: list[tuple[Path, int]] = []
    for label, class_dir in enumerate(class_dirs):
        paths = [path for path in sorted(class_dir.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
        if len(paths) < 2:
            raise ValueError(f"Class '{class_dir.name}' needs at least two supported images")
        samples.extend((path, label) for path in paths)
    return samples, class_names


def _test_images(directory: Path) -> list[tuple[str, Path]]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Test image directory does not exist: {directory}")
    indexed = [(path.stem, path) for path in sorted(directory.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    if not indexed:
        raise ValueError(f"No supported test images found in {directory}")
    identifiers = [item[0] for item in indexed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Test image stems must be unique for CSV submission generation")
    return indexed


def _stratified_split(samples: list[tuple[Path, int]], validation_fraction: float, seed: int) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    torch, _, _ = _dependencies()
    if not 0.05 <= validation_fraction < 0.5:
        raise ValueError("data.validation_fraction must be between 0.05 and 0.5")
    grouped: dict[int, list[tuple[Path, int]]] = defaultdict(list)
    for sample in samples:
        grouped[sample[1]].append(sample)
    generator = torch.Generator().manual_seed(seed)
    train: list[tuple[Path, int]] = []
    validation: list[tuple[Path, int]] = []
    for label in sorted(grouped):
        group = grouped[label]
        order = torch.randperm(len(group), generator=generator).tolist()
        validation_count = max(1, round(len(group) * validation_fraction))
        validation_count = min(validation_count, len(group) - 1)
        validation.extend(group[index] for index in order[:validation_count])
        train.extend(group[index] for index in order[validation_count:])
    return train, validation


def _tiny_classifier(base_channels: int, classes: int, dropout: float) -> Any:
    _, _, nn = _dependencies()
    if base_channels < 2:
        raise ValueError("model.base_channels must be at least 2")
    if not 0 <= dropout < 1:
        raise ValueError("model.dropout must be in [0, 1)")
    return nn.Sequential(
        nn.Conv2d(3, base_channels, kernel_size=3, padding=1),
        nn.BatchNorm2d(base_channels),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
        nn.Conv2d(base_channels, base_channels * 2, kernel_size=3, padding=1),
        nn.BatchNorm2d(base_channels * 2),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
        nn.Conv2d(base_channels * 2, base_channels * 4, kernel_size=3, padding=1),
        nn.ReLU(inplace=True),
        nn.AdaptiveAvgPool2d((1, 1)),
        nn.Flatten(),
        nn.Dropout(dropout),
        nn.Linear(base_channels * 4, classes),
    )


class _ClassificationDataset:
    def __init__(self, samples: list[tuple[Path, int]], size: tuple[int, int]):
        self.samples = samples
        self.size = size

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[Any, int]:
        path, label = self.samples[index]
        return _image_tensor(path, self.size), label


def _evaluate(model: Any, loader: Any, device: Any, criterion: Any) -> tuple[float, float]:
    torch, _, _ = _dependencies()
    model.eval()
    total_loss = total_correct = total_samples = 0
    with torch.no_grad():
        for images, labels in loader:
            labels = labels.to(device)
            logits = model(images.to(device))
            total_loss += float(criterion(logits, labels).item()) * len(labels)
            total_correct += int(logits.argmax(dim=1).eq(labels).sum().item())
            total_samples += len(labels)
    return total_loss / total_samples, total_correct / total_samples


def run_image_classification(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Train a lightweight folder-label classifier and optionally emit predictions."""
    torch, _, _ = _dependencies()
    data = config["data"]
    model_config = config.get("model", {})
    training = config["training"]
    optimizer_config = config.get("optimizer", {})
    seed = int(training.get("seed", 42))
    size = _parse_size(data.get("image_size", [128, 128]))
    samples, class_names = _class_samples(Path(str(data.get("train_images_dir", ""))).expanduser().resolve())
    train_samples, validation_samples = _stratified_split(samples, float(data.get("validation_fraction", 0.2)), seed)
    batch_size = int(training.get("batch_size", 16))
    if batch_size < 1:
        raise ValueError("training.batch_size must be positive")
    generator = torch.Generator().manual_seed(seed)
    loader_kwargs = {"batch_size": batch_size, "num_workers": int(training.get("num_workers", 0))}
    train_loader = torch.utils.data.DataLoader(_ClassificationDataset(train_samples, size), shuffle=True, generator=generator, **loader_kwargs)
    validation_loader = torch.utils.data.DataLoader(_ClassificationDataset(validation_samples, size), shuffle=False, **loader_kwargs)

    torch.manual_seed(seed)
    device_name = str(training.get("device", "cpu"))
    if device_name.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(device_name)
    base_channels = int(model_config.get("base_channels", 16))
    dropout = float(model_config.get("dropout", 0.1))
    model = _tiny_classifier(base_channels, len(class_names), dropout).to(device)
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(optimizer_config.get("learning_rate", 1e-3)),
        weight_decay=float(optimizer_config.get("weight_decay", 0.0)),
    )
    epochs = int(training.get("epochs", 20))
    if epochs < 1:
        raise ValueError("training.epochs must be positive")

    history: list[dict[str, float]] = []
    best_accuracy, best_epoch, best_state = -1.0, 1, None
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = train_correct = train_count = 0
        for images, labels in train_loader:
            labels = labels.to(device)
            logits = model(images.to(device))
            loss = criterion(logits, labels)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * len(labels)
            train_correct += int(logits.argmax(dim=1).eq(labels).sum().item())
            train_count += len(labels)
        validation_loss, validation_accuracy = _evaluate(model, validation_loader, device, criterion)
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss / train_count,
                "train_accuracy": train_correct / train_count,
                "val_loss": validation_loss,
                "val_accuracy": validation_accuracy,
            }
        )
        if validation_accuracy > best_accuracy:
            best_accuracy, best_epoch = validation_accuracy, epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training did not produce a model checkpoint")
    model.load_state_dict(best_state)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = artifact_dir / "model.pt"
    torch.save(
        {
            "state_dict": best_state,
            "image_size": size,
            "base_channels": base_channels,
            "class_names": class_names,
            "config": config,
        },
        checkpoint_path,
    )
    label_map_path = artifact_dir / "label_map.json"
    label_map_path.write_text(
        json.dumps({str(index): name for index, name in enumerate(class_names)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    artifact_paths = [str(checkpoint_path), str(label_map_path)]

    validation_predictions_path = artifact_dir / "validation_predictions.jsonl"
    model.eval()
    with validation_predictions_path.open("w", encoding="utf-8") as handle:
        with torch.no_grad():
            for image_path, true_label in validation_samples:
                probabilities = model(_image_tensor(image_path, size).unsqueeze(0).to(device)).softmax(dim=1).squeeze(0)
                confidence, predicted_label = probabilities.max(dim=0)
                handle.write(
                    json.dumps(
                        {
                            "path": str(image_path),
                            "true_label": class_names[true_label],
                            "predicted_label": class_names[int(predicted_label.item())],
                            "confidence": float(confidence.item()),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
    artifact_paths.append(str(validation_predictions_path))

    if data.get("test_images_dir"):
        test_items = _test_images(Path(str(data["test_images_dir"])).expanduser().resolve())
        model.eval()
        prediction_column = str(data.get("prediction_column") or "label")
        id_column = str(data.get("id_column") or "id")
        submission_path = artifact_dir / "submission.csv"
        with submission_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[id_column, prediction_column])
            writer.writeheader()
            with torch.no_grad():
                for identifier, image_path in test_items:
                    label = int(model(_image_tensor(image_path, size).unsqueeze(0).to(device)).argmax(dim=1).item())
                    writer.writerow({id_column: identifier, prediction_column: class_names[label]})
        artifact_paths.append(str(submission_path))

    peak_memory = round(torch.cuda.max_memory_allocated(device) / 1024**3, 4) if device.type == "cuda" else None
    best = history[best_epoch - 1]
    return {
        "history": history,
        "best_epoch": best_epoch,
        "validation_metric": best_accuracy,
        "metrics": {
            "val_accuracy": best_accuracy,
            "val_loss_at_best_accuracy": best["val_loss"],
            "classes": float(len(class_names)),
        },
        "peak_gpu_memory_gb": peak_memory,
        "artifact_paths": artifact_paths,
    }
