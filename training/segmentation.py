"""A compact, reproducible binary image-segmentation task adapter.

It is intentionally a baseline rather than a claim of state-of-the-art
performance.  It provides the same manifest/result/artifact contract as the
other runners and produces PNG masks that can be validated locally.
"""

from __future__ import annotations

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
            "image_segmentation requires the optional training dependency (torch) and Pillow."
        ) from exc
    return torch, Image, nn


def _parse_size(value: Any) -> tuple[int, int]:
    if isinstance(value, int):
        height = width = value
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        height, width = int(value[0]), int(value[1])
    else:
        raise ValueError("data.image_size must be an integer or [height, width]")
    if height < 16 or width < 16 or height % 4 or width % 4:
        raise ValueError("data.image_size dimensions must be multiples of 4 and at least 16")
    return height, width


def _index_images(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Image directory does not exist: {directory}")
    indexed = {
        path.stem: path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }
    if not indexed:
        raise ValueError(f"No supported image files found in {directory}")
    return indexed


def _image_tensor(path: Path, size: tuple[int, int]) -> tuple[Any, tuple[int, int]]:
    torch, Image, _ = _dependencies()
    with Image.open(path) as image:
        source = image.convert("RGB")
        original_size = (source.height, source.width)
        resized = source.resize((size[1], size[0]), Image.Resampling.BILINEAR)
        values = torch.frombuffer(bytearray(resized.tobytes()), dtype=torch.uint8)
    return values.reshape(size[0], size[1], 3).permute(2, 0, 1).float().div(255), original_size


def _mask_tensor(path: Path, size: tuple[int, int], threshold: int) -> Any:
    torch, Image, _ = _dependencies()
    with Image.open(path) as image:
        resized = image.convert("L").resize((size[1], size[0]), Image.Resampling.NEAREST)
        values = torch.frombuffer(bytearray(resized.tobytes()), dtype=torch.uint8)
    return values.reshape(1, size[0], size[1]).float().gt(threshold).float()


def _dice_from_logits(logits: Any, masks: Any, epsilon: float = 1e-6) -> Any:
    torch, _, _ = _dependencies()
    predictions = logits.sigmoid()
    intersection = (predictions * masks).sum(dim=(1, 2, 3))
    denominator = predictions.sum(dim=(1, 2, 3)) + masks.sum(dim=(1, 2, 3))
    return ((2 * intersection + epsilon) / (denominator + epsilon)).mean()


def _mean_iou(logits: Any, masks: Any, threshold: float) -> float:
    predictions = logits.sigmoid().ge(threshold)
    targets = masks.bool()
    intersection = (predictions & targets).sum(dim=(1, 2, 3)).float()
    union = (predictions | targets).sum(dim=(1, 2, 3)).float()
    return float(((intersection + 1e-6) / (union + 1e-6)).mean().item())


def _conv_block(nn: Any, inputs: int, outputs: int) -> Any:
    return nn.Sequential(
        nn.Conv2d(inputs, outputs, kernel_size=3, padding=1),
        nn.BatchNorm2d(outputs),
        nn.ReLU(inplace=True),
        nn.Conv2d(outputs, outputs, kernel_size=3, padding=1),
        nn.BatchNorm2d(outputs),
        nn.ReLU(inplace=True),
    )


def _tiny_unet(base_channels: int) -> Any:
    _, _, nn = _dependencies()

    class TinyUNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder_one = _conv_block(nn, 3, base_channels)
            self.pool_one = nn.MaxPool2d(2)
            self.encoder_two = _conv_block(nn, base_channels, base_channels * 2)
            self.pool_two = nn.MaxPool2d(2)
            self.bottleneck = _conv_block(nn, base_channels * 2, base_channels * 4)
            self.up_two = nn.ConvTranspose2d(base_channels * 4, base_channels * 2, kernel_size=2, stride=2)
            self.decoder_two = _conv_block(nn, base_channels * 4, base_channels * 2)
            self.up_one = nn.ConvTranspose2d(base_channels * 2, base_channels, kernel_size=2, stride=2)
            self.decoder_one = _conv_block(nn, base_channels * 2, base_channels)
            self.head = nn.Conv2d(base_channels, 1, kernel_size=1)

        def forward(self, image: Any) -> Any:
            torch, _, _ = _dependencies()
            first = self.encoder_one(image)
            second = self.encoder_two(self.pool_one(first))
            centre = self.bottleneck(self.pool_two(second))
            decoded_second = self.decoder_two(torch.cat([self.up_two(centre), second], dim=1))
            decoded_first = self.decoder_one(torch.cat([self.up_one(decoded_second), first], dim=1))
            return self.head(decoded_first)

    return TinyUNet()


class _SegmentationDataset:
    def __init__(self, pairs: list[tuple[str, Path, Path]], size: tuple[int, int], threshold: int):
        self.pairs = pairs
        self.size = size
        self.threshold = threshold

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int) -> tuple[Any, Any]:
        _, image_path, mask_path = self.pairs[index]
        image, _ = _image_tensor(image_path, self.size)
        return image, _mask_tensor(mask_path, self.size, self.threshold)


