"""Structured proposals for state-changing work.

An ``ActionRequest`` is a proposal, never a permission.  Nothing in this system
may act on one until the authorization gateway returns an explicit allow for
exactly this content, so the agent that produced it never holds authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.provenance import utc_now


READ_ONLY = "read_only"
LOW = "low"
COSTLY = "costly"
EXTERNAL = "external"
DESTRUCTIVE = "destructive"

RISK_LEVELS = (READ_ONLY, LOW, COSTLY, EXTERNAL, DESTRUCTIVE)

TRAINING_RUN = "training.run"


@dataclass
class ActionRequest:
    action_id: str
    kind: str
    skill: str
    parameters: dict[str, Any]
    content_sha256: str
    risk: str
    rationale: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    requested_by: str = "human:cli"
    parent_experiment_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
