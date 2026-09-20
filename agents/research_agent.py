"""Multi-source literature and code discovery with local, inspectable records."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any, Callable

from tools.files import write_json_atomic
from tools.provenance import utc_now


USER_AGENT = "competition-agent/0.2 (local research workflow)"
QUERY_STOP_WORDS = {"a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "via", "with"}


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310: URL is a fixed provider endpoint
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Search provider returned a non-object payload")
    return payload


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _query_terms(query: str) -> list[str]:
    """Keep meaningful, repeatable English terms for provider-side filtering."""
    return [
        term
        for term in re.findall(r"[a-z0-9]+", query.lower())
        if len(term) >= 3 and term not in QUERY_STOP_WORDS
    ]


def _arxiv_expression(query: str) -> str:
    """Use documented explicit field clauses instead of an ambiguous free-text string."""
    terms = _query_terms(query)
    if not terms:
        raise ValueError("Research query needs at least one meaningful term")
    return " AND ".join(f"all:{term}" for term in terms)


def _is_relevant(record: dict[str, Any], query: str) -> bool:
    """Reject provider fallbacks that ignored a query and returned arbitrary newest work."""
    terms = _query_terms(query)
    if not terms:
        return True
    text = " ".join(
        str(record.get(key) or "") for key in ("title", "abstract", "venue")
    ).lower()
    matched = sum(term in text for term in terms)
    return matched >= min(2, len(terms))


def _base_record(source: str, identifier: str, title: str) -> dict[str, Any]:
    return {
        "paper_id": identifier,
        "source": source,
        "title": _clean(title),
        "year": None,
        "venue": None,
        "authors": [],
        "abstract": None,
        "url": None,
        "code_url": None,
        "pdf_url": None,
        "official_code": False,
        "license": None,
        "task": None,
        "relevance_score": None,
        "reproduction_priority": None,
    }


def search_arxiv(query: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {"search_query": _arxiv_expression(query), "start": 0, "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"}
    )
    request = urllib.request.Request(
        f"https://export.arxiv.org/api/query?{params}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310: fixed arXiv endpoint
        root = element_tree.fromstring(response.read())
    atom = "{http://www.w3.org/2005/Atom}"
    records: list[dict[str, Any]] = []
    for entry in root.findall(f"{atom}entry"):
        identifier = (entry.findtext(f"{atom}id") or "").rsplit("/", 1)[-1]
        record = _base_record("arxiv", f"arxiv:{identifier}", entry.findtext(f"{atom}title") or "Untitled")
        record["abstract"] = _clean(entry.findtext(f"{atom}summary") or "") or None
        published = entry.findtext(f"{atom}published") or ""
        record["year"] = int(published[:4]) if published[:4].isdigit() else None
        record["url"] = entry.findtext(f"{atom}id")
        record["pdf_url"] = f"https://arxiv.org/pdf/{identifier}.pdf"
        record["authors"] = [
            _clean(author.findtext(f"{atom}name") or "")
            for author in entry.findall(f"{atom}author")
        ]
        if _is_relevant(record, query):
            records.append(record)
    return records


def search_openalex(query: str, limit: int) -> list[dict[str, Any]]:
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": query, "per-page": limit})
    payload = _request_json(url)
    records: list[dict[str, Any]] = []
    for item in payload.get("results", []):
        identifier = str(item.get("id") or item.get("doi") or item.get("display_name"))
        record = _base_record("openalex", identifier, str(item.get("display_name") or "Untitled"))
        record["year"] = item.get("publication_year")
        record["venue"] = (item.get("primary_location") or {}).get("source", {}).get("display_name")
        record["url"] = item.get("doi") or item.get("id")
        record["pdf_url"] = (item.get("best_oa_location") or {}).get("pdf_url")
        record["authors"] = [
            str((authorship.get("author") or {}).get("display_name"))
            for authorship in item.get("authorships", [])
            if (authorship.get("author") or {}).get("display_name")
        ]
        records.append(record)
    return records


def search_semantic_scholar(query: str, limit: int) -> list[dict[str, Any]]:
    fields = "title,year,venue,abstract,authors,url,externalIds,openAccessPdf"
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
        {"query": query, "limit": limit, "fields": fields}
    )
    payload = _request_json(url)
    records: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        identifier = str(item.get("paperId") or (item.get("externalIds") or {}).get("DOI") or item.get("title"))
        record = _base_record("semantic_scholar", identifier, str(item.get("title") or "Untitled"))
        record["year"] = item.get("year")
        record["venue"] = item.get("venue")
        record["abstract"] = item.get("abstract")
        record["url"] = item.get("url") or (item.get("openAccessPdf") or {}).get("url")
        record["pdf_url"] = (item.get("openAccessPdf") or {}).get("url")
        record["authors"] = [str(author.get("name")) for author in item.get("authors", []) if author.get("name")]
        records.append(record)
    return records


def search_github(query: str, limit: int) -> list[dict[str, Any]]:
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
    )
    payload = _request_json(url)
    records: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        record = _base_record("github", f"github:{item.get('full_name')}", str(item.get("full_name") or "Untitled repository"))
        record["abstract"] = item.get("description")
        record["url"] = item.get("html_url")
        record["code_url"] = item.get("clone_url")
        record["license"] = (item.get("license") or {}).get("spdx_id")
        record["official_code"] = False
        record["year"] = int(str(item.get("created_at", ""))[:4]) if str(item.get("created_at", ""))[:4].isdigit() else None
        records.append(record)
    return records


SOURCES: dict[str, Callable[[str, int], list[dict[str, Any]]]] = {
    "arxiv": search_arxiv,
    "openalex": search_openalex,
    "semantic_scholar": search_semantic_scholar,
    "github": search_github,
}


def _deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        title_key = re.sub(r"\W+", "", record["title"].lower())
        key = str(record.get("url") or title_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def search_research(
    workspace: Path,
    query: str,
    *,
    limit: int = 5,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Search explicit public providers and persist results plus provider failures."""
    chosen = sources or ["arxiv", "openalex", "semantic_scholar", "github"]
    invalid = sorted(set(chosen) - set(SOURCES))
    if invalid:
        raise ValueError(f"Unknown research sources: {', '.join(invalid)}")
    if not query.strip():
        raise ValueError("Research query cannot be empty")
    if not 1 <= limit <= 25:
        raise ValueError("limit must be between 1 and 25")

    records: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    provider_records: dict[str, list[dict[str, Any]]] = {}
    # Providers have independent network timeouts; fan them out so one slow
    # source does not serially delay every other public result.
    with ThreadPoolExecutor(max_workers=min(4, len(chosen))) as executor:
        futures = {name: executor.submit(SOURCES[name], query, limit) for name in chosen}
    for name in chosen:
        try:
            provider_records[name] = futures[name].result()
            records.extend(provider_records[name])
        except Exception as exc:  # provider outages must not discard successful sources
            failures[name] = f"{type(exc).__name__}: {exc}"
    records = _deduplicate([record for record in records if _is_relevant(record, query)])
    for index, record in enumerate(records, 1):
        record["relevance_score"] = round(max(0.1, 1 - (index - 1) * 0.04), 3)
        record["reproduction_priority"] = round(record["relevance_score"] * (0.9 if record.get("code_url") else 0.55), 3)

    research_dir = workspace / "research"
    payload = {"query": query, "searched_at": utc_now(), "sources": chosen, "records": records, "provider_failures": failures}
    write_json_atomic(research_dir / "papers.json", payload)
    markdown = ["# Research radar", "", f"Query: `{query}`", ""]
    if records:
        markdown.extend(["| Source | Title | Year | Code | Priority |", "| --- | --- | ---: | --- | ---: |"])
        for record in records:
            title = record["title"].replace("|", "\\|")
            code = "yes" if record.get("code_url") else "no"
            markdown.append(f"| {record['source']} | {title} | {record.get('year') or ''} | {code} | {record['reproduction_priority']:.2f} |")
    else:
        markdown.append("No records were returned. Review provider failures and refine the query.")
    if failures:
        markdown.extend(["", "## Provider failures", ""])
        markdown.extend(f"- **{source}**: {message}" for source, message in failures.items())
    (research_dir / "research_radar.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return {"query": query, "records": len(records), "provider_failures": failures, "papers_path": str(research_dir / "papers.json")}
