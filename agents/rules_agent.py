"""Turn a local competition rule document into reviewable structured artefacts.

This module deliberately treats extraction as a draft.  A competition rule can be
ambiguous, therefore every missing or weakly extracted field remains in the
``unresolved_questions`` list and keeps human confirmation enabled.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.configuration import load_yaml, write_yaml
from tools.files import write_json_atomic
from tools.provenance import file_sha256, utc_now


FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "competition.name": (
        r"^(?:competition(?:\s+name)?|比赛(?:名称)?)\s*[:：]\s*(.+)$",
        r"^#\s+(.+)$",
    ),
    "competition.platform": (r"^(?:platform|平台)\s*[:：]\s*(.+)$",),
    "competition.task_type": (r"^(?:task(?:\s+type)?|任务(?:类型)?)\s*[:：]\s*(.+)$",),
    "competition.deadline": (r"^(?:deadline|截止(?:日期|时间)?)\s*[:：]\s*(.+)$",),
    "evaluation.primary_metric": (r"^(?:primary\s+metric|metric|评价指标|评测指标)\s*[:：]\s*(.+)$",),
    "evaluation.direction": (r"^(?:metric\s+direction|direction|指标方向)\s*[:：]\s*(maximize|minimize|最大化|最小化)\s*$",),
    "submission.format": (r"^(?:submission\s+format|format|提交格式)\s*[:：]\s*(.+)$",),
    "submission.filename_rule": (r"^(?:filename(?:\s+rule)?|文件名(?:规则)?)\s*[:：]\s*(.+)$",),
    "submission.daily_limit": (r"^(?:daily\s+limit|submission\s+limit|每日提交(?:次数)?)\s*[:：]\s*(.+)$",),
    "constraints.inference_time_limit_seconds": (r"^(?:inference\s+time(?:\s+limit)?|推理时间(?:限制)?)\s*[:：]\s*(.+)$",),
    "constraints.model_size_limit_mb": (r"^(?:model\s+size(?:\s+limit)?|模型大小(?:限制)?)\s*[:：]\s*(.+)$",),
}

REQUIRED_FIELDS = (
    "competition.name",
    "competition.task_type",
    "evaluation.primary_metric",
    "submission.format",
)


# A rule extraction is only a draft.  Before a real-data run we require a
# reviewer to attach the exact source they used and the source anchors for the
# fields that materially change the training or submission plan.  This is
# deliberately stricter for the Xunfei water-segmentation adapter because its
# output contract and pretrained-weight policy are currently consequential.
BASE_CONFIRMATION_FIELDS = (
    "competition.name",
    "competition.platform",
    "competition.task_type",
    "competition.deadline",
    "evaluation.primary_metric",
    "evaluation.direction",
    "submission.format",
    "submission.filename_rule",
    "submission.daily_limit",
    "constraints.model_size_limit_mb",
)

XUNFEI_CONFIRMATION_FIELDS = (
    "submission.contract.package_layout",
    "submission.contract.required_files",
    "submission.contract.mask_size",
    "submission.contract.mask_filename_suffix",
    "submission.contract.runtime_output",
    "constraints.external_data_allowed",
    "constraints.pretrained_models_allowed",
    "constraints.ensemble_allowed",
    "constraints.inference_limit_evidence",
)


def _deep_get(payload: dict[str, Any], dotted_name: str) -> Any:
    value: Any = payload
    for key in dotted_name.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {"unresolved", "unknown", "tbd", "todo"}
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _is_xunfei_waterseg_spec(spec: dict[str, Any]) -> bool:
    submission = spec.get("submission", {})
    competition = spec.get("competition", {})
    return (
        isinstance(submission, dict)
        and submission.get("validation_profile") in {
            "xunfei_waterseg_inference_package",
            "xunfei_waterseg_runtime_output",
        }
    ) or str(competition.get("preferred_runner", "")) == "waterseg_external"


def rule_confirmation_readiness(spec: dict[str, Any]) -> dict[str, Any]:
    """Return explicit, machine-readable gaps before human rule approval.

    This does not decide whether a rule is true.  It makes the human review
    auditable and prevents an incomplete, manually edited YAML file from
    unlocking a costly training run.
    """
    approval = spec.get("approval", {}) if isinstance(spec.get("approval"), dict) else {}
    strict_xunfei_profile = _is_xunfei_waterseg_spec(spec)
    # Generic competitions have different rule schemas, so their existing
    # extractor remains the source of required fields.  The fixed contract
    # below applies only to the fully integrated Xunfei adapter, where a wrong
    # output bundle or pretrained-weight assumption would directly invalidate
    # a run.
    required_fields = list(BASE_CONFIRMATION_FIELDS) if strict_xunfei_profile else []
    if strict_xunfei_profile:
        required_fields.extend(XUNFEI_CONFIRMATION_FIELDS)

    gaps: list[dict[str, str]] = []
    for field in required_fields:
        value = _deep_get(spec, field)
        if not _meaningful(value):
            gaps.append({"field": field, "reason": "The confirmed value is missing or unresolved."})

    if strict_xunfei_profile:
        output_mode = str(_deep_get(spec, "submission.contract.runtime_output") or "").lower()
        if output_mode not in {"loose_png", "submit_zip"}:
            gaps.append(
                {
                    "field": "submission.contract.runtime_output",
                    "reason": "Use exactly loose_png or submit_zip after reading the official runtime contract.",
                }
            )

    if strict_xunfei_profile:
        evidence = approval.get("official_evidence") if isinstance(approval.get("official_evidence"), dict) else {}
        for field in ("source_type", "source_locator", "reviewed_at"):
            if not _meaningful(evidence.get(field)):
                gaps.append(
                    {
                        "field": f"approval.official_evidence.{field}",
                        "reason": "Record the official rule-page or document evidence used for review.",
                    }
                )
        field_evidence = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
        for field in required_fields:
            if not _meaningful(field_evidence.get(field)):
                gaps.append(
                    {
                        "field": f"approval.official_evidence.fields.{field}",
                        "reason": "Add an exact quote, section heading, page number, or screenshot anchor for this field.",
                    }
                )

    unresolved = approval.get("unresolved_questions", [])
    if not isinstance(unresolved, list):
        gaps.append({"field": "approval.unresolved_questions", "reason": "This must be a list and must be empty before approval."})
    elif unresolved:
        gaps.append({"field": "approval.unresolved_questions", "reason": f"Resolve all {len(unresolved)} listed rule question(s)."})

    return {
        "ready": not gaps,
        "profile": "xunfei_waterseg" if _is_xunfei_waterseg_spec(spec) else "generic",
        "required_fields": required_fields,
        "gaps": gaps,
    }


def rule_confirmation_readiness_for_workspace(workspace: Path) -> dict[str, Any]:
    """Load the current spec and return the approval readiness projection."""
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        return {
            "ready": False,
            "profile": "unknown",
            "required_fields": [],
            "gaps": [{"field": "competition_spec.yaml", "reason": "Create a reviewed competition specification first."}],
        }
    outcome = rule_confirmation_readiness(load_yaml(spec_path))
    outcome["spec_path"] = str(spec_path)
    return outcome


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _set_nested(payload: dict[str, Any], dotted_name: str, value: Any) -> None:
    parent, field = dotted_name.split(".")
    payload.setdefault(parent, {})[field] = value


def _get_nested(payload: dict[str, Any], dotted_name: str) -> Any:
    parent, field = dotted_name.split(".")
    value = payload.get(parent, {})
    return value.get(field) if isinstance(value, dict) else None


def _yes_no(value: str) -> bool | None:
    normalized = value.lower().strip()
    if normalized in {"yes", "true", "allowed", "allow", "允许", "可以", "是"}:
        return True
    if normalized in {"no", "false", "prohibited", "not allowed", "禁止", "不允许", "否"}:
        return False
    return None


def _constraint_flags(lines: list[str]) -> dict[str, dict[str, Any]]:
    labels = {
        "external_data_allowed": ("external data", "外部数据"),
        "pretrained_models_allowed": ("pretrained", "预训练"),
        "ensemble_allowed": ("ensemble", "集成"),
    }
    evidence: dict[str, dict[str, Any]] = {}
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        lowered = line.lower()
        for field, terms in labels.items():
            if not any(term in lowered or term in line for term in terms):
                continue
            value = _yes_no(line.split(":", 1)[-1].split("：", 1)[-1])
            if value is None:
                if any(token in lowered or token in line for token in ("not allowed", "prohibited", "forbidden", "禁止", "不允许")):
                    value = False
                elif any(token in lowered or token in line for token in ("allowed", "permit", "允许", "可以")):
                    value = True
            if value is not None:
                evidence[field] = {"value": value, "line": line_number, "text": line}
    return evidence


def analyze_rules(source_path: Path, workspace: Path) -> dict[str, Any]:
    """Create an auditable draft spec and reviewer-facing rule summaries."""
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Rule source does not exist: {source_path}")

    text = _read_text(source_path)
    lines = text.splitlines()
    spec_path = workspace / "competition_spec.yaml"
    spec = load_yaml(spec_path) if spec_path.exists() else {}
    evidence: dict[str, dict[str, Any]] = {}

    for dotted_name, patterns in FIELD_PATTERNS.items():
        for line_number, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            for pattern in patterns:
                match = re.match(pattern, line, flags=re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    if dotted_name == "evaluation.direction":
                        value = {"最大化": "maximize", "最小化": "minimize"}.get(value, value.lower())
                    _set_nested(spec, dotted_name, value)
                    evidence[dotted_name] = {"line": line_number, "text": line, "value": value}
                    break
            if dotted_name in evidence:
                break

    for field, extracted in _constraint_flags(lines).items():
        spec.setdefault("constraints", {})[field] = extracted["value"]
        evidence[f"constraints.{field}"] = extracted

    unresolved: list[str] = []
    for field in REQUIRED_FIELDS:
        if not _get_nested(spec, field):
            unresolved.append(f"Confirm {field} from the official rules.")
    for field in ("external_data_allowed", "pretrained_models_allowed", "ensemble_allowed"):
        if spec.get("constraints", {}).get(field) is None:
            unresolved.append(f"Confirm constraints.{field} from the official rules.")

    previous_approval = spec.get("approval", {}) if isinstance(spec.get("approval"), dict) else {}
    spec["approval"] = {
        "requires_human_confirmation": bool(unresolved),
        "unresolved_questions": unresolved,
    }
    # Re-analysis may refresh extracted values, but it must not silently erase
    # a human's attached official evidence or a prior review record.
    for key in ("official_evidence", "approved_at", "approved_note"):
        if key in previous_approval:
            spec["approval"][key] = previous_approval[key]
    spec["rule_source"] = {
        "path": str(source_path),
        "sha256": file_sha256(source_path),
        "analyzed_at": utc_now(),
        "evidence": evidence,
    }
    write_yaml(spec_path, spec)

    docs_dir = workspace / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    rule_lines = [
        "# Competition rules — review draft",
        "",
        "> This file is generated from a local source document. Confirm every unresolved item before training or submission.",
        "",
        "## Extracted specification",
        "",
    ]
    for section in ("competition", "evaluation", "submission", "constraints"):
        rule_lines.append(f"### {section.title()}")
        for key, value in spec.get(section, {}).items():
            rule_lines.append(f"- **{key}**: {value if value is not None else 'unresolved'}")
        rule_lines.append("")
    rule_lines.extend(["## Source evidence", ""])
    if evidence:
        for field, item in evidence.items():
            rule_lines.append(f"- `{field}` — line {item['line']}: {item['text']}")
    else:
        rule_lines.append("- No deterministic fields could be extracted; complete the specification manually.")
    rule_lines.extend(["", "## Required human confirmation", ""])
    rule_lines.extend(f"- [ ] {question}" for question in unresolved) if unresolved else rule_lines.append("- [x] All required fields are present; verify them against the official source.")
    (docs_dir / "competition_rules.md").write_text("\n".join(rule_lines) + "\n", encoding="utf-8")

    checklist = [
        "# Submission checklist",
        "",
        "- [ ] Official rule source is stored unchanged under `input/`.",
        "- [ ] `competition_spec.yaml` was reviewed and approval is recorded.",
        "- [ ] Submission format and filename rule were validated locally.",
        "- [ ] Inference time and model-size limits were tested where applicable.",
        "- [ ] External data, pretraining and ensemble usage comply with the rules.",
        "- [ ] Submission count / daily quota was checked before upload.",
    ]
    (docs_dir / "submission_checklist.md").write_text("\n".join(checklist) + "\n", encoding="utf-8")

    outcome = {
        "source_path": str(source_path),
        "spec_path": str(spec_path),
        "rules_report": str(docs_dir / "competition_rules.md"),
        "submission_checklist": str(docs_dir / "submission_checklist.md"),
        "requires_human_confirmation": bool(unresolved),
        "unresolved_questions": unresolved,
        "evidence_count": len(evidence),
    }
    write_json_atomic(workspace / "reports" / "rule_extraction.json", outcome)
    return outcome


def approve_rule_specification(workspace: Path, note: str) -> dict[str, Any]:
    """Record a human rule review only when all required fields are present."""
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        raise FileNotFoundError("Run rule analysis or create competition_spec.yaml before approval.")
    spec = load_yaml(spec_path)
    readiness = rule_confirmation_readiness(spec)
    if not readiness["ready"]:
        details = "; ".join(f"{item['field']}: {item['reason']}" for item in readiness["gaps"][:8])
        if len(readiness["gaps"]) > 8:
            details += f"; and {len(readiness['gaps']) - 8} more gap(s)"
        raise ValueError("Cannot approve an incomplete rule specification: " + details)
    if not note.strip():
        raise ValueError("A human review note is required for approval.")
    approval = spec.setdefault("approval", {})
    approval.update(
        {
            "requires_human_confirmation": False,
            "approved_at": utc_now(),
            "approved_note": note.strip(),
        }
    )
    write_yaml(spec_path, spec)
    outcome = {
        "spec_path": str(spec_path),
        "approved": True,
        "approved_at": approval["approved_at"],
        "note": approval["approved_note"],
        "readiness": readiness,
    }
    write_json_atomic(workspace / "reports" / "rule_approval.json", outcome)
    return outcome
