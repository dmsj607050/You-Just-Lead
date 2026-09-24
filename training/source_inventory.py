"""Fingerprint the source files that decide what an external project trains.

Both external adapters (water segmentation and object detection) hand a human
review a configuration, and that review is only meaningful if the code behind
it has not changed since.  So each adapter pins a digest of the project's
source and configuration files, and refuses to run when the digest moved.

The fingerprint is deliberately limited to source and configuration suffixes:
hashing data or checkpoints would make every review stale for the wrong
reason.  Both adapters share this loop so that "the source changed" means
exactly one thing across the product.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def fingerprint_source(
    project_dir: Path,
    *,
    suffixes: set[str],
    excluded_parts: set[str],
    label: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Return one digest plus the per-file records it was computed from."""
    root = project_dir.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{label} project directory does not exist: {root}")

    records: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if any(part.lower() in excluded_parts for part in relative.parts):
            continue
        if path.suffix.lower() not in suffixes:
            continue
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_digest,
        }
        records.append(record)
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    if not records:
        raise ValueError(f"No {label} source files found in {root}")
    return digest.hexdigest(), records