def _evaluate(model: Any, loader: Any, device: Any, bce: Any, dice_weight: float, threshold: float) -> tuple[float, float, float]:
    torch, _, _ = _dependencies()
    model.eval()
    total_loss = total_iou = total_dice = 0.0
    batches = 0
    with torch.no_grad():
        for images, masks in loader:
            logits = model(images.to(device))
            masks = masks.to(device)
            dice = _dice_from_logits(logits, masks)
            loss = bce(logits, masks) + dice_weight * (1 - dice)
            total_loss += float(loss.item())
            total_iou += _mean_iou(logits, masks, threshold)
            total_dice += float(dice.item())
            batches += 1
    return total_loss / batches, total_iou / batches, total_dice / batches


def run_image_segmentation(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Train a binary U-Net baseline and optionally emit one PNG per test image."""
    torch, Image, _ = _dependencies()
    data = config["data"]
    model_config = config.get("model", {})
    training = config["training"]
    optimizer_config = config.get("optimizer", {})
    size = _parse_size(data.get("image_size", [128, 128]))
    image_dir = Path(str(data.get("train_images_dir", ""))).expanduser().resolve()
    mask_dir = Path(str(data.get("train_masks_dir", ""))).expanduser().resolve()
    images, masks = _index_images(image_dir), _index_images(mask_dir)
    missing_masks = sorted(set(images) - set(masks))
    extra_masks = sorted(set(masks) - set(images))
    if missing_masks or extra_masks:
        detail = []
        if missing_masks:
            detail.append(f"missing masks for {', '.join(missing_masks[:5])}")
        if extra_masks:
            detail.append(f"masks without images: {', '.join(extra_masks[:5])}")
        raise ValueError("Image/mask pairing mismatch: " + "; ".join(detail))
    pairs = [(stem, images[stem], masks[stem]) for stem in sorted(images)]
    if len(pairs) < 3:
        raise ValueError("At least three paired images are required for train/validation segmentation")
    seed = int(training.get("seed", 42))
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(len(pairs), generator=generator).tolist()
    validation_fraction = float(data.get("validation_fraction", 0.2))
    if not 0.05 <= validation_fraction < 0.5:
        raise ValueError("data.validation_fraction must be between 0.05 and 0.5")
    validation_count = max(1, round(len(pairs) * validation_fraction))
    validation_pairs = [pairs[index] for index in order[:validation_count]]
    train_pairs = [pairs[index] for index in order[validation_count:]]
    mask_threshold = int(data.get("mask_foreground_threshold", 0))
    batch_size = int(training.get("batch_size", 4))
    if batch_size < 1:
        raise ValueError("training.batch_size must be positive")
    loader_kwargs = {"batch_size": batch_size, "num_workers": int(training.get("num_workers", 0))}
    train_loader = torch.utils.data.DataLoader(_SegmentationDataset(train_pairs, size, mask_threshold), shuffle=True, generator=generator, **loader_kwargs)
    validation_loader = torch.utils.data.DataLoader(_SegmentationDataset(validation_pairs, size, mask_threshold), shuffle=False, **loader_kwargs)

    torch.manual_seed(seed)
    device_name = str(training.get("device", "cpu"))
    if device_name.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(device_name)
    base_channels = int(model_config.get("base_channels", 16))
    if base_channels < 2:
        raise ValueError("model.base_channels must be at least 2")
    model = _tiny_unet(base_channels).to(device)
    bce = torch.nn.BCEWithLogitsLoss()
    dice_weight = float(model_config.get("dice_loss_weight", 0.5))
    if not 0 <= dice_weight <= 2:
        raise ValueError("model.dice_loss_weight must be between 0 and 2")
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(optimizer_config.get("learning_rate", 1e-3)), weight_decay=float(optimizer_config.get("weight_decay", 0.0)))
    epochs = int(training.get("epochs", 20))
    threshold = float(data.get("prediction_threshold", 0.5))
    if epochs < 1 or not 0 < threshold < 1:
        raise ValueError("training.epochs must be positive and data.prediction_threshold must be between 0 and 1")

    history: list[dict[str, float]] = []
    best_iou, best_epoch, best_state = -1.0, 1, None
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = train_iou = train_dice = 0.0
        batches = 0
        for images_batch, masks_batch in train_loader:
            images_batch, masks_batch = images_batch.to(device), masks_batch.to(device)
            logits = model(images_batch)
            dice = _dice_from_logits(logits, masks_batch)
            loss = bce(logits, masks_batch) + dice_weight * (1 - dice)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())
            train_iou += _mean_iou(logits.detach(), masks_batch, threshold)
            train_dice += float(dice.item())
            batches += 1
        validation_loss, validation_iou, validation_dice = _evaluate(model, validation_loader, device, bce, dice_weight, threshold)
        history.append({"epoch": float(epoch), "train_loss": train_loss / batches, "train_mean_iou": train_iou / batches, "train_dice": train_dice / batches, "val_loss": validation_loss, "val_mean_iou": validation_iou, "val_dice": validation_dice})
        if validation_iou > best_iou:
            best_iou, best_epoch = validation_iou, epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training did not produce a model checkpoint")
    model.load_state_dict(best_state)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = artifact_dir / "model.pt"
    torch.save({"state_dict": best_state, "image_size": size, "base_channels": base_channels, "threshold": threshold, "config": config}, checkpoint_path)
    artifact_paths = [str(checkpoint_path)]

    test_directory = data.get("test_images_dir")
    if test_directory:
        test_images = _index_images(Path(str(test_directory)).expanduser().resolve())
        submission_directory = artifact_dir / "submission_png"
        submission_directory.mkdir(exist_ok=True)
        model.eval()
        with torch.no_grad():
            for stem, image_path in test_images.items():
                image, original_size = _image_tensor(image_path, size)
                probability = model(image.unsqueeze(0).to(device)).sigmoid().squeeze().cpu().ge(threshold).to(torch.uint8).mul(255)
                output = Image.frombytes("L", (size[1], size[0]), probability.contiguous().numpy().tobytes())
                output.resize((original_size[1], original_size[0]), Image.Resampling.NEAREST).save(submission_directory / f"{stem}.png")
        artifact_paths.append(str(submission_directory))

    peak_memory = round(torch.cuda.max_memory_allocated(device) / 1024**3, 4) if device.type == "cuda" else None
    best = history[best_epoch - 1]
    return {"history": history, "best_epoch": best_epoch, "validation_metric": best_iou, "metrics": {"val_mean_iou": best_iou, "val_loss_at_best_mean_iou": best["val_loss"], "val_dice_at_best_mean_iou": best["val_dice"]}, "peak_gpu_memory_gb": peak_memory, "artifact_paths": artifact_paths}
