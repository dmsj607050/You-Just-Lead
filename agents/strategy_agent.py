"""Rule-aware next-action selection based only on persisted local evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.configuration import load_yaml
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


def _results(workspace: Path) -> list[dict[str, Any]]:
    return sorted(
        (read_json(path) for path in (workspace / "experiments" / "results").glob("EXP-*.json")),
        key=lambda item: item["experiment_id"],
    )


def _bounded(value: Any, default: float) -> float:
    try:
        return max(0.05, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _priority_score(
    expected_gain: float,
    evidence_confidence: float,
    compatibility: float,
    compute_cost: float,
    implementation_risk: float,
) -> float:
    """Rank proposals without treating the score as a predicted leaderboard gain."""
    return round(
        (expected_gain * evidence_confidence * compatibility)
        / max(0.1, compute_cost + implementation_risk),
        4,
    )


def _proposal(
    *,
    proposal_id: str,
    parent_experiment_id: str,
    change_type: str,
    hypothesis: str,
    evidence: list[dict[str, str]],
    expected_gain_score: float,
    evidence_confidence: float,
    compatibility: float,
    compute_cost: float,
    implementation_risk: float,
    requires_human_approval: bool,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "parent_experiment_id": parent_experiment_id,
        "change_type": change_type,
        "hypothesis": hypothesis,
        "evidence": evidence,
        "expected_gain": "Not estimated; validate against the frozen parent baseline.",
        "score_inputs": {
            "expected_gain_score": expected_gain_score,
            "evidence_confidence": evidence_confidence,
            "compatibility": compatibility,
            "compute_cost": compute_cost,
            "implementation_risk": implementation_risk,
        },
        "priority_score": _priority_score(
            expected_gain_score,
            evidence_confidence,
            compatibility,
            compute_cost,
            implementation_risk,
        ),
        "requires_human_approval": requires_human_approval,
        "rollback": parent_experiment_id,
    }


def rank_experiment_proposals(workspace: Path) -> list[dict[str, Any]]:
    """Rank up to three review-only experiment candidates from persisted evidence.

    The inputs are deliberately conservative: curve symptoms, past result
    records and explicitly searched research records.  It never invents a
    claimed score improvement or turns a proposal into a scheduled run.
    """
    completed = [item for item in _results(workspace) if item.get("status") == "completed"]
    if not completed:
        return []
    parent = completed[-1]
    parent_id = str(parent["experiment_id"])
    diagnosis = parent.get("diagnosis") if isinstance(parent.get("diagnosis"), dict) else {}
    proposals: list[dict[str, Any]] = []

    if diagnosis.get("overfitting_detected"):
        proposals.append(
            _proposal(
                proposal_id="PROPOSAL-01",
                parent_experiment_id=parent_id,
                change_type="regularization",
                hypothesis="Increase regularization or augmentation while preserving the parent architecture.",
                evidence=[
                    {
                        "source": parent_id,
                        "detail": "Curve diagnosis detected both a train/validation gap and post-best degradation.",
                    }
                ],
                expected_gain_score=0.58,
                evidence_confidence=0.86,
                compatibility=0.92,
                compute_cost=0.25,
                implementation_risk=0.16,
                requires_human_approval=True,
            )
        )
    if diagnosis.get("instability_detected"):
        proposals.append(
            _proposal(
                proposal_id=f"PROPOSAL-{len(proposals) + 1:02d}",
                parent_experiment_id=parent_id,
                change_type="optimizer",
                hypothesis="Reduce the learning rate or add a scheduler in a one-variable stability ablation.",
                evidence=[
                    {
                        "source": parent_id,
                        "detail": "Recent validation measurements exceeded the configured instability threshold.",
                    }
                ],
                expected_gain_score=0.49,
                evidence_confidence=0.82,
                compatibility=0.9,
                compute_cost=0.22,
                implementation_risk=0.12,
                requires_human_approval=True,
            )
        )

    proposals.append(
        _proposal(
            proposal_id=f"PROPOSAL-{len(proposals) + 1:02d}",
            parent_experiment_id=parent_id,
            change_type="controlled_ablation",
            hypothesis="Repeat the parent configuration with exactly one documented low-cost parameter change.",
            evidence=[
                {
                    "source": parent_id,
                    "detail": "The latest completed run is the only valid comparison point for a controlled change.",
                }
            ],
            expected_gain_score=0.35,
            evidence_confidence=0.7,
            compatibility=0.95,
            compute_cost=0.18,
            implementation_risk=0.08,
            requires_human_approval=True,
        )
    )

    research_path = workspace / "research" / "papers.json"
    if research_path.exists() and len(proposals) < 3:
        research = read_json(research_path)
        records = research.get("records") if isinstance(research.get("records"), list) else []
        for record in records:
            if not isinstance(record, dict) or not record.get("title"):
                continue
            priority = _bounded(record.get("reproduction_priority"), 0.35)
            proposals.append(
                _proposal(
                    proposal_id=f"PROPOSAL-{len(proposals) + 1:02d}",
                    parent_experiment_id=parent_id,
                    change_type="research_transfer",
                    hypothesis=f"Assess one compatible component from '{record['title']}' before considering full reproduction.",
                    evidence=[
                        {
                            "source": str(record.get("paper_id") or record.get("url") or "research record"),
                            "detail": "Explicitly persisted research record; no performance claim is transferred automatically.",
                        }
                    ],
                    expected_gain_score=0.42,
                    evidence_confidence=priority,
                    compatibility=_bounded(record.get("relevance_score"), 0.5),
                    compute_cost=0.55 if record.get("code_url") else 0.4,
                    implementation_risk=0.62 if record.get("code_url") else 0.45,
                    requires_human_approval=True,
                )
            )
            break

    ranked = sorted(proposals[:3], key=lambda item: (-float(item["priority_score"]), item["proposal_id"]))
    for rank, proposal in enumerate(ranked, 1):
        proposal["rank"] = rank
    return ranked


def recommend_next_actions(workspace: Path, *, persist: bool = True) -> dict[str, Any]:
    """Produce a bounded, human-reviewable action queue rather than auto-running work."""
    actions: list[dict[str, str]] = []
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        actions.append({"priority": "blocker", "action": "Create and review competition_spec.yaml before any real-data training.", "evidence": "No specification found."})
    else:
        spec = load_yaml(spec_path)
        approval = spec.get("approval", {})
        if approval.get("requires_human_confirmation", True):
            questions = approval.get("unresolved_questions", [])
            actions.append({"priority": "blocker", "action": "Resolve official-rule questions and explicitly approve the specification.", "evidence": "; ".join(questions) or "Specification is not approved."})

    if not (workspace / "reports" / "data_statistics.json").exists():
        actions.append({"priority": "high", "action": "Run the deterministic data audit before creating a real baseline.", "evidence": "No data_statistics.json exists."})
    if not (workspace / "research" / "papers.json").exists():
        actions.append({"priority": "medium", "action": "Search research sources using the task and metric from the approved specification.", "evidence": "No persisted research radar exists."})

    results = _results(workspace)
    completed = [item for item in results if item.get("status") == "completed"]
    if not completed:
        actions.append({"priority": "high", "action": "After rules and audit are approved, run one reproducible baseline with a frozen configuration.", "evidence": "No completed experiments recorded."})
    else:
        latest = completed[-1]
        diagnosis = latest.get("diagnosis", {})
        for recommendation in diagnosis.get("recommendations", [])[:2]:
            actions.append({"priority": "medium", "action": str(recommendation), "evidence": f"{latest['experiment_id']} curve diagnosis."})
        actions.append({"priority": "low", "action": "Review ranked candidate experiments and approve at most one controlled change.", "evidence": f"Latest completed run: {latest['experiment_id']}."})

    proposals = rank_experiment_proposals(workspace)
    payload = {
        "generated_at": utc_now(),
        "actions": actions[:6],
        "proposals": proposals,
        "completed_experiments": len(completed),
    }
    if persist:
        write_json_atomic(workspace / "experiments" / "next_actions.json", payload)
        write_json_atomic(
            workspace / "experiments" / "proposals.json",
            {"generated_at": payload["generated_at"], "proposals": proposals},
        )
        report = ["# Decision memo", "", "This queue is evidence-led and does not execute actions automatically.", ""]
        for index, action in enumerate(payload["actions"], 1):
            report.extend([f"## {index}. {action['priority'].upper()}", action["action"], "", f"Evidence: {action['evidence']}", ""])
        report.extend(["## Ranked experiment proposals", ""])
        if proposals:
            for proposal in proposals:
                report.extend(
                    [
                        f"### {proposal['rank']}. {proposal['proposal_id']} — score {proposal['priority_score']:.4f}",
                        proposal["hypothesis"],
                        "",
                        f"- Parent / rollback: `{proposal['parent_experiment_id']}`",
                        f"- Change type: `{proposal['change_type']}`",
                        f"- Human approval required: `{proposal['requires_human_approval']}`",
                        f"- Evidence: {proposal['evidence'][0]['source']} — {proposal['evidence'][0]['detail']}",
                        "",
                    ]
                )
        else:
            report.extend(["No proposal exists until a completed baseline provides a valid parent.", ""])
        (workspace / "reports" / "decision_memo.md").write_text("\n".join(report), encoding="utf-8")
    return payload
