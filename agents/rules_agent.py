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

    spec["approval"] = {
        "requires_human_confirmation": bool(unresolved),
        "unresolved_questions": unresolved,
    }
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
