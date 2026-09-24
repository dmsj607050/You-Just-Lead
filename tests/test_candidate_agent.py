"""Tests for literature triage (investigate/discard) and candidate value assessment."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.candidate_agent import (
    assess_candidate,
    assess_investigated,
    candidates_for_workspace,
    decide_verdict,
    record_decision,
)
from agents.research_agent import build_research_query, score_record, spec_terms
from app.api_server import CompetitionApiHandler
from tools.files import read_json, write_json_atomic


MULTIMODAL_SPEC = {
    "competition": {"name": "Urban multimodal detection", "task_type": "object_detection"},
    "evaluation": {"primary_metric": "mAP@50-95", "direction": "maximize"},
    "data": {"modalities": ["visible_rgb", "infrared", "depth"], "class_count": 12},
}


def _record(paper_id: str, title: str, **overrides: object) -> dict:
    record = {
        "paper_id": paper_id,
        "source": "arxiv",
        "title": title,
        "year": 2025,
        "venue": "CVPR",
        "authors": [],
        "abstract": None,
        "url": f"https://example.test/{paper_id}",
        "code_url": None,
        "pdf_url": None,
        "official_code": False,
        "license": None,
        "stars": None,
        "relevance_score": 0.5,
        "relevance_parts": {"terms": 0.5, "task": 0.5, "code": 0.0, "recency": 0.8},
        "reproduction_priority": 0.3,
    }
    record.update(overrides)
    return record


def _repo(name: str, description: str, **overrides: object) -> dict:
    """一条 GitHub 检索结果（形状与 `search_github` 的返回一致）。"""
    repo = {
        "paper_id": f"github:{name}",
        "source": "github",
        "title": name,
        "abstract": description,
        "url": f"https://github.com/{name}",
        "code_url": f"https://github.com/{name}.git",
        "license": "MIT",
        "stars": 120,
        "year": 2024,
    }
    repo.update(overrides)
    return repo


def _workspace_with_records(root: Path, records: list[dict]) -> Path:
    workspace = root / "workspace" / "current"
    workspace.mkdir(parents=True)
    write_json_atomic(
        workspace / "research" / "papers.json",
        {
            "query": "object detection rgb infrared depth",
            "searched_at": "2026-09-24T00:00:00+00:00",
            "sources": ["arxiv"],
            "records": records,
            "provider_failures": {},
        },
    )
    return workspace


class SpecQueryTests(unittest.TestCase):
    def test_query_is_built_from_task_and_modalities(self) -> None:
        """检索式来自规格里的任务与模态，而不是让人自己编检索词。"""
        self.assertEqual(build_research_query(MULTIMODAL_SPEC), "object detection rgb infrared depth")

    def test_query_terms_are_capped(self) -> None:
        """provider 侧是 AND 查询，词太多会一条都命中不到。"""
        self.assertLessEqual(len(build_research_query(MULTIMODAL_SPEC).split()), 5)

    def test_query_is_empty_without_usable_spec_fields(self) -> None:
        """规格里没有任务类型与模态时，宁可为空也不要瞎拼一条。"""
        self.assertEqual(build_research_query({"competition": {"name": "只写了名字"}}), "")

    def test_spec_terms_split_task_modality_metric(self) -> None:
        groups = spec_terms(MULTIMODAL_SPEC)
        self.assertIn("object detection", groups["task"])
        self.assertIn("multimodal", groups["modality"])
        self.assertIn("mean average precision", groups["metric"])


class ScoringTests(unittest.TestCase):
    def test_title_hits_beat_abstract_hits(self) -> None:
        """标题里写着查询词的论文，分数要高于只在摘要里顺带提到的。"""
        groups = spec_terms(MULTIMODAL_SPEC)
        terms = ["object", "detection", "rgb"]
        on_title = score_record(_record("a", "RGB object detection for driving"), terms, groups, this_year=2026)
        on_abstract = score_record(
            _record("b", "A study of sensor rigs", abstract="we compare rgb object detection baselines"),
            terms,
            groups,
            this_year=2026,
        )
        self.assertGreater(on_title["relevance_score"], on_abstract["relevance_score"])

    def test_score_does_not_depend_on_list_position(self) -> None:
        """同样的记录算几次都一样 —— 旧实现是按列表位次衰减的假系数。"""
        groups = spec_terms(MULTIMODAL_SPEC)
        record = _record("a", "RGB infrared depth object detection fusion")
        first = score_record(dict(record), ["object", "detection"], groups, this_year=2026)
        second = score_record(dict(record), ["object", "detection"], groups, this_year=2026)
        self.assertEqual(first["relevance_score"], second["relevance_score"])

    def test_parts_are_reported_and_missing_parts_drop_out(self) -> None:
        """每个分量都单独给出；算不出来的是 None，并在权重里剔除。"""
        # 空规格：任务词与指标词都没有，年份也缺 —— 这两项该是 None 而不是 0 或中性分。
        empty_groups = spec_terms({})
        scored = score_record(_record("a", "RGB object detection", year=None), ["object"], empty_groups, this_year=2026)
        self.assertIsNone(scored["relevance_parts"]["task"])
        self.assertIsNone(scored["relevance_parts"]["recency"])
        self.assertEqual(scored["relevance_parts"]["code"], 0.0)
        self.assertGreater(scored["relevance_score"], 0.0)

    def test_code_url_raises_the_priority(self) -> None:
        groups = spec_terms(MULTIMODAL_SPEC)
        without = score_record(_record("a", "RGB object detection"), ["object"], groups, this_year=2026)
        with_code = score_record(
            _record("b", "RGB object detection", code_url="https://github.com/example/det.git"),
            ["object"],
            groups,
            this_year=2026,
        )
        self.assertGreater(with_code["reproduction_priority"], without["reproduction_priority"])


class DecisionTests(unittest.TestCase):
    def test_decision_is_persisted_next_to_the_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "Fusion detector")])
            outcome = record_decision(workspace, "arxiv:1", "investigate", "worth a look")

            stored = read_json(workspace / "research" / "candidate_decisions.json")
            self.assertEqual(stored["decisions"]["arxiv:1"]["decision"], "investigate")
            self.assertEqual(outcome["counts"]["investigate"], 1)

    def test_running_the_search_again_keeps_human_decisions(self) -> None:
        """重跑检索只换 papers.json，人的取舍不在里面，所以不会被覆盖。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "Fusion detector")])
            record_decision(workspace, "arxiv:1", "discard")

            write_json_atomic(
                workspace / "research" / "papers.json",
                {"query": "q", "records": [_record("arxiv:1", "Fusion detector")], "provider_failures": {}},
            )
            merged = candidates_for_workspace(workspace)
            self.assertEqual(merged["records"][0]["decision"], "discard")

    def test_undecided_clears_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "Fusion detector")])
            record_decision(workspace, "arxiv:1", "investigate")
            record_decision(workspace, "arxiv:1", "undecided")

            stored = read_json(workspace / "research" / "candidate_decisions.json")
            self.assertEqual(stored["decisions"], {})

    def test_counts_ignore_decisions_on_records_that_left_the_search(self) -> None:
        """重跑检索换掉一批记录后，旧记录上的取舍仍留着，但不再算进顶上的计数。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(
                Path(temporary),
                [_record("arxiv:1", "Kept paper"), _record("arxiv:2", "Dropped by re-search")],
            )
            record_decision(workspace, "arxiv:1", "investigate")
            record_decision(workspace, "arxiv:2", "discard")

            write_json_atomic(
                workspace / "research" / "papers.json",
                {"query": "q", "records": [_record("arxiv:1", "Kept paper")], "provider_failures": {}},
            )
            merged = candidates_for_workspace(workspace)
            stored = read_json(workspace / "research" / "candidate_decisions.json")

            self.assertEqual(merged["counts"]["investigate"], 1)
            self.assertEqual(merged["counts"]["discard"], 0)
            # 记录还在文件里：人做过的决定不因为一次检索被抹掉。
            self.assertIn("arxiv:2", stored["decisions"])

    def test_unknown_or_invalid_decision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "Fusion detector")])
            with self.assertRaises(ValueError):
                record_decision(workspace, "arxiv:missing", "investigate")
            with self.assertRaises(ValueError):
                record_decision(workspace, "arxiv:1", "maybe")


class VerdictTests(unittest.TestCase):
    def test_verdict_ladder(self) -> None:
        self.assertEqual(decide_verdict(0.8, True), "reproduce")
        self.assertEqual(decide_verdict(0.1, True), "adapt_component")
        self.assertEqual(decide_verdict(0.8, False), "reference_only")
        self.assertEqual(decide_verdict(0.1, False), "skip")

    def test_verdict_without_task_fit_does_not_assume_relevance(self) -> None:
        """没有规格可比时 task_fit 是 None，不能当成「很吻合」。"""
        self.assertEqual(decide_verdict(None, True), "adapt_component")
        self.assertEqual(decide_verdict(None, False), "skip")


class AssessmentTests(unittest.TestCase):
    def test_code_found_by_title_becomes_public_code(self) -> None:
        """arXiv 记录里 code_url 恒为空，靠标题去 GitHub 找实现仓库来回答「有没有代码」。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(
                Path(temporary), [_record("arxiv:1", "RGB infrared depth fusion object detection")]
            )
            record = candidates_for_workspace(workspace)["records"][0]
            repos = [_repo("example/fusion-detector", "rgb infrared depth fusion object detection")]
            assessment = assess_candidate(workspace, record, fetcher=lambda query, limit: repos)

            self.assertTrue(assessment["has_public_code"])
            self.assertEqual(assessment["code_lookup"], "found")
            self.assertEqual(assessment["verdict"], "reproduce")
            self.assertTrue(assessment["worth_reproducing"])
            self.assertEqual(assessment["code_candidates"][0]["repository"], "example/fusion-detector")

    def test_unrelated_repository_is_not_counted_as_the_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "RGB infrared depth fusion")])
            record = candidates_for_workspace(workspace)["records"][0]
            assessment = assess_candidate(
                workspace,
                record,
                fetcher=lambda query, limit: [_repo("someone/unrelated-map-viewer", "a tile map viewer")],
            )

            self.assertFalse(assessment["has_public_code"])
            self.assertEqual(assessment["code_lookup"], "none_found")

    def test_lookup_failure_is_reported_as_unknown_not_absent(self) -> None:
        """查不动 ≠ 没开源：这条必须显式区分，否则会被读成「这篇没代码」。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "RGB depth fusion")])
            record = candidates_for_workspace(workspace)["records"][0]
            assessment = assess_candidate(
                workspace,
                record,
                fetcher=lambda query, limit: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
            )

            self.assertEqual(assessment["code_lookup"], "lookup_failed")
            self.assertIn("code_lookup_failed", [signal["key"] for signal in assessment["signals"]])

    def test_record_with_code_url_skips_the_lookup(self) -> None:
        """记录本身就带仓库时不再打一次 GitHub。"""
        calls: list[str] = []

        def fetcher(query: str, limit: int) -> list[dict]:
            calls.append(query)
            return []

        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(
                Path(temporary),
                [_record("github:example/det", "Example detector", code_url="https://github.com/example/det.git")],
            )
            record = candidates_for_workspace(workspace)["records"][0]
            assessment = assess_candidate(workspace, record, fetcher=fetcher)

            self.assertEqual(calls, [])
            self.assertTrue(assessment["has_public_code"])

    def test_only_investigated_candidates_are_assessed(self) -> None:
        """评判要为每条打一次 GitHub，已舍弃的不值得花。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(
                Path(temporary),
                [_record("arxiv:1", "Kept paper"), _record("arxiv:2", "Dropped paper")],
            )
            record_decision(workspace, "arxiv:1", "investigate")
            record_decision(workspace, "arxiv:2", "discard")

            outcome = assess_investigated(workspace, fetcher=lambda query, limit: [])
            self.assertEqual(outcome["assessed"], 1)
            self.assertEqual(outcome["assessments"][0]["paper_id"], "arxiv:1")

    def test_assessment_is_merged_into_the_candidate_view(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = _workspace_with_records(Path(temporary), [_record("arxiv:1", "Depth fusion detector")])
            record_decision(workspace, "arxiv:1", "investigate")
            assess_investigated(workspace, fetcher=lambda query, limit: [])

            merged = candidates_for_workspace(workspace)
            self.assertEqual(merged["counts"]["assessed"], 1)
            self.assertEqual(merged["records"][0]["assessment"]["paper_id"], "arxiv:1")


class ResearchApiTests(unittest.TestCase):
    """取舍与评判两个接口走真实的 HTTP 路径。"""

    def _serve(self, root: Path, workspace: Path):
        handler = type("TestCandidateApiHandler", (CompetitionApiHandler,), {"project_root": root, "workspace": workspace})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _post(self, base: str, path: str, payload: dict) -> dict:
        request = Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def test_decide_then_assess_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_records(root, [_record("arxiv:1", "RGB depth fusion object detection")])
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with patch("agents.candidate_agent.search_github", lambda query, limit: []):
                    decided = self._post(base, "/api/research/decide", {"paper_id": "arxiv:1", "decision": "investigate"})
                    assessed = self._post(base, "/api/research/assess", {})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(decided["counts"]["investigate"], 1)
            self.assertEqual(decided["records"][0]["decision"], "investigate")
            self.assertEqual(assessed["counts"]["assessed"], 1)
            self.assertEqual(assessed["records"][0]["assessment"]["paper_id"], "arxiv:1")

    def test_decide_rejects_an_unknown_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_records(root, [_record("arxiv:1", "Kept paper")])
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as raised:
                    self._post(base, "/api/research/decide", {"paper_id": "arxiv:nope", "decision": "investigate"})
                body = raised.exception.read().decode("utf-8")
                status = raised.exception.code
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(status, 400)
            self.assertIn("Unknown research record", body)


if __name__ == "__main__":
    unittest.main()
