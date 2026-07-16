"""Deterministic, dependency-light data profiling for a competition workspace."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tools.files import write_json_atomic
from tools.provenance import utc_now


IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
CSV_SUFFIXES = {".csv", ".tsv"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_name(path: Path) -> str:
    names = {part.lower() for part in path.parts}
    if names & {"train", "training", "labels", "masks"}:
        return "train"
    if names & {"valid", "validation", "val"}:
        return "validation"
    if names & {"test", "testing"}:
        return "test"
    return "unassigned"


def _png_size(path: Path) -> tuple[int, int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(32)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height, bit_depth, color_type = struct.unpack(">IIBB", header[16:26])
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 0)
    return width, height, channels


def _image_metadata(path: Path) -> dict[str, int]:
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(path) as image:
            width, height = image.size
            channels = len(image.getbands())
        return {"width": width, "height": height, "channels": channels}
    except ImportError:
        if path.suffix.lower() == ".png":
            parsed = _png_size(path)
            if parsed:
                return {"width": parsed[0], "height": parsed[1], "channels": parsed[2]}
        raise ValueError("Image metadata requires Pillow for this format.")
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _is_mask_path(path: Path) -> bool:
    """Recognise common segmentation-mask directory names."""
    return any(
        part.lower() in {"mask", "masks", "label", "labels", "annotation", "annotations"}
        for part in path.parts
    )


def _foreground_ratio(path: Path) -> float:
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(path) as image:
            histogram = image.convert("L").histogram()
        pixels = sum(histogram)
        return 0.0 if pixels == 0 else round((pixels - histogram[0]) / pixels, 8)
    except ImportError as exc:
        raise ValueError("Mask statistics require Pillow.") from exc
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _csv_metadata(path: Path) -> dict[str, Any]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = reader.fieldnames or []
        rows = 0
        missing = Counter()
        for row in reader:
            rows += 1
            for field in fields:
                if not (row.get(field) or "").strip():
                    missing[field] += 1
    return {"rows": rows, "columns": fields, "missing_values": dict(missing)}


def _write_metadata_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _write_svg(path: Path, type_counts: Counter[str], split_counts: Counter[str]) -> None:
    labels = list(type_counts) or ["no files"]
    maximum = max(type_counts.values(), default=1)
    bars = []
    for index, label in enumerate(labels):
        count = type_counts.get(label, 0)
        height = max(4, round(138 * count / maximum))
        x = 52 + index * 86
        bars.append(f'<rect x="{x}" y="{166 - height}" width="42" height="{height}" rx="5" fill="#e67c61"/>')
        bars.append(f'<text x="{x + 21}" y="184" text-anchor="middle" font-size="10" fill="#657080">{label}</text>')
        bars.append(f'<text x="{x + 21}" y="{157 - height}" text-anchor="middle" font-size="10" fill="#273140">{count}</text>')
    subtitle = " · ".join(f"{name}: {count}" for name, count in sorted(split_counts.items())) or "No splits detected"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"520\" height=\"220\" viewBox=\"0 0 520 220\">
<rect width=\"520\" height=\"220\" rx=\"16\" fill=\"#fffdf9\"/><text x=\"28\" y=\"34\" font-family=\"Arial\" font-size=\"17\" fill=\"#172231\">Dataset file inventory</text>
<text x=\"28\" y=\"54\" font-family=\"Arial\" font-size=\"11\" fill=\"#7e8894\">"""
        + subtitle.replace("&", "&amp;")
        + "</text><line x1=\"30\" y1=\"167\" x2=\"490\" y2=\"167\" stroke=\"#e8e1d7\"/>"
        + "".join(bars)
        + "</svg>\n",
        encoding="utf-8",
    )


