"""Multi-source literature and code discovery with local, inspectable records."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any, Callable

from tools.configuration import get_nested, load_yaml
from tools.files import write_json_atomic
from tools.provenance import utc_now


USER_AGENT = "competition-agent/0.2 (local research workflow)"
QUERY_STOP_WORDS = {"a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "via", "with"}

# 规格里写的是机器名（object_detection / visible_rgb），检索源只认英文词，
# 这几张表负责把规格翻译成检索与匹配用的词。表里没有的就留空，不猜。
TASK_TERMS: dict[str, list[str]] = {
    "object_detection": ["object detection", "detector"],
    "image_classification": ["image classification", "classifier"],
    "image_segmentation": ["image segmentation", "segmentation"],
    "tabular_classification": ["tabular classification"],
    "tabular_regression": ["tabular regression"],
}
MODALITY_TERMS: dict[str, list[str]] = {
    "visible_rgb": ["rgb"],
    "infrared": ["infrared", "thermal"],
    "depth": ["depth"],
    "audio": ["audio"],
    "text": ["natural language"],
    "lidar": ["lidar", "point cloud"],
}
# 指标名太短或太常见（map / iou / f1），当**检索词**会把结果带偏，所以只参与匹配打分。
METRIC_TERMS: dict[str, list[str]] = {
    "map@50-95": ["mean average precision"],
    "map@50": ["average precision"],
    "iou": ["intersection over union"],
    "dice": ["dice coefficient"],
    "accuracy": ["accuracy"],
    "f1": ["f1 score"],
    "rmse": ["rmse"],
    "bleu": ["bleu"],
}
# 两种以上模态时补进去：这类任务的区分度就在「融合」上。
FUSION_TERMS = ["multimodal", "multi-modal", "fusion"]

# provider 侧是把词 AND 起来查的，词越多命中越少，所以检索式有词数上限。
QUERY_MAX_TERMS = 5

# 相关性打分的四项权重。词命中占大头，任务匹配次之，有没有代码与年份只做微调。
SCORE_WEIGHTS = {"terms": 0.45, "task": 0.25, "code": 0.20, "recency": 0.10}


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310: URL is a fixed provider endpoint
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Search provider returned a non-object payload")
    return payload


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def query_terms(query: str) -> list[str]:
    """Keep meaningful, repeatable English terms for provider-side filtering."""
    return [
        term
        for term in re.findall(r"[a-z0-9]+", query.lower())
        if len(term) >= 3 and term not in QUERY_STOP_WORDS
    ]


def spec_terms(spec: dict[str, Any]) -> dict[str, list[str]]:
    """把竞赛规格折成几组英文词：任务、模态、指标。

    `modality` 是全量变体（thermal 也算 infrared），用于**匹配**；`modality_primary`
    每种模态只留主名（infrared 只留 infrared），用于**拼检索式** —— 检索式有词数上限，
    让 thermal 挤掉 depth 会把多模态这件事查没。

    规格里没写的项返回空列表 —— 打分时该分量直接不参与，而不是给个中性分糊过去。
    """
    task_type = _clean(str(get_nested(spec, "competition.task_type") or "")).lower().replace(" ", "_")
    raw_modalities = get_nested(spec, "data.modalities")
    modalities = raw_modalities if isinstance(raw_modalities, list) else []
    metric = _clean(str(get_nested(spec, "evaluation.primary_metric") or "")).lower()

    modality: list[str] = []
    modality_primary: list[str] = []
    for item in modalities:
        variants = MODALITY_TERMS.get(_clean(str(item)).lower().replace(" ", "_"), [])
        modality.extend(variants)
        if variants:
            modality_primary.append(variants[0])
    if len(modalities) >= 2:
        modality.extend(FUSION_TERMS)
        modality_primary.extend(FUSION_TERMS[:1])

    return {
        "task": list(TASK_TERMS.get(task_type, [])),
        "modality": modality,
        "modality_primary": modality_primary,
        "metric": list(METRIC_TERMS.get(metric, [])),
    }


def build_research_query(spec: dict[str, Any]) -> str:
    """按规则规格拼检索式。

    只用任务主词与模态主词：指标词太泛（map / iou），备用任务词（detector）会挤掉模态词，
    都会把结果带偏。上限 5 个词，超出就不再往里加。
    """
    groups = spec_terms(spec)
    candidates = list(groups["task"][:1]) + list(groups["modality_primary"])
    terms: list[str] = []
    for value in candidates:
        for term in query_terms(value):
            if term not in terms:
                terms.append(term)
            if len(terms) >= QUERY_MAX_TERMS:
                return " ".join(terms)
    return " ".join(terms)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).lower()


def _hits(haystack: str, terms: list[str]) -> int:
    return sum(1 for term in terms if term in haystack)


def score_record(
    record: dict[str, Any],
    terms: list[str],
    groups: dict[str, list[str]],
    *,
    this_year: int,
) -> dict[str, Any]:
    """给一条文献打分，并把每一项单独留在 `relevance_parts` 里。

    以前这里的 `relevance_score` 是列表位置衰减（第 1 条 1.0、第 2 条 0.96…），
    看起来像相关系数，其实只反映 provider 的返回顺序。现在改成四项可复算的分量：
    查询词命中、任务匹配、有没有代码、年份新旧。算不出来的分量给 None，
    权重里剔除它再归一 —— 缺数据时不拿中性分糊过去。
    """
    title = _text(record.get("title"))
    abstract = _text(record.get("abstract"))
    venue = _text(record.get("venue"))

    parts: dict[str, float | None] = {}
    if terms:
        # 标题权重最高：标题里就写着查询词的论文，比摘要里顺带提到的更相关。
        weighted = 1.0 * _hits(title, terms) + 0.5 * _hits(abstract, terms) + 0.2 * _hits(venue, terms)
        parts["terms"] = min(1.0, weighted / len(terms))
    else:
        parts["terms"] = None

    task_terms = groups["task"] + groups["modality"] + groups["metric"]
    if task_terms:
        parts["task"] = _hits(" ".join([title, abstract]), task_terms) / len(task_terms)
    else:
        parts["task"] = None

    parts["code"] = 1.0 if record.get("code_url") else 0.0

    year = record.get("year")
    if isinstance(year, int) and year > 1900:
        parts["recency"] = max(0.2, 1.0 - max(0, this_year - year) * 0.1)
    else:
        parts["recency"] = None

    total_weight = sum(SCORE_WEIGHTS[name] for name, value in parts.items() if value is not None)
    score = (
        sum(SCORE_WEIGHTS[name] * float(value) for name, value in parts.items() if value is not None) / total_weight
        if total_weight
        else 0.0
    )
    priority = score * (1.0 if record.get("code_url") else 0.6)
    return {
        "relevance_score": round(score, 3),
        "relevance_parts": {name: (None if value is None else round(value, 3)) for name, value in parts.items()},
        "reproduction_priority": round(priority, 3),
    }


def score_records(
    records: list[dict[str, Any]],
    query: str,
    spec: dict[str, Any],
    *,
    this_year: int | None = None,
) -> list[dict[str, Any]]:
    """给整批结果打分并写上字段，返回同一批记录（按相关性从高到低重排）。"""
    year = this_year if this_year is not None else datetime.now(timezone.utc).year
    terms = query_terms(query)
    groups = spec_terms(spec)
    for record in records:
        record.update(score_record(record, terms, groups, this_year=year))
    return sorted(records, key=lambda item: float(item.get("relevance_score") or 0), reverse=True)


def _arxiv_expression(query: str) -> str:
    """Use documented explicit field clauses instead of an ambiguous free-text string."""
    terms = query_terms(query)
    if not terms:
        raise ValueError("Research query needs at least one meaningful term")
    return " AND ".join(f"all:{term}" for term in terms)


def _is_relevant(record: dict[str, Any], query: str) -> bool:
    """Reject provider fallbacks that ignored a query and returned arbitrary newest work."""
    terms = query_terms(query)
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
        "stars": None,
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
        # `primary_location.source` 可能是显式的 null，所以每一项都要 `or {}` 再取 ——
        # 只给 `.get(key, {})` 挡不住「键在、值是 None」这种情况。
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        record["year"] = item.get("publication_year")
        record["venue"] = source.get("display_name")
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
        # 星数是仓库热度的唯一客观信号，候选评判用它排掉同名的小仓库。
        record["stars"] = item.get("stargazers_count")
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
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search explicit public providers and persist results plus provider failures.

    `spec` 是竞赛规则规格，只用于打分时判断「任务匹配」这一项；传 None 时按工作区里
    已有的 `competition_spec.yaml` 读一次，读不到就该项不参与（不会伪造一个匹配分）。
    """
    chosen = sources or ["arxiv", "openalex", "semantic_scholar", "github"]
    invalid = sorted(set(chosen) - set(SOURCES))
    if invalid:
        raise ValueError(f"Unknown research sources: {', '.join(invalid)}")
    if not query.strip():
        raise ValueError("Research query cannot be empty")
    if not 1 <= limit <= 25:
        raise ValueError("limit must be between 1 and 25")

    resolved_spec = spec
    if resolved_spec is None:
        spec_path = workspace / "competition_spec.yaml"
        resolved_spec = load_yaml(spec_path) if spec_path.exists() else {}

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
    records = score_records(records, query, resolved_spec)

    research_dir = workspace / "research"
    payload = {"query": query, "searched_at": utc_now(), "sources": chosen, "records": records, "provider_failures": failures}
    write_json_atomic(research_dir / "papers.json", payload)
    markdown = ["# Research radar", "", f"Query: `{query}`", ""]
    if records:
        markdown.extend(["| Source | Title | Year | Code | Relevance | Priority |", "| --- | --- | ---: | --- | ---: | ---: |"])
        for record in records:
            title = record["title"].replace("|", "\\|")
            code = "yes" if record.get("code_url") else "no"
            markdown.append(
                f"| {record['source']} | {title} | {record.get('year') or ''} | {code} | "
                f"{record['relevance_score']:.2f} | {record['reproduction_priority']:.2f} |"
            )
    else:
        markdown.append("No records were returned. Review provider failures and refine the query.")
    if failures:
        markdown.extend(["", "## Provider failures", ""])
        markdown.extend(f"- **{source}**: {message}" for source, message in failures.items())
    (research_dir / "research_radar.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return {"query": query, "records": len(records), "provider_failures": failures, "papers_path": str(research_dir / "papers.json")}
