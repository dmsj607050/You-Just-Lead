"""Entry point for the packaged Windows desktop Agent sidecar."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.api_server import serve


WORKSPACE_DIRECTORIES = (
    "configs",
    "reports",
    "experiments/manifests",
    "experiments/results",
    "experiments/artifacts",
    "experiments/tracking",
    "experiments/drafts",
    "experiments/approvals",
    "submissions/validation",
    "models",
    "input",
    "data/raw",
    "data/interim",
    "data/processed",
    "docs",
    "research",
    "reproductions",
)


def _data_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "YouJustLead"


def _workspace() -> tuple[Path, Path]:
    data_root = _data_root()
    workspace = data_root / "workspace" / "current_competition"
    for relative_path in WORKSPACE_DIRECTORIES:
        (workspace / relative_path).mkdir(parents=True, exist_ok=True)
    (data_root / "database").mkdir(parents=True, exist_ok=True)
    specification = workspace / "competition_spec.yaml"
    if not specification.exists():
        specification.write_text(
            "# Fill this after creating or importing a competition project.\n"
            "competition:\n"
            "  name: New competition\n"
            "  task_type: pending\n"
            "evaluation:\n"
            "  primary_metric: pending\n"
            "  direction: maximize\n"
            "approval:\n"
            "  requires_human_confirmation: true\n",
            encoding="utf-8",
        )
    return data_root, workspace


def main() -> None:
    parser = argparse.ArgumentParser(description="You Just Lead desktop Agent sidecar")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    project_root, workspace = _workspace()
    serve(args.host, args.port, workspace, project_root=project_root)


if __name__ == "__main__":
    main()
