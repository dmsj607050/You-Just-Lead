"""Local submission validation against the reviewed competition specification."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from pathlib import PurePosixPath
import tarfile
from typing import Any
import zipfile

from tools.configuration import load_yaml
from tools.files import write_json_atomic
from tools.provenance import file_sha256, utc_now
from agents.rules_agent import rule_confirmation_readiness


def _csv_checks(path: Path, spec: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    required = spec.get("required_columns") or []
    if not isinstance(required, list):
        required = []
    for column in required:
        if column not in fields:
            checks.append({"severity": "error", "message": f"Missing required column: {column}"})
    if not fields:
        checks.append({"severity": "error", "message": "CSV has no header"})
    if not rows:
        checks.append({"severity": "error", "message": "CSV has no prediction rows"})
    expected_rows = spec.get("expected_rows")
    if expected_rows is not None:
        try:
            if len(rows) != int(expected_rows):
                checks.append({"severity": "error", "message": f"Expected {expected_rows} rows, found {len(rows)}"})
        except (TypeError, ValueError):
            checks.append({"severity": "warning", "message": "expected_rows is not a valid integer in the specification"})
    id_column = spec.get("id_column")
    if id_column and id_column in fields:
        values = [row.get(str(id_column), "") for row in rows]
        if len(values) != len(set(values)):
            checks.append({"severity": "error", "message": f"Duplicate values found in id column '{id_column}'"})
    return checks


def _png_directory_checks(path: Path, spec: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    masks = sorted(path.glob("*.png")) if path.is_dir() else []
    if not masks:
        checks.append({"severity": "error", "message": "No PNG masks found"})
    filename_rule = str(spec.get("filename_rule") or "")
    if filename_rule and filename_rule != "{image_id}.png":
        checks.append({"severity": "warning", "message": f"Filename rule '{filename_rule}' requires task-specific validation"})
    expected_rows = spec.get("expected_rows")
    if expected_rows is not None:
        try:
            if len(masks) != int(expected_rows):
                checks.append({"severity": "error", "message": f"Expected {expected_rows} masks, found {len(masks)}"})
        except (TypeError, ValueError):
            checks.append({"severity": "warning", "message": "expected_rows is not a valid integer in the specification"})
    return checks


def _png_payload_checks(name: str, payload: bytes, *, expected_size: tuple[int, int], suffix: str) -> list[dict[str, str]]:
    """Check a water-segmentation mask without writing archive contents to disk."""
    checks: list[dict[str, str]] = []
    if suffix and not name.endswith(f"{suffix}.png"):
        checks.append({"severity": "error", "message": f"Mask filename does not end in {suffix}.png: {name}"})
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "PNG":
                checks.append({"severity": "error", "message": f"Mask is not a PNG: {name}"})
            if image.mode != "L":
                checks.append({"severity": "error", "message": f"Mask must be single-channel grayscale (L): {name}"})
            if image.size != expected_size:
                checks.append({"severity": "error", "message": f"Mask size must be {expected_size[0]}x{expected_size[1]}: {name}"})
            if image.mode == "L":
                values = [value for value, count in enumerate(image.histogram()) if count]
                if any(value not in {0, 255} for value in values):
                    checks.append({"severity": "error", "message": f"Mask pixels must be only 0 or 255: {name}"})
    except ImportError:
        checks.append({"severity": "error", "message": "Pillow is required to validate water-segmentation masks"})
    except Exception as exc:
        checks.append({"severity": "error", "message": f"Unreadable PNG mask {name}: {exc}"})
    return checks


def _safe_tar_members(archive: tarfile.TarFile) -> tuple[list[tarfile.TarInfo], list[dict[str, str]]]:
    checks: list[dict[str, str]] = []
    members: list[tarfile.TarInfo] = []
    for member in archive.getmembers():
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            checks.append({"severity": "error", "message": f"Unsafe archive member path: {member.name}"})
            continue
        if member.issym() or member.islnk():
            checks.append({"severity": "error", "message": f"Archive symlink is not permitted: {member.name}"})
            continue
        if member.isfile():
            members.append(member)
    return members, checks


def _xunfei_waterseg_package_checks(path: Path, spec: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if not path.is_file() or not path.name.lower().endswith(".tar.gz"):
        return [{"severity": "error", "message": "Expected a .tar.gz inference package"}]
    submission = spec.get("submission", {})
    contract = submission.get("contract", {}) if isinstance(submission, dict) else {}
    if not isinstance(contract, dict):
        contract = {}
    output_mode = str(contract.get("runtime_output", "unresolved")).lower()
    if output_mode == "unresolved":
        checks.append({"severity": "error", "message": "Official runtime-output contract is unresolved; package cannot be approved"})
    expected_size = contract.get("mask_size", [1024, 1024])
    try:
        expected_size_tuple = (int(expected_size[0]), int(expected_size[1]))
    except (IndexError, TypeError, ValueError):
        checks.append({"severity": "error", "message": "submission.contract.mask_size must be [width, height]"})
        expected_size_tuple = (1024, 1024)
    suffix = str(contract.get("mask_filename_suffix", "_mask"))
    required_paths = {"run.py", "model/model.ts", "model/config.json"}
    try:
        with tarfile.open(path, "r:gz") as archive:
            members, archive_checks = _safe_tar_members(archive)
            checks.extend(archive_checks)
            roots = {PurePosixPath(member.name).parts[0] for member in members if PurePosixPath(member.name).parts}
            if len(roots) != 1:
                checks.append({"severity": "error", "message": "Package must contain exactly one top-level directory"})
                return checks
            root = next(iter(roots))
            indexed = {
                PurePosixPath(member.name).relative_to(root).as_posix(): member
                for member in members
                if len(PurePosixPath(member.name).parts) > 1
            }
            for required in sorted(required_paths):
                if required not in indexed:
                    checks.append({"severity": "error", "message": f"Missing package file: {root}/{required}"})
            model_member = indexed.get("model/model.ts")
            model_limit = spec.get("constraints", {}).get("model_size_limit_mb")
            if model_member is not None and model_limit is not None:
                try:
                    limit_bytes = int(float(model_limit) * 1024**2)
                    if model_member.size > limit_bytes:
                        checks.append({"severity": "error", "message": f"TorchScript model exceeds {model_limit} MB"})
                except (TypeError, ValueError):
                    checks.append({"severity": "warning", "message": "model_size_limit_mb is not a valid number"})
            config_member = indexed.get("model/config.json")
            if config_member is not None:
                extracted = archive.extractfile(config_member)
                try:
                    parsed = json.loads((extracted.read() if extracted else b"").decode("utf-8"))
                    threshold = float(parsed.get("threshold", 0.5))
                    if not 0 < threshold < 1:
                        checks.append({"severity": "error", "message": "model/config.json threshold must be between 0 and 1"})
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    checks.append({"severity": "error", "message": f"Invalid model/config.json: {exc}"})
    except (tarfile.TarError, OSError) as exc:
        checks.append({"severity": "error", "message": f"Unreadable tar.gz package: {exc}"})
    return checks


def _xunfei_waterseg_output_checks(path: Path, spec: dict[str, Any]) -> list[dict[str, str]]:
    """Validate an already-generated output directory or submit.zip for local smoke results."""
    submission = spec.get("submission", {})
    contract = submission.get("contract", {}) if isinstance(submission, dict) else {}
    if not isinstance(contract, dict):
        contract = {}
    expected_size = contract.get("mask_size", [1024, 1024])
    try:
        expected_size_tuple = (int(expected_size[0]), int(expected_size[1]))
    except (IndexError, TypeError, ValueError):
        expected_size_tuple = (1024, 1024)
    suffix = str(contract.get("mask_filename_suffix", "_mask"))
    payloads: list[tuple[str, bytes]] = []
    checks: list[dict[str, str]] = []
    if str(contract.get("runtime_output", "unresolved")).lower() == "unresolved":
        checks.append({"severity": "error", "message": "Official runtime-output contract is unresolved; masks cannot be approved"})
    if path.is_dir():
        payloads = [(item.name, item.read_bytes()) for item in sorted(path.glob("*.png"))]
    elif path.is_file() and path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    candidate = PurePosixPath(member.filename)
                    if candidate.is_absolute() or ".." in candidate.parts:
                        checks.append({"severity": "error", "message": f"Unsafe ZIP member path: {member.filename}"})
                    elif not member.is_dir() and candidate.suffix.lower() == ".png":
                        payloads.append((candidate.name, archive.read(member)))
        except (zipfile.BadZipFile, OSError) as exc:
            checks.append({"severity": "error", "message": f"Unreadable submit ZIP: {exc}"})
    else:
        checks.append({"severity": "error", "message": "Expected a PNG output directory or submit.zip"})
    if not payloads:
        checks.append({"severity": "error", "message": "No PNG prediction masks found"})
    for name, payload in payloads:
        checks.extend(_png_payload_checks(name, payload, expected_size=expected_size_tuple, suffix=suffix))
    return checks


def validate_submission(workspace: Path, candidate: Path) -> dict[str, Any]:
    """Validate a local candidate. Uploading to a competition platform is excluded."""
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        raise FileNotFoundError("competition_spec.yaml is required before submission validation")
    spec = load_yaml(spec_path)
    readiness = rule_confirmation_readiness(spec)
    if spec.get("approval", {}).get("requires_human_confirmation", True) or not readiness["ready"]:
        details = ", ".join(item["field"] for item in readiness["gaps"][:4])
        raise PermissionError(
            "Rules have not received complete human confirmation"
            + (f" (missing: {details})" if details else "")
        )
    candidate = candidate.resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"Submission candidate does not exist: {candidate}")
    submission = spec.get("submission", {})
    profile = str(submission.get("validation_profile") or "") if isinstance(submission, dict) else ""
    expected_format = str(submission.get("format") or "").lower()
    checks: list[dict[str, str]] = []
    if profile == "xunfei_waterseg_inference_package":
        if candidate.is_file() and candidate.name.lower().endswith(".tar.gz"):
            checks.extend(_xunfei_waterseg_package_checks(candidate, spec))
        else:
            checks.extend(_xunfei_waterseg_output_checks(candidate, spec))
    elif profile == "xunfei_waterseg_runtime_output":
        checks.extend(_xunfei_waterseg_output_checks(candidate, spec))
    elif expected_format in {"csv", "csv_file"}:
        if not candidate.is_file() or candidate.suffix.lower() != ".csv":
            checks.append({"severity": "error", "message": "Expected a CSV file"})
        else:
            checks.extend(_csv_checks(candidate, submission))
    elif expected_format in {"png_masks", "png_mask_directory"}:
        checks.extend(_png_directory_checks(candidate, submission))
    else:
        checks.append({"severity": "warning", "message": "No supported submission format is configured; only existence was checked"})
    errors = [check for check in checks if check["severity"] == "error"]
    digest = file_sha256(candidate) if candidate.is_file() else None
    outcome = {
        "candidate": str(candidate),
        "checked_at": utc_now(),
        "expected_format": expected_format or None,
        "status": "passed" if not errors else "failed",
        "checks": checks,
        "sha256": digest,
        "manual_upload_required": True,
    }
    output_dir = workspace / "submissions" / "validation"
    write_json_atomic(output_dir / f"{candidate.stem}.json", outcome)
    return outcome
