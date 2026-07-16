"""Local submission validation against the reviewed competition specification."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from tools.configuration import load_yaml
from tools.files import write_json_atomic
from tools.provenance import file_sha256, utc_now


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


def validate_submission(workspace: Path, candidate: Path) -> dict[str, Any]:
    """Validate a local candidate. Uploading to a competition platform is excluded."""
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        raise FileNotFoundError("competition_spec.yaml is required before submission validation")
    spec = load_yaml(spec_path)
    if spec.get("approval", {}).get("requires_human_confirmation", True):
        raise PermissionError("Rules have not received human confirmation")
    candidate = candidate.resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"Submission candidate does not exist: {candidate}")
    submission = spec.get("submission", {})
    expected_format = str(submission.get("format") or "").lower()
    checks: list[dict[str, str]] = []
    if expected_format in {"csv", "csv_file"}:
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
