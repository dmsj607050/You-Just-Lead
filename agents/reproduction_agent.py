"""Safe repository intake for third-party competition baselines.

The module never executes downloaded code. Cloning is possible only with an
explicit approval flag, records the fixed commit, and produces a static review
report. Runtime reproduction remains a separate human-approved operation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from tools.files import write_json_atomic
from tools.provenance import utc_now


def _safe_repository_url(repository: str) -> bool:
    return bool(
        re.fullmatch(r"https://[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+\.git", repository)
        or re.fullmatch(r"git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", repository)
    )


def _slug(repository: str) -> str:
    stem = repository.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-") or "repository"


def _run(arguments: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(arguments, cwd=cwd, check=True, capture_output=True, text=True, timeout=120)
    return completed.stdout.strip()


def intake_repository(
    workspace: Path,
    repository: str,
    *,
    approved: bool = False,
    commit: str | None = None,
) -> dict[str, Any]:
    """Create a review request or clone a repository for static inspection."""
    if not _safe_repository_url(repository):
        raise ValueError("Only explicit HTTPS .git URLs or git@github.com URLs are accepted.")
    reproductions = workspace / "reproductions"
    record_path = reproductions / f"{_slug(repository)}.json"
    base: dict[str, Any] = {
        "repository": repository,
        "requested_commit": commit,
        "requested_at": utc_now(),
        "approved": approved,
        "execution_policy": "No downloaded code is executed by this intake workflow.",
    }
    if not approved:
        base.update({"status": "awaiting_human_approval", "next_step": "Review licence, source trust and resource budget; rerun with --approved to clone for static inspection."})
        write_json_atomic(record_path, base)
        return {"status": base["status"], "record_path": str(record_path)}

    target = reproductions / "sources" / _slug(repository)
    if target.exists():
        raise FileExistsError(f"Repository target already exists: {target}. Remove it manually only after review.")
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--no-checkout", repository, str(target)])
    resolved_commit = commit or _run(["git", "rev-parse", "HEAD"], target)
    _run(["git", "checkout", "--detach", resolved_commit], target)
    candidates = ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "NOTICE"]
    licence_file = next((name for name in candidates if (target / name).is_file()), None)
    static_signals = {
        "license_file": licence_file,
        "dockerfile": (target / "Dockerfile").is_file(),
        "requirements_files": [path.name for path in target.glob("requirements*.txt")],
        "environment_files": [path.name for path in target.glob("environment*.yml")] + [path.name for path in target.glob("environment*.yaml")],
        "readme": next((path.name for path in target.glob("README*")), None),
    }
    base.update(
        {
            "status": "static_inspection_complete",
            "commit": resolved_commit,
            "local_path": str(target),
            "static_signals": static_signals,
            "next_step": "Review the static report. Build or run code only in a separately approved isolated environment.",
        }
    )
    write_json_atomic(record_path, base)
    report = ["# Reproduction intake report", "", f"- Repository: `{repository}`", f"- Fixed commit: `{resolved_commit}`", f"- License file: {licence_file or 'not found'}", f"- Dockerfile: {static_signals['dockerfile']}", f"- Requirements: {', '.join(static_signals['requirements_files']) or 'not found'}", "", "## Safety gate", "", "Downloaded code has not been executed. A human must approve an isolated smoke test and full reproduction separately."]
    (reproductions / f"{_slug(repository)}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"status": base["status"], "record_path": str(record_path), "commit": resolved_commit}
