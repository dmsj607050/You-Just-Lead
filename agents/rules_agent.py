"""Turn a local competition rule document into reviewable structured artefacts.

This module deliberately treats extraction as a draft.  A competition rule can be
ambiguous, therefore every missing or weakly extracted field remains in the
``unresolved_questions`` list and keeps human confirmation enabled.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import re
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.configuration import display_value, get_nested, load_yaml, write_yaml
from tools.files import write_json_atomic
from tools.provenance import file_sha256, utc_now


FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "competition.name": (
        r"^(?:competition(?:\s+name)?|比赛(?:名称)?)\s*[:：]\s*(.+)$",
        r"^#\s+(.+)$",
    ),
    "competition.platform": (r"^(?:platform|平台)\s*[:：]\s*(.+)$",),
    "competition.task_type": (r"^(?:task(?:\s+type)?|任务(?:类型)?)\s*[:：]\s*(.+)$",),
    "data.requirements": (r"^(?:data(?:set)?(?:\s+requirements?)?|数据(?:要求|集要求)?)\s*[:：]\s*(.+)$",),
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

MAX_RULE_SOURCE_BYTES = 12 * 1024 * 1024
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}

class RuleImportError(ValueError):
    """Raised when a local or remote rule source cannot be safely imported."""

class _VisibleTextParser(HTMLParser):
    """Small dependency-free HTML-to-text adapter for official rule pages."""
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignored_depth = 0
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        elif tag in {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")
    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")
    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)
    def text(self) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)


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
    return get_nested(payload, dotted_name)


def _deep_set(payload: dict[str, Any], dotted_name: str, value: Any) -> None:
    keys = dotted_name.split(".")
    parent = payload
    for key in keys[:-1]:
        next_value = parent.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            parent[key] = next_value
        parent = next_value
    parent[keys[-1]] = value


def is_meaningful(value: Any) -> bool:
    """判断规格里的一个值是否已经真正填好（占位词如「待填」不算）。"""
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return bool(normalized) and normalized not in {"unresolved", "unknown", "tbd", "todo", "待填", "待确认"} and "待填" not in normalized
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
        if not is_meaningful(value):
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
            if not is_meaningful(evidence.get(field)):
                gaps.append(
                    {
                        "field": f"approval.official_evidence.{field}",
                        "reason": "Record the official rule-page or document evidence used for review.",
                    }
                )
        field_evidence = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
        for field in required_fields:
            if not is_meaningful(field_evidence.get(field)):
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


def apply_official_rule_evidence(workspace: Path, evidence_path: Path) -> dict[str, Any]:
    """Apply a complete, human-reviewed Xunfei rule evidence record.

    The caller supplies a compact YAML record whose values and source anchors
    are copied from an official rule page or official PDF.  This action records
    evidence and deliberately *does not* approve the rules or a GPU run.
    """
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        raise FileNotFoundError("competition_spec.yaml is required before applying rule evidence")
    evidence_path = evidence_path.resolve()
    if not evidence_path.is_file():
        raise FileNotFoundError(f"Rule evidence record does not exist: {evidence_path}")
    spec = load_yaml(spec_path)
    if not _is_xunfei_waterseg_spec(spec):
        raise ValueError("This evidence-record workflow is currently scoped to the Xunfei water-segmentation adapter")
    record = load_yaml(evidence_path)
    source = record.get("source")
    fields = record.get("fields")
    if not isinstance(source, dict):
        raise ValueError("Rule evidence must contain a source mapping")
    if not isinstance(fields, dict):
        raise ValueError("Rule evidence must contain a fields mapping")
    required = list(BASE_CONFIRMATION_FIELDS) + list(XUNFEI_CONFIRMATION_FIELDS)
    unknown = sorted(set(fields) - set(required))
    if unknown:
        raise ValueError("Rule evidence contains unsupported fields: " + ", ".join(unknown))
    missing: list[str] = []
    anchors: dict[str, str] = {}
    values: dict[str, Any] = {}
    for name in required:
        item = fields.get(name)
        if not isinstance(item, dict):
            missing.append(name)
            continue
        value = item.get("value")
        anchor = item.get("anchor")
        if not is_meaningful(value) or not is_meaningful(anchor):
            missing.append(name)
            continue
        values[name] = value
        anchors[name] = str(anchor).strip()
    source_missing = [name for name in ("source_type", "source_locator", "reviewed_at") if not is_meaningful(source.get(name))]
    if "..." in str(source.get("source_locator", "")):
        source_missing.append("source_locator")
    if missing or source_missing:
        details = [f"field {name}" for name in missing] + [f"source.{name}" for name in source_missing]
        raise ValueError("Incomplete official rule evidence: " + ", ".join(details))

    output_mode = str(values["submission.contract.runtime_output"]).lower()
    if output_mode not in {"loose_png", "submit_zip"}:
        raise ValueError("submission.contract.runtime_output must be loose_png or submit_zip")
    for boolean_field in (
        "constraints.external_data_allowed",
        "constraints.pretrained_models_allowed",
        "constraints.ensemble_allowed",
    ):
        if not isinstance(values[boolean_field], bool):
            raise ValueError(f"{boolean_field} must be a YAML boolean: true or false")

    for name, value in values.items():
        _deep_set(spec, name, value)
    approval = spec.setdefault("approval", {})
    approval["official_evidence"] = {
        "source_type": str(source["source_type"]).strip(),
        "source_locator": str(source["source_locator"]).strip(),
        "reviewed_at": str(source["reviewed_at"]).strip(),
        "confirmation_file": str(evidence_path),
        "confirmation_file_sha256": file_sha256(evidence_path),
        "fields": anchors,
    }
    # Evidence capture and permission to run are intentionally separate.
    approval["requires_human_confirmation"] = True
    approval["unresolved_questions"] = []
    approval.pop("approved_at", None)
    approval.pop("approved_note", None)
    write_yaml(spec_path, spec)
    readiness = rule_confirmation_readiness(spec)
    outcome = {
        "spec_path": str(spec_path),
        "evidence_path": str(evidence_path),
        "applied_fields": required,
        "requires_human_confirmation": True,
        "readiness": readiness,
        "next_action": "Run approve-rules after independently reviewing the recorded evidence.",
    }
    write_json_atomic(workspace / "reports" / "official_rule_evidence_applied.json", outcome)
    return outcome


# 界面录入证据时每个字段的值控件类型。只有类型敏感的字段需要特判，其余按文本处理；
# 列表与数值不允许在界面里改写，避免把 1024,1024 这种输入写成字符串。
EVIDENCE_FIELD_KINDS = {
    "submission.contract.runtime_output": "runtime_output",
    "constraints.external_data_allowed": "boolean",
    "constraints.pretrained_models_allowed": "boolean",
    "constraints.ensemble_allowed": "boolean",
    "submission.contract.required_files": "list",
    "submission.contract.mask_size": "list",
    "submission.daily_limit": "number",
    "constraints.model_size_limit_mb": "number",
    "evaluation.direction": "direction",
}


def rule_evidence_form_for_workspace(workspace: Path) -> dict[str, Any]:
    """界面「录入官方证据」需要的表单状态：逐字段现值/锚点 + 值控件类型。

    只读，不改任何文件。`supported` 为假时界面禁用录入：证据记录与应用目前只对
    完成集成的讯飞水体分割档案开放，通用竞赛的规则来源不同，不能套同一张表。
    """
    spec_path = workspace / "competition_spec.yaml"
    spec = load_yaml(spec_path) if spec_path.exists() else {}
    readiness = rule_confirmation_readiness_for_workspace(workspace)
    approval = spec.get("approval") if isinstance(spec.get("approval"), dict) else {}
    evidence = approval.get("official_evidence") if isinstance(approval.get("official_evidence"), dict) else {}
    anchors = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}

    fields: list[dict[str, Any]] = []
    for name in readiness.get("required_fields", []):
        value = _deep_get(spec, name)
        anchor = anchors.get(name)
        fields.append(
            {
                "field": name,
                "value": display_value(value),
                "has_value": is_meaningful(value),
                "anchor": display_value(anchor),
                "has_anchor": is_meaningful(anchor),
                "kind": EVIDENCE_FIELD_KINDS.get(name, "text"),
            }
        )

    return {
        "supported": bool(spec) and _is_xunfei_waterseg_spec(spec),
        "profile": readiness.get("profile"),
        "spec_path": str(spec_path) if spec_path.exists() else None,
        "source": {
            "source_type": display_value(evidence.get("source_type")),
            "source_locator": display_value(evidence.get("source_locator")),
            "reviewed_at": display_value(evidence.get("reviewed_at")),
            "confirmation_file": display_value(evidence.get("confirmation_file")),
        },
        "fields": fields,
        "required_field_count": len(fields),
        "missing_value_count": sum(1 for item in fields if not item["has_value"]),
        "missing_anchor_count": sum(1 for item in fields if not item["has_anchor"]),
    }


def build_rule_evidence_record(
    *,
    spec: dict[str, Any],
    source: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """把界面提交的改动合并到规格现值与已有锚点上，得到一份完整的证据记录。

    界面只提交「人实际填的东西」，其余字段沿用规格里的值，所以数值/布尔/列表
    不需要在客户端往返一遍、也不会被字符串化。缺值或缺锚点在这里就被拦下，
    免得写出一份自以为完整的证据。
    """
    required = list(BASE_CONFIRMATION_FIELDS) + list(XUNFEI_CONFIRMATION_FIELDS)
    approval = spec.get("approval") if isinstance(spec.get("approval"), dict) else {}
    evidence = approval.get("official_evidence") if isinstance(approval.get("official_evidence"), dict) else {}
    anchors = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}

    record_fields: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name in required:
        override = overrides.get(name)
        override = override if isinstance(override, dict) else {}
        value = _deep_get(spec, name)
        anchor = anchors.get(name)
        # 布尔字段用 value_flag 传，显式的 false 不能被当成「没填」。
        if "value_flag" in override:
            value = bool(override["value_flag"])
        elif is_meaningful(override.get("value_text")):
            value = str(override["value_text"]).strip()
        if is_meaningful(override.get("anchor")):
            anchor = str(override["anchor"]).strip()
        if not is_meaningful(value) or not is_meaningful(anchor):
            missing.append(name)
            continue
        record_fields[name] = {"value": value, "anchor": anchor}

    if missing:
        raise ValueError("Incomplete official rule evidence: " + ", ".join(f"field {name}" for name in missing))
    return {"source": dict(source), "fields": record_fields}


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        raise RuleImportError("Image OCR is not configured. Upload a PDF, Markdown, text file, or rule-page URL instead.")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuleImportError("PDF support requires the pypdf package in the local Agent runtime.") from exc
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise RuleImportError(f"Unable to open PDF rule document: {exc}") from exc
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            raise RuleImportError("No selectable text was found in this PDF. Use a text PDF or provide OCR text for a scanned document.")
        return text
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            decoded = data.decode(encoding)
            if decoded:
                break
        except UnicodeDecodeError:
            continue
    else:
        decoded = data.decode("utf-8", errors="replace")
    if suffix in {".htm", ".html", ".xhtml"} or "<html" in decoded[:1000].lower():
        parser = _VisibleTextParser()
        parser.feed(decoded)
        parsed = parser.text()
        if parsed:
            return parsed

    return decoded

def _safe_rule_filename(filename: str, default: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._")
    return candidate or default

def _validate_public_rule_url(source_url: str):
    parsed = urlparse(source_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise RuleImportError("Rule-page URLs must use http or https.")
    host = parsed.hostname
    if not host or host.lower() in {"localhost", "localhost.localdomain"}:
        raise RuleImportError("Local rule-page URLs are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise RuleImportError(f"Unable to resolve rule-page host: {exc}") from exc
    for address in addresses:
        try:
            ip_address = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not ip_address.is_global:
            raise RuleImportError("Rule-page URL must resolve to a public address.")
    return parsed

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _download_rule_page(source_url: str) -> tuple[bytes, str, Any]:
    parsed = _validate_public_rule_url(source_url)
    opener = build_opener(_NoRedirect)
    request = Request(source_url, headers={"User-Agent": "YouJustLead/0.1"})
    try:
        with opener.open(request, timeout=20) as response:
            declared_size = int(response.headers.get("Content-Length", "0") or "0")
            if declared_size > MAX_RULE_SOURCE_BYTES:
                raise RuleImportError("Rule page is larger than the 12 MB import limit.")
            payload = response.read(MAX_RULE_SOURCE_BYTES + 1)
            media_type = response.headers.get_content_type()
    except HTTPError as exc:
        raise RuleImportError(f"Unable to download rule page (HTTP {exc.code}).") from exc
    except URLError as exc:
        raise RuleImportError(f"Unable to download rule page: {exc.reason}") from exc
    if len(payload) > MAX_RULE_SOURCE_BYTES:
        raise RuleImportError("Rule page is larger than the 12 MB import limit.")
    return payload, media_type, parsed

def import_rule_source(workspace: Path, *, filename: str = "", content_base64: str = "", source_url: str = "") -> dict[str, Any]:
    has_upload = bool(content_base64.strip())
    has_url = bool(source_url.strip())
    if has_upload == has_url:
        raise RuleImportError("Provide exactly one rule file or one rule-page URL.")
    if has_upload:
        encoded = content_base64.split(",", 1)[-1].strip()
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuleImportError("Rule-file upload is not valid base64 data.") from exc
        source_kind = "file"
        safe_name = _safe_rule_filename(filename, "official_rules.txt")
    else:
        payload, media_type, parsed = _download_rule_page(source_url)
        suffix = Path(parsed.path).suffix.lower()
        if not suffix:
            suffix = ".pdf" if media_type == "application/pdf" else ".html"
        source_kind = "url"
        safe_name = _safe_rule_filename(f"{parsed.hostname or 'rule-page'}{suffix}", f"rule-page{suffix}")
    if not payload:
        raise RuleImportError("Rule source is empty.")
    if len(payload) > MAX_RULE_SOURCE_BYTES:
        raise RuleImportError("Rule source is larger than the 12 MB import limit.")
    source_dir = workspace / "input" / "rules"
    source_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    stored_source = source_dir / f"{digest[:12]}_{safe_name}"
    stored_source.write_bytes(payload)
    analysis = analyze_rules(stored_source, workspace)
    spec_path = workspace / "competition_spec.yaml"
    spec = load_yaml(spec_path)
    if has_url:
        spec.setdefault("rule_source", {})["origin_url"] = source_url.strip()
        write_yaml(spec_path, spec)
    report_path = Path(analysis["rules_report"])
    return {
        "source": {"kind": source_kind, "filename": stored_source.name, "path": str(stored_source), "sha256": digest, "url": source_url.strip() or None},
        "analysis": analysis,
        "spec": spec,
        "readiness": rule_confirmation_readiness(spec),
        "report_markdown": report_path.read_text(encoding="utf-8") if report_path.exists() else "",
    }

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
                    _deep_set(spec, dotted_name, value)
                    evidence[dotted_name] = {"line": line_number, "text": line, "value": value}
                    break
            if dotted_name in evidence:
                break

    for field, extracted in _constraint_flags(lines).items():
        spec.setdefault("constraints", {})[field] = extracted["value"]
        evidence[f"constraints.{field}"] = extracted

    unresolved: list[str] = []
    for field in REQUIRED_FIELDS:
        if not _deep_get(spec, field):
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
    for key in ("official_evidence",):
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
    for section in ("competition", "data", "evaluation", "submission", "constraints"):
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
