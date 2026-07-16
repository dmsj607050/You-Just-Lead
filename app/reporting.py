"""Generate human-readable reports from structured experiment records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.files import read_json


def _records(directory: Path) -> list[dict[str, Any]]:
    records = [read_json(path) for path in directory.glob("EXP-*.json")]
    return sorted(records, key=lambda item: item["experiment_id"])


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate_reports(workspace: Path, direction: str = "maximize") -> dict[str, str | None]:
    """Regenerate summaries without treating Markdown as source of truth."""
    experiments = workspace / "experiments"
    manifests = {
        record["experiment_id"]: record
        for record in _records(experiments / "manifests")
    }
    results = _records(experiments / "results")
    completed = [
        result
        for result in results
        if result["status"] == "completed" and result["validation_metric"] is not None
    ]
    best: dict[str, Any] | None = None
    if completed:
        multiplier = 1.0 if direction == "maximize" else -1.0
        best = max(
            completed,
            key=lambda item: (
                multiplier * float(item["validation_metric"]),
                item.get("finished_at", ""),
            ),
        )

    log_lines = [
        "# Experiment log",
        "",
        "| ID | Status | Validation metric | Best epoch | Runtime (s) | Decision |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        metric = (
            f"{float(result['validation_metric']):.6f}"
            if result["validation_metric"] is not None
            else "—"
        )
        log_lines.append(
            "| {id} | {status} | {metric} | {epoch} | {runtime:.3f} | {decision} |".format(
                id=_escape(result["experiment_id"]),
                status=_escape(result["status"]),
                metric=metric,
                epoch=result["best_epoch"] if result["best_epoch"] is not None else "—",
                runtime=float(result["runtime_seconds"]),
                decision=_escape(result["decision"]),
            )
        )
    if not results:
        log_lines.append("| — | No experiments recorded | — | — | — | — |")
    _write(experiments / "EXPERIMENT_LOG.md", "\n".join(log_lines) + "\n")

    if best is None:
        best_report = "# Best run\n\nNo validated run yet.\n"
    else:
        manifest = manifests.get(best["experiment_id"], {})
        best_report = "\n".join(
            [
                "# Best run",
                "",
                f"- Experiment: {best['experiment_id']}",
                f"- Validation metric: {float(best['validation_metric']):.6f}",
                f"- Best epoch: {best['best_epoch']}",
                f"- Hypothesis: {manifest.get('hypothesis', 'Unknown')}",
                f"- Config: {manifest.get('config_path', 'Unknown')}",
                f"- Git commit: {manifest.get('git', {}).get('commit') or 'unavailable'}",
            ]
        ) + "\n"
    _write(experiments / "BEST_RUN.md", best_report)

    failed = [
        result
        for result in results
        if result["status"] == "failed" or result["decision"] == "reject"
    ]
    failed_lines = ["# Failed ideas", ""]
    if failed:
        for result in failed:
            failed_lines.extend(
                [
                    f"## {result['experiment_id']}",
                    f"- Conclusion: {result['conclusion']}",
                    f"- Error: {result.get('error') or 'None'}",
                    "",
                ]
            )
    else:
        failed_lines.append("No rejected experiments yet.")
    _write(experiments / "FAILED_IDEAS.md", "\n".join(failed_lines) + "\n")

    candidates: list[str] = []
    for result in reversed(results):
        for candidate in result.get("next_candidates", []):
            if candidate not in candidates:
                candidates.append(candidate)
            if len(candidates) == 3:
                break
        if len(candidates) == 3:
            break
    action_lines = ["# Next actions", ""]
    if candidates:
        action_lines.extend(
            f"{index}. {candidate}" for index, candidate in enumerate(candidates, 1)
        )
    else:
        action_lines.extend(
            [
                "1. Read and record official competition rules.",
                "2. Run the deterministic data audit.",
                "3. Establish a reproducible baseline before optimization.",
            ]
        )
    _write(experiments / "NEXT_ACTIONS.md", "\n".join(action_lines) + "\n")

    summary_lines = [
        "# Training summary",
        "",
        f"- Completed runs: {len(completed)}",
        f"- Failed runs: {len(failed)}",
        f"- Selection direction: {direction}",
    ]
    if best:
        summary_lines.append(
            f"- Best result: {best['experiment_id']} ({float(best['validation_metric']):.6f})"
        )
    _write(workspace / "reports" / "training_summary.md", "\n".join(summary_lines) + "\n")
    return {"best_experiment_id": best["experiment_id"] if best else None}
