"""Read-only provenance chains for the trace page.

四条链只读已有证据、不写任何文件：界面据此回答「这条结论能不能回到原始证据」。
规格与规则缺口复用 agents/rules_agent，实验范围复用 tools/experiment_scope，
所以这里不会与工作流页、数据页对同一份证据给出不同说法。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.rules_agent import is_meaningful, rule_confirmation_readiness_for_workspace
from tools.configuration import display_value, get_nested, load_yaml
from tools.experiment_scope import manifests_by_id, scope_exclusion
from tools.files import read_json
from tools.provenance import utc_now

# 证据文档的后缀：只列人写的说明与引用文件，不列数据文件。
_DOCUMENT_SUFFIXES = (".md", ".yaml", ".yml", ".bib")


def _json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError):
        return {}
    return payload


def _documents(directory: Path, workspace: Path) -> list[dict[str, Any]]:
    """目录下的人工证据文档，按其工作区相对路径排序。"""
    if not directory.exists():
        return []
    documents: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _DOCUMENT_SUFFIXES:
            continue
        documents.append(
            {
                "name": path.name,
                "path": path.relative_to(workspace).as_posix(),
                "size_bytes": path.stat().st_size,
            }
        )
    return documents


def _rule_chain(workspace: Path) -> dict[str, Any]:
    """规则链：字段值 → 官方锚点 → 来源定位 → 人工复核记录。

    只展示已经存在的东西：`official_evidence` 里没写的字段就是缺锚点，
    不会拿证据模板里的示例值冒充结论。
    """
    spec_path = workspace / "competition_spec.yaml"
    spec = load_yaml(spec_path) if spec_path.exists() else {}
    readiness = rule_confirmation_readiness_for_workspace(workspace)
    approval = spec.get("approval") if isinstance(spec.get("approval"), dict) else {}
    evidence = approval.get("official_evidence") if isinstance(approval.get("official_evidence"), dict) else {}
    anchors = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
    questions = approval.get("unresolved_questions")

    fields: list[dict[str, Any]] = []
    for name in readiness.get("required_fields", []):
        value = get_nested(spec, name)
        anchor = anchors.get(name)
        fields.append(
            {
                "field": name,
                "value": display_value(value),
                "has_value": is_meaningful(value),
                "anchor": display_value(anchor),
                "has_anchor": is_meaningful(anchor),
            }
        )

    return {
        "spec_path": str(spec_path) if spec_path.exists() else None,
        "profile": readiness.get("profile"),
        "ready": bool(readiness.get("ready")),
        "gap_count": len(readiness.get("gaps", [])),
        # 规则关口只在人工确认后把 requires_human_confirmation 置 false，这里据此判断。
        "approved": approval.get("requires_human_confirmation") is False,
        "approved_at": display_value(approval.get("approved_at")),
        "approved_note": display_value(approval.get("approved_note")),
        "source": {
            "source_type": display_value(evidence.get("source_type")),
            "source_locator": display_value(evidence.get("source_locator")),
            "reviewed_at": display_value(evidence.get("reviewed_at")),
            "confirmation_file": display_value(evidence.get("confirmation_file")),
        },
        "unresolved_questions": [str(item) for item in questions if str(item).strip()]
        if isinstance(questions, list)
        else [],
        "fields": fields,
        "required_field_count": len(fields),
        "missing_value_count": sum(1 for item in fields if not item["has_value"]),
        "missing_anchor_count": sum(1 for item in fields if not item["has_anchor"]),
        "documents": _documents(workspace / "docs", workspace),
    }


def _data_chain(workspace: Path) -> dict[str, Any]:
    """数据链：审计指纹 → 每个实验的 data.version → 是否落在审计范围内。"""
    audit = _json_or_empty(workspace / "reports" / "data_statistics.json")
    scope: list[dict[str, Any]] = []
    for experiment_id, manifest in sorted(manifests_by_id(workspace).items()):
        config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        data = config.get("data") if isinstance(config.get("data"), dict) else {}
        exclusion = scope_exclusion(workspace, manifest)
        scope.append(
            {
                "experiment_id": experiment_id,
                "in_scope": exclusion is None,
                "exclusion": exclusion,
                "data_version": display_value(data.get("version")),
            }
        )

    return {
        "audit": {
            "available": bool(audit),
            "data_dir": display_value(audit.get("data_dir")),
            "inventory_sha256": display_value(audit.get("inventory_sha256")),
            "file_count": audit.get("file_count"),
            "issue_count": audit.get("issue_count"),
            "generated_at": display_value(audit.get("generated_at")),
        },
        "experiments": scope,
        "in_scope_count": sum(1 for item in scope if item["in_scope"]),
    }


def _experiment_chain(workspace: Path) -> dict[str, Any]:
    """实验链：清单（假设/配置指纹/环境）→ 结果（指标/结论/产物）→ 人工批准。"""
    results_dir = workspace / "experiments" / "results"
    experiments: list[dict[str, Any]] = []
    for experiment_id, manifest in sorted(manifests_by_id(workspace).items()):
        result = _json_or_empty(results_dir / f"{experiment_id}.json")
        approval = _json_or_empty(workspace / "experiments" / "approvals" / f"{experiment_id}.json")
        git = manifest.get("git") if isinstance(manifest.get("git"), dict) else {}
        environment = manifest.get("environment") if isinstance(manifest.get("environment"), dict) else {}
        artifacts: list[dict[str, Any]] = []
        artifact_paths = result.get("artifact_paths")
        for value in artifact_paths if isinstance(artifact_paths, list) else []:
            path = Path(str(value))
            artifacts.append(
                {
                    "path": str(value),
                    "name": path.name,
                    "exists": path.exists(),
                    "size_bytes": path.stat().st_size if path.is_file() else None,
                }
            )
        exclusion = scope_exclusion(workspace, manifest)
        experiments.append(
            {
                "experiment_id": experiment_id,
                "in_scope": exclusion is None,
                "exclusion": exclusion,
                "status": result.get("status") or manifest.get("status"),
                "change_type": manifest.get("change_type"),
                "hypothesis": manifest.get("hypothesis"),
                "config_path": manifest.get("config_path"),
                "config_sha256": manifest.get("config_sha256"),
                "created_at": manifest.get("created_at"),
                "seed": manifest.get("seed"),
                "parent_id": manifest.get("parent_id"),
                "git": {
                    "available": bool(git.get("available")),
                    "commit": git.get("commit"),
                    "branch": git.get("branch"),
                    "dirty": git.get("dirty"),
                },
                "environment": {
                    "python": environment.get("python"),
                    "platform": environment.get("platform"),
                    "torch": environment.get("torch"),
                    "cuda_available": environment.get("cuda_available"),
                    "gpu": environment.get("gpu"),
                },
                "metrics": result.get("metrics", {}),
                "validation_metric": result.get("validation_metric"),
                "decision": result.get("decision"),
                "conclusion": result.get("conclusion"),
                "error": result.get("error"),
                "started_at": result.get("started_at"),
                "finished_at": result.get("finished_at"),
                "runtime_seconds": result.get("runtime_seconds"),
                "tracker_backend": result.get("tracker_backend"),
                "result_path": f"experiments/results/{experiment_id}.json" if result else None,
                "artifacts": artifacts,
                "approval": {
                    "recorded": bool(approval),
                    "approved_at": approval.get("approved_at"),
                    "approved_by": approval.get("approved_by"),
                },
            }
        )

    return {
        "experiments": experiments,
        "in_scope_count": sum(1 for item in experiments if item["in_scope"]),
        "artifact_missing_count": sum(
            1 for item in experiments for artifact in item["artifacts"] if not artifact["exists"]
        ),
    }


def _research_chain(workspace: Path) -> dict[str, Any]:
    """文献链：检索条件 → 记录（带 url/编号）→ 检索失败也如实上报。"""
    research_dir = workspace / "research"
    payload = _json_or_empty(research_dir / "papers.json")
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    failures = payload.get("provider_failures") if isinstance(payload.get("provider_failures"), dict) else {}
    return {
        "query": display_value(payload.get("query")),
        "searched_at": display_value(payload.get("searched_at")),
        "provider_failures": {str(key): str(value) for key, value in failures.items()},
        "record_count": len(records),
        "records": [
            {
                "paper_id": record.get("paper_id"),
                "title": record.get("title"),
                "url": record.get("url"),
                "source": record.get("source"),
                "year": record.get("year"),
                "relevance_score": record.get("relevance_score"),
                "reproduction_priority": record.get("reproduction_priority"),
                "code_url": record.get("code_url"),
                "official_code": bool(record.get("official_code")),
            }
            for record in records
            if isinstance(record, dict)
        ],
        "documents": _documents(research_dir, workspace),
    }


def paper_package_report(project_root: Path, workspace: Path) -> dict[str, Any]:
    """论文终点：已有证据包与投稿契约。

    只读，不重新生成包，所以一次 GET 不会改动任何证据。
    每条 claim 额外带上 `result_exists`：界面据此判断它引用的结果文件是否还在。
    """
    package_dir = project_root / "paper" / "generated"
    tex_path = package_dir / "competition_report.tex"
    bib_path = package_dir / "references.bib"
    evidence_path = package_dir / "evidence_map.json"
    evidence = _json_or_empty(evidence_path)

    sections: list[str] = []
    if tex_path.exists():
        for line in tex_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("\\section{"):
                sections.append(stripped[len("\\section{"):].rstrip("}"))

    bib_entries = 0
    if bib_path.exists():
        bib_entries = sum(1 for line in bib_path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("@"))

    spec_path = workspace / "competition_spec.yaml"
    spec = load_yaml(spec_path) if spec_path.exists() else {}
    submission = spec.get("submission", {}) or {}
    contract = submission.get("contract", {}) or {}

    raw_claims = evidence.get("claims")
    claims: list[dict[str, Any]] = []
    for claim in raw_claims if isinstance(raw_claims, list) else []:
        if not isinstance(claim, dict):
            continue
        result_path = str(claim.get("result_path") or "")
        resolved = (
            (workspace / result_path).exists() or (project_root / result_path).exists()
            if result_path
            else False
        )
        claims.append({**claim, "result_exists": resolved})

    return {
        "available": tex_path.exists(),
        "package_dir": str(package_dir),
        "tex_path": str(tex_path) if tex_path.exists() else None,
        "bib_path": str(bib_path) if bib_path.exists() else None,
        "evidence_path": str(evidence_path) if evidence_path.exists() else None,
        "generated_at": evidence.get("generated_at"),
        "sections": sections,
        "claims": claims,
        "research_records": evidence.get("research_records", 0),
        "bib_entries": bib_entries,
        "submission": {
            "format": submission.get("format"),
            "filename_rule": submission.get("filename_rule"),
            "daily_limit": submission.get("daily_limit"),
            "validation_profile": submission.get("validation_profile"),
            "required_files": contract.get("required_files", []),
            "mask_size": contract.get("mask_size", []),
        },
    }


def trace_snapshot(project_root: Path, workspace: Path) -> dict[str, Any]:
    """四条链 + 论文终点，全部来自已有文件。"""
    return {
        "generated_at": utc_now(),
        "workspace": str(workspace),
        "rule": _rule_chain(workspace),
        "data": _data_chain(workspace),
        "experiments": _experiment_chain(workspace),
        "research": _research_chain(workspace),
        "paper": paper_package_report(project_root, workspace),
    }
