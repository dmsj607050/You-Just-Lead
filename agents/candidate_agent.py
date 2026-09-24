"""Literature triage and value assessment: what to investigate, and what it is worth.

This module owns the two steps between "we found papers" and "we decide to build on
one of them":

* **triage** -- the operator marks each candidate `investigate` or `discard`. The
  decision is recorded next to the search results, never inside them, so a re-run of
  the search cannot silently rewrite what a human already decided.
* **assessment** -- for the candidates marked `investigate`, collect the evidence that
  answers "is this worth reproducing?" (public code, licence, task fit, recency) and
  reduce it to a verdict. Every signal is a fact with a source; nothing is guessed.

The verdict is deliberately an enum plus a list of evidence signals rather than a
sentence: the app owns the wording, this module owns the facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agents.research_agent import query_terms, search_github
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


DECISIONS = ("undecided", "investigate", "discard")
PAPERS_FILE = "research/papers.json"
DECISIONS_FILE = "research/candidate_decisions.json"
ASSESSMENTS_FILE = "research/candidate_assessments.json"

# 拿论文标题去 GitHub 搜仓库时，标题词在仓库名/描述里的命中率下限。
# 低于它就不把那个仓库算成「这篇工作的代码」—— 宁可说没找到，也不要指错仓库。
CODE_TITLE_OVERLAP = 0.6
CODE_CANDIDATE_LIMIT = 5

# 任务匹配度低于这个值，就算有代码也不是同一件事，只能当组件借鉴。
TASK_FIT_REPRODUCE = 0.4
# 没有代码、但任务高度吻合时，值得当参考实现自己写一遍。
TASK_FIT_REFERENCE = 0.6

# 许可缺失或未声明的写法（GitHub 对没写许可的仓库返回 NOASSERTION）。
LICENSE_UNKNOWN = {None, "", "NOASSERTION", "noassertion"}


def _text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def papers_for_workspace(workspace: Path) -> dict[str, Any]:
    """读最近一次检索结果；没有就返回空结构而不是抛错（界面首屏就是这种情况）。"""
    path = workspace / PAPERS_FILE
    if not path.exists():
        return {"query": None, "searched_at": None, "sources": [], "records": [], "provider_failures": {}}
    payload = read_json(path)
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    return payload


def decisions_map(workspace: Path) -> dict[str, dict[str, Any]]:
    """读取舍记录：`paper_id` → `{decision, note, decided_at}`。"""
    path = workspace / DECISIONS_FILE
    if not path.exists():
        return {}
    payload = read_json(path)
    entries = payload.get("decisions")
    return entries if isinstance(entries, dict) else {}


def record_decision(workspace: Path, paper_id: str, decision: str, note: str = "") -> dict[str, Any]:
    """记下一条候选的取舍。

    只允许在检索结果里出现过的 `paper_id`：否则一次笔误就会在工作区里留下
    一条永远对不上任何论文的「调研」，界面之后再也没法把它清掉。
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    known = {str(record.get("paper_id")) for record in papers_for_workspace(workspace)["records"]}
    if paper_id not in known:
        raise ValueError(f"Unknown research record: {paper_id}")

    decisions = decisions_map(workspace)
    if decision == "undecided":
        # 「未决」等于没记过，直接删掉这条，别留下一个等价于空的记录。
        decisions.pop(paper_id, None)
    else:
        decisions[paper_id] = {"decision": decision, "note": note.strip(), "decided_at": utc_now()}
    write_json_atomic(workspace / DECISIONS_FILE, {"updated_at": utc_now(), "decisions": decisions})
    return {
        "paper_id": paper_id,
        "decision": decision,
        "decided_at": decisions.get(paper_id, {}).get("decided_at"),
        "counts": decision_counts(decisions),
    }


def decision_counts(decisions: dict[str, dict[str, Any]]) -> dict[str, int]:
    """每一档各几条，给界面顶上的「已调研 N / 已舍弃 M」用。"""
    counts = {name: 0 for name in DECISIONS}
    for entry in decisions.values():
        choice = str(entry.get("decision") or "undecided")
        counts[choice] = counts.get(choice, 0) + 1
    return counts


