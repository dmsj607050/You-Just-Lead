"""Download selected open papers and create safe static source-code intake records.

The workflow is triggered only after a user confirms the selected research items.
It saves public PDF evidence and clones source repositories solely for static
inspection; downloaded code is never executed here.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.reproduction_agent import intake_repository
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


MAX_MATERIAL_BYTES = 25 * 1024 * 1024


class MaterialIntakeError(ValueError):
    """Raised when selected research material cannot be safely received."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _public_https_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise MaterialIntakeError("Only explicit public HTTPS paper URLs are allowed.")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise MaterialIntakeError("Local paper URLs are not allowed.")
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(parsed.hostname, None)}
    except OSError as exc:
        raise MaterialIntakeError(f"Unable to resolve paper host: {exc}") from exc
    for address in addresses:
        try:
            if not ipaddress.ip_address(address).is_global:
                raise MaterialIntakeError("Paper URL must resolve to a public address.")
        except ValueError:
            continue
    return parsed.geturl()


def _download_pdf(url: str, destination: Path) -> dict[str, Any]:
    approved_url = _public_https_url(url)
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(approved_url, headers={"User-Agent": "YouJustLead/0.2"})
    try:
        with opener.open(request, timeout=30) as response:
            declared_size = int(response.headers.get("Content-Length", "0") or "0")
            if declared_size > MAX_MATERIAL_BYTES:
                raise MaterialIntakeError("Paper is larger than the 25 MB intake limit.")
            payload = response.read(MAX_MATERIAL_BYTES + 1)
            content_type = response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        raise MaterialIntakeError(f"Unable to download paper (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise MaterialIntakeError(f"Unable to download paper: {exc.reason}") from exc
    if len(payload) > MAX_MATERIAL_BYTES:
        raise MaterialIntakeError("Paper is larger than the 25 MB intake limit.")
    if not payload.startswith(b"%PDF"):
        raise MaterialIntakeError(f"Expected a PDF response, received {content_type or 'unknown content'}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return {
        "url": approved_url,
        "path": str(destination),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "content_type": content_type,
    }


def _pdf_excerpt(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "PDF was saved; text extraction is unavailable because pypdf is not installed."
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
    except Exception as exc:
        return f"PDF was saved but text extraction failed: {type(exc).__name__}: {exc}"
    cleaned = " ".join(text.split())
    return cleaned[:1600] if cleaned else "PDF was saved but no selectable text was found."


def _record_name(record: dict[str, Any]) -> str:
    identifier = str(record.get("paper_id") or record.get("title") or "material")
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:12]
    return digest


def intake_selected_materials(workspace: Path, paper_ids: list[str]) -> dict[str, Any]:
    """Persist selected records, download open PDFs, and clone approved code for static review."""
    if not 1 <= len(paper_ids) <= 12:
        raise MaterialIntakeError("Select between 1 and 12 research records for intake.")
    papers_path = workspace / "research" / "papers.json"
    if not papers_path.exists():
        raise FileNotFoundError("Run a research search before requesting material intake.")
    payload = read_json(papers_path)
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise MaterialIntakeError("Persisted research records are invalid.")
    requested = list(dict.fromkeys(str(item).strip() for item in paper_ids if str(item).strip()))
    selected = [item for item in records if str(item.get("paper_id")) in requested]
    if len(selected) != len(requested):
        known = {str(item.get("paper_id")) for item in selected}
        missing = sorted(set(requested) - known)
        raise MaterialIntakeError(f"Selected records are missing from the current search: {', '.join(missing[:5])}")

    materials_dir = workspace / "research" / "materials"
    item_results: list[dict[str, Any]] = []
    for record in selected:
        name = _record_name(record)
        item: dict[str, Any] = {
            "paper_id": record.get("paper_id"),
            "title": record.get("title"),
            "source": record.get("source"),
            "selected_at": utc_now(),
            "paper": {"status": "metadata_saved"},
            "code": {"status": "no_code_url"},
        }
        pdf_url = str(record.get("pdf_url") or "").strip()
        if pdf_url:
            try:
                pdf = _download_pdf(pdf_url, materials_dir / "papers" / f"{name}.pdf")
                item["paper"] = {
                    "status": "downloaded",
                    **pdf,
                    "excerpt": _pdf_excerpt(Path(pdf["path"])),
                }
            except Exception as exc:
                item["paper"] = {"status": "download_failed", "url": pdf_url, "error": f"{type(exc).__name__}: {exc}"}

        code_url = str(record.get("code_url") or "").strip()
        if code_url:
            try:
                intake = intake_repository(workspace, code_url, approved=True)
                item["code"] = {"status": intake["status"], **intake}
            except Exception as exc:
                item["code"] = {"status": "intake_failed", "url": code_url, "error": f"{type(exc).__name__}: {exc}"}
        write_json_atomic(materials_dir / "records" / f"{name}.json", item)
        item_results.append(item)

    summary = {
        "created_at": utc_now(),
        "selected_ids": requested,
        "items": item_results,
        "safety_note": "PDFs are stored as evidence. Source repositories are cloned only for static inspection and are never executed by this intake workflow.",
    }
    report_path = materials_dir / "material_analysis.json"
    write_json_atomic(report_path, summary)
    markdown = ["# Selected material intake", "", summary["safety_note"], ""]
    for item in item_results:
        markdown.extend([
            f"## {item['title']}",
            f"- Source: {item['source']}",
            f"- Paper: {item['paper']['status']}",
            f"- Code: {item['code']['status']}",
            "",
        ])
        excerpt = item["paper"].get("excerpt")
        if excerpt:
            markdown.extend(["### Extracted paper text", "", excerpt, ""])
    (materials_dir / "material_analysis.md").write_text("\n".join(markdown), encoding="utf-8")
    return {
        "items": item_results,
        "report_path": str(report_path),
        "markdown_path": str(materials_dir / "material_analysis.md"),
    }
