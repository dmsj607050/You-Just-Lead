"""Code, data, and environment provenance capture."""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(project_root: Path, *args: str) -> tuple[bool, str]:
    try:
        process = subprocess.run(
            ["git", "-C", str(project_root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return process.returncode == 0, process.stdout.strip()


def git_provenance(project_root: Path) -> dict[str, Any]:
    """Return commit and dirty-state information without requiring a repository."""
    available, repository_root = _git(project_root, "rev-parse", "--show-toplevel")
    if not available:
        return {
            "available": False,
            "repository_root": None,
            "commit": None,
            "branch": None,
            "dirty": None,
        }

    _, commit = _git(project_root, "rev-parse", "HEAD")
    _, branch = _git(project_root, "rev-parse", "--abbrev-ref", "HEAD")
    _, status = _git(project_root, "status", "--porcelain")
    return {
        "available": True,
        "repository_root": repository_root,
        "commit": commit or None,
        "branch": branch or None,
        "dirty": bool(status),
    }


def environment_snapshot() -> dict[str, Any]:
    """Capture execution environment details needed to interpret a result."""
    snapshot: dict[str, Any] = {
        "captured_at": utc_now(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    try:
        import torch

        snapshot["torch"] = torch.__version__
        snapshot["cuda_available"] = torch.cuda.is_available()
        snapshot["cuda_version"] = torch.version.cuda
        if torch.cuda.is_available():
            snapshot["gpu"] = torch.cuda.get_device_name(0)
    except ImportError:
        snapshot["torch"] = None
        snapshot["cuda_available"] = False
    return snapshot