def find_code_candidates(
    record: dict[str, Any],
    *,
    fetcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """用论文标题去 GitHub 找可能的实现仓库。

    这一步是必要的：arXiv / OpenAlex / Semantic Scholar 的记录里 `code_url` 恒为空，
    只有 GitHub 源才有值。不主动找一次，「这篇有没有开源代码」这个问题就只能答「不知道」。

    返回 `status`：`found` / `none_found` / `lookup_failed`。第三种要和第二种分开 ——
    网络不通不代表这篇工作没有代码。

    `fetcher` 默认取模块级的 `search_github`（不是默认参数），这样测试可以替换它。
    """
    title = str(record.get("title") or "").strip()
    if not title:
        return {"status": "none_found", "candidates": [], "reason": "record has no title to search with"}
    terms = query_terms(title)
    if not terms:
        return {"status": "none_found", "candidates": [], "reason": "title has no meaningful search terms"}
    try:
        results = (fetcher or search_github)(title, CODE_CANDIDATE_LIMIT)
    except Exception as exc:  # 网络/限流都算「没查成」，不能算「没有」
        return {"status": "lookup_failed", "candidates": [], "reason": f"{type(exc).__name__}: {exc}"}

    candidates: list[dict[str, Any]] = []
    for item in results:
        body = f"{_text(item.get('title'))} {_text(item.get('abstract'))}"
        overlap = round(sum(1 for term in terms if term in body) / len(terms), 3)
        if overlap < CODE_TITLE_OVERLAP:
            continue
        candidates.append(
            {
                "repository": item.get("title"),
                "url": item.get("url"),
                "clone_url": item.get("code_url"),
                "license": item.get("license"),
                "stars": item.get("stars"),
                "title_overlap": overlap,
            }
        )
    candidates.sort(key=lambda item: (item["title_overlap"], item.get("stars") or 0), reverse=True)
    return {"status": "found" if candidates else "none_found", "candidates": candidates}


def _signal(key: str, tone: str, detail: str) -> dict[str, str]:
    return {"key": key, "tone": tone, "detail": detail}


def _code_signals(record: dict[str, Any], lookup: dict[str, Any]) -> tuple[list[dict[str, str]], bool]:
    """代码这一项的结论与证据。

    `code_url` 只有 GitHub 源的记录才有，所以先看它，没有再去看主动搜出来的候选仓库。
    """
    if record.get("code_url"):
        return [_signal("code_in_record", "ok", str(record["code_url"]))], True
    if lookup["status"] == "found":
        best = lookup["candidates"][0]
        return [_signal("code_found_by_title", "ok", f"{best['repository']} · overlap {best['title_overlap']}")], True
    if lookup["status"] == "lookup_failed":
        # 查不动 ≠ 没有：这条必须显式标出来，否则会被读成「这篇工作没开源」。
        return [_signal("code_lookup_failed", "muted", str(lookup.get("reason") or ""))], False
    return [_signal("code_none_found", "warn", "searched GitHub by title, nothing matched")], False


def _license_signals(record: dict[str, Any], lookup: dict[str, Any]) -> list[dict[str, str]]:
    """许可：能不能拿来用，是复现建议里绕不开的一项。

    记录里没写许可时，退回看代码候选仓库声明的许可 —— 同一份工作的许可多半是这个。
    """
    license_name = record.get("license")
    if license_name in LICENSE_UNKNOWN and lookup["candidates"]:
        license_name = lookup["candidates"][0].get("license")
    if license_name in LICENSE_UNKNOWN:
        return [_signal("license_unknown", "warn", "no licence declared in the record")]
    return [_signal("license_declared", "ok", str(license_name))]


def _task_signals(record: dict[str, Any]) -> list[dict[str, str]]:
    """任务匹配度：来自打分的 `relevance_parts.task`，不是另算一套。"""
    parts = record.get("relevance_parts") if isinstance(record.get("relevance_parts"), dict) else {}
    fit = parts.get("task")
    if fit is None:
        return [_signal("task_fit_unknown", "muted", "no competition spec to compare against")]
    value = float(fit)
    tone = "ok" if value >= TASK_FIT_REFERENCE else ("warn" if value >= TASK_FIT_REPRODUCE else "danger")
    return [_signal("task_fit", tone, f"{value:.2f}")]


def _evidence_signals(record: dict[str, Any]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = [
        _signal(
            "official_code_marked" if record.get("official_code") else "official_code_unmarked",
            "ok" if record.get("official_code") else "muted",
            "no provider marks authorship, so 官方实现 cannot be proven from the search record",
        )
    ]
    year = record.get("year")
    if isinstance(year, int) and year > 1900:
        signals.append(_signal("year_known", "ok", str(year)))
    else:
        signals.append(_signal("year_unknown", "muted", "provider returned no year"))
    venue = str(record.get("venue") or "").strip()
    signals.append(_signal("venue_known", "ok", venue) if venue else _signal("venue_unknown", "muted", "no venue"))
    return signals


def decide_verdict(task_fit: float | None, has_code: bool) -> str:
    """把证据折成一个结论。规则写在一处，界面只负责翻译这个枚举。

    * `reproduce` -- 有代码、任务也吻合：值得按它的方法跑一遍。
    * `adapt_component` -- 有代码但不是同一件事：只借鉴其中可复用的部分。
    * `reference_only` -- 没代码但任务高度吻合：值得读，实现得自己写。
    * `skip` -- 既没代码任务也不吻合：不投入。
    """
    fit = float(task_fit) if task_fit is not None else 0.0
    if has_code and fit >= TASK_FIT_REPRODUCE:
        return "reproduce"
    if has_code:
        return "adapt_component"
    if fit >= TASK_FIT_REFERENCE:
        return "reference_only"
    return "skip"


def assess_candidate(
    workspace: Path,
    record: dict[str, Any],
    *,
    lookup_code: bool = True,
    fetcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """对一条候选做价值评判，并把结论写进 `research/candidate_assessments.json`。"""
    lookup = (
        find_code_candidates(record, fetcher=fetcher)
        if lookup_code and not record.get("code_url")
        else {"status": "skipped", "candidates": [], "reason": "record already carries a code URL"}
    )
    code_signals, has_code = _code_signals(record, lookup)
    signals = code_signals + _license_signals(record, lookup) + _task_signals(record) + _evidence_signals(record)
    parts = record.get("relevance_parts") if isinstance(record.get("relevance_parts"), dict) else {}
    verdict = decide_verdict(parts.get("task"), has_code)

    assessment = {
        "paper_id": record.get("paper_id"),
        "title": record.get("title"),
        "source": record.get("source"),
        "assessed_at": utc_now(),
        "verdict": verdict,
        "worth_reproducing": verdict == "reproduce",
        "has_public_code": has_code,
        "has_official_code": bool(record.get("official_code")),
        "code_lookup": lookup["status"],
        "code_candidates": lookup["candidates"],
        "task_fit": parts.get("task"),
        "relevance_score": record.get("relevance_score"),
        "signals": signals,
    }

    path = workspace / ASSESSMENTS_FILE
    existing = read_json(path).get("assessments") if path.exists() else {}
    assessments = existing if isinstance(existing, dict) else {}
    assessments[str(record.get("paper_id"))] = assessment
    write_json_atomic(path, {"updated_at": utc_now(), "assessments": assessments})
    return assessment


def assessments_map(workspace: Path) -> dict[str, dict[str, Any]]:
    path = workspace / ASSESSMENTS_FILE
    if not path.exists():
        return {}
    payload = read_json(path)
    entries = payload.get("assessments")
    return entries if isinstance(entries, dict) else {}


def assess_investigated(
    workspace: Path,
    *,
    paper_ids: list[str] | None = None,
    lookup_code: bool = True,
    fetcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """对「已选调研」的候选做评判。

    不传 `paper_ids` 就按取舍记录来：只评判 `investigate` 的那些。已舍弃的不评判 ——
    评判要花一次 GitHub 查询，对已经决定不看的东西不值得花。
    """
    papers = papers_for_workspace(workspace)
    decisions = decisions_map(workspace)
    records = {str(record.get("paper_id")): record for record in papers["records"]}

    if paper_ids is None:
        targets = [pid for pid, entry in decisions.items() if entry.get("decision") == "investigate"]
    else:
        targets = paper_ids

    results: list[dict[str, Any]] = []
    skipped: list[str] = []
    for paper_id in targets:
        record = records.get(paper_id)
        if record is None:
            skipped.append(paper_id)
            continue
        results.append(assess_candidate(workspace, record, lookup_code=lookup_code, fetcher=fetcher))

    verdicts: dict[str, int] = {}
    for item in results:
        verdicts[item["verdict"]] = verdicts.get(item["verdict"], 0) + 1
    return {"assessed": len(results), "skipped": skipped, "verdicts": verdicts, "assessments": results}


def candidates_for_workspace(workspace: Path) -> dict[str, Any]:
    """检索结果 + 取舍 + 评判合成一份候选视图，界面只读这一个接口。

    计数只算**当前检索结果里**的候选：重跑检索换掉一批记录之后，旧记录上的取舍仍在
    文件里留着（人做过的事不抹掉），但不能再算进「已调研 N」里，否则顶上的数字会和
    下面看得见的清单对不上。
    """
    papers = papers_for_workspace(workspace)
    stored = decisions_map(workspace)
    assessments = assessments_map(workspace)
    records: list[dict[str, Any]] = []
    live_decisions: dict[str, dict[str, Any]] = {}
    live_assessed: int = 0
    for record in papers["records"]:
        paper_id = str(record.get("paper_id"))
        decision = stored.get(paper_id, {})
        if decision:
            live_decisions[paper_id] = decision
        assessment = assessments.get(paper_id)
        if assessment:
            live_assessed += 1
        records.append(
            {
                **record,
                "decision": decision.get("decision", "undecided"),
                "decision_note": decision.get("note", ""),
                "decided_at": decision.get("decided_at"),
                "assessment": assessment,
            }
        )
    return {
        "query": papers.get("query"),
        "searched_at": papers.get("searched_at"),
        "sources": papers.get("sources", []),
        "provider_failures": papers.get("provider_failures", {}),
        "counts": {
            "records": len(records),
            **decision_counts(live_decisions),
            "assessed": live_assessed,
        },
        "records": records,
    }
