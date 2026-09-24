"""Structured records for all experiment intentions and outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.provenance import utc_now


@dataclass
class ExperimentManifest:
    experiment_id: str
    hypothesis: str
    config_path: str
    config_sha256: str
    parent_id: str | None
    change_type: str
    data_version: str
    seed: int | None
    command: str
    git: dict[str, Any]
    environment: dict[str, Any]
    config: dict[str, Any]
    expected_improvement: str | None = None
    estimated_gpu_hours: float | None = None
    rollback_plan: str | None = None
    created_at: str = field(default_factory=utc_now)
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentResult:
    experiment_id: str
    status: str
    started_at: str
    finished_at: str
    best_epoch: int | None
    validation_metric: float | None
    metrics: dict[str, float]
    runtime_seconds: float
    peak_gpu_memory_gb: float | None
    diagnosis: dict[str, Any]
    conclusion: str
    decision: str
    next_candidates: list[str]
    artifact_paths: list[str]
    tracker_backend: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