def audit_dataset(workspace: Path, data_dir: Path | None = None) -> dict[str, Any]:
    """Profile data without changing the raw source directory."""
    root = (data_dir or workspace / "data" / "raw").resolve()
    if not root.exists():
        raise FileNotFoundError(f"Data directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Data path is not a directory: {root}")

    records: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    type_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    image_sizes: list[tuple[int, int]] = []
    image_channels: Counter[int] = Counter()
    mask_ratios: list[float] = []
    csv_files: list[dict[str, Any]] = []

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        record: dict[str, Any] = {
            "path": relative,
            "suffix": suffix or "[none]",
            "bytes": path.stat().st_size,
            "split": _split_name(path.relative_to(root)),
            "sha256": _sha256(path),
        }
        record["kind"] = "image" if suffix in IMAGE_SUFFIXES else "table" if suffix in CSV_SUFFIXES else "file"
        type_counts[record["kind"]] += 1
        split_counts[record["split"]] += 1
        hashes[record["sha256"]].append(relative)
        if record["bytes"] == 0:
            issues.append({"severity": "error", "path": relative, "issue": "Empty file"})

        if suffix in IMAGE_SUFFIXES:
            try:
                metadata = _image_metadata(path)
                record["image"] = metadata
                image_sizes.append((metadata["width"], metadata["height"]))
                image_channels[metadata["channels"]] += 1
                if _is_mask_path(path.relative_to(root)):
                    foreground_ratio = _foreground_ratio(path)
                    record["mask"] = {"foreground_ratio": foreground_ratio}
                    mask_ratios.append(foreground_ratio)
                    if foreground_ratio == 0:
                        issues.append(
                            {
                                "severity": "warning",
                                "path": relative,
                                "issue": "Empty segmentation mask",
                            }
                        )
            except ValueError as exc:
                record["image_error"] = str(exc)
                issues.append({"severity": "error", "path": relative, "issue": f"Unreadable image: {exc}"})
        elif suffix in CSV_SUFFIXES:
            try:
                table = _csv_metadata(path)
                record["table"] = table
                csv_files.append({"path": relative, **table})
                for field, missing in table["missing_values"].items():
                    if missing:
                        issues.append({"severity": "warning", "path": relative, "issue": f"{missing} missing values in column '{field}'"})
            except (OSError, csv.Error) as exc:
                issues.append({"severity": "error", "path": relative, "issue": f"Unreadable table: {exc}"})
        records.append(record)

    duplicate_groups = [paths for paths in hashes.values() if len(paths) > 1]
    for group in duplicate_groups:
        issues.append({"severity": "warning", "path": "; ".join(group), "issue": "Exact duplicate content"})
        group_splits = {_split_name(Path(item)) for item in group}
        if len(group_splits - {"unassigned"}) > 1:
            issues.append(
                {
                    "severity": "error",
                    "path": "; ".join(group),
                    "issue": "Potential leakage: identical content appears in multiple dataset splits",
                }
            )

    widths = [size[0] for size in image_sizes]
    heights = [size[1] for size in image_sizes]
    statistics_payload: dict[str, Any] = {
        "generated_at": utc_now(),
        "data_dir": str(root),
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "file_kinds": dict(sorted(type_counts.items())),
        "splits": dict(sorted(split_counts.items())),
        "exact_duplicate_groups": duplicate_groups,
        "issue_count": len(issues),
        "images": {
            "count": len(image_sizes),
            "width": {"min": min(widths), "max": max(widths), "mean": round(statistics.fmean(widths), 3)} if widths else None,
            "height": {"min": min(heights), "max": max(heights), "mean": round(statistics.fmean(heights), 3)} if heights else None,
            "channels": dict(sorted(image_channels.items())),
        },
        "segmentation_masks": {
            "count": len(mask_ratios),
            "empty_count": sum(ratio == 0 for ratio in mask_ratios),
            "foreground_ratio": {
                "min": min(mask_ratios),
                "max": max(mask_ratios),
                "mean": round(statistics.fmean(mask_ratios), 8),
            }
            if mask_ratios
            else None,
        },
        "tables": csv_files,
        "metadata_format": "jsonl",
    }
    reports = workspace / "reports"
    write_json_atomic(reports / "data_statistics.json", statistics_payload)
    _write_metadata_jsonl(workspace / "data" / "metadata.jsonl", records)
    with (reports / "data_quality_issues.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["severity", "path", "issue"])
        writer.writeheader()
        writer.writerows(issues)
    _write_svg(reports / "figures" / "data_overview.svg", type_counts, split_counts)

    profile = [
        "# Data profile",
        "",
        f"- Source: `{root}`",
        f"- Files: **{len(records)}**",
        f"- Total bytes: **{statistics_payload['total_bytes']}**",
        f"- Quality issues: **{len(issues)}**",
        f"- Exact duplicate groups: **{len(duplicate_groups)}**",
        "",
        "## Inventory",
        "",
    ]
    profile.extend(f"- {kind}: {count}" for kind, count in sorted(type_counts.items())) or profile.append("- No files found")
    profile.extend(["", "## Split hints", ""])
    profile.extend(f"- {split_name}: {count}" for split_name, count in sorted(split_counts.items())) or profile.append("- No train/test folder names detected")
    if image_sizes:
        profile.extend(["", "## Images", "", f"- Width range: {min(widths)}–{max(widths)}", f"- Height range: {min(heights)}–{max(heights)}", f"- Channel distribution: {dict(sorted(image_channels.items()))}"])
    profile.extend(["", "## Derived artefacts", "", "- `reports/data_statistics.json` — machine-readable summary", "- `reports/data_quality_issues.csv` — review queue", "- `data/metadata.jsonl` — one record per file", "- `reports/figures/data_overview.svg` — inventory visual"])
    (reports / "data_profile.md").write_text("\n".join(profile) + "\n", encoding="utf-8")
    return statistics_payload
