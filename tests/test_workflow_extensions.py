"""Tests for persisted research, approval and paper-generation workflows."""

from __future__ import annotations

import tempfile
import threading
import unittest
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.api_server import CompetitionApiHandler
from app.orchestrator.workflow import workflow_state
from agents.materials_agent import intake_selected_materials
from database.ledger import ledger_path
from training.catalog import recommend_runner
from agents.reproduction_agent import intake_repository
from agents.research_agent import search_research
from agents.strategy_agent import recommend_next_actions
from paper.generator import generate_paper_package
from tools.configuration import load_yaml, write_yaml
from tools.files import read_json, write_json_atomic
from tools.submission import validate_submission


def _approved_spec(name: str, task_type: str, metric: str) -> dict:
    """Minimal complete rule record for workflows that are not rule-gate tests."""
    fields = {
        "competition.name": "official section: competition overview",
        "competition.platform": "official section: platform",
        "competition.task_type": "official section: task",
        "competition.deadline": "official section: schedule",
        "evaluation.primary_metric": "official section: evaluation",
        "evaluation.direction": "official section: evaluation direction",
        "submission.format": "official section: submission",
        "submission.filename_rule": "official section: submission filename",
        "submission.daily_limit": "official section: submission quota",
        "constraints.model_size_limit_mb": "official section: runtime limits",
    }
    return {
        "competition": {"name": name, "platform": "Test Platform", "task_type": task_type, "deadline": "2026-12-31 23:59 UTC"},
        "evaluation": {"primary_metric": metric, "direction": "maximize"},
        "submission": {"format": "csv", "filename_rule": "submission.csv", "daily_limit": 3},
        "constraints": {"model_size_limit_mb": 100},
        "approval": {
            "requires_human_confirmation": False,
            "unresolved_questions": [],
            "official_evidence": {
                "source_type": "official_document",
                "source_locator": "https://example.test/rules",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "fields": fields,
            },
        },
    }


def _serve_workspace(root: Path, workspace: Path) -> tuple[ThreadingHTTPServer, str]:
    """起一个只注入 project_root/workspace 的接口服务，返回 (server, base_url)。"""
    handler = type("GateApiHandler", (CompetitionApiHandler,), {"project_root": root, "workspace": workspace})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _stop_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:  # nosec B310: local test server
        return json.loads(response.read())


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:  # nosec B310: local test server
        return json.loads(response.read())


def _post_status(url: str, payload: dict) -> int:
    try:
        _post_json(url, payload)
    except HTTPError as error:
        return int(error.code)
    raise AssertionError(f"Expected {url} to fail")


def _workspace_with_audited_experiment(root: Path, *, rules_approved: bool = True) -> Path:
    """一条已完成、且属于当前竞赛数据版本的实验，供人的关口测试使用。"""
    workspace = root / "workspace"
    raw_data_dir = workspace / "data" / "raw"
    raw_data_dir.mkdir(parents=True, exist_ok=True)
    (raw_data_dir / "train.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    inventory_sha = "a" * 64
    spec = _approved_spec("Gate Cup", "classification", "accuracy")
    spec["approval"]["requires_human_confirmation"] = not rules_approved
    write_yaml(workspace / "competition_spec.yaml", spec)
    write_json_atomic(workspace / "reports" / "data_statistics.json", {
        "file_count": 1,
        "issue_count": 0,
        "exact_duplicate_groups": [],
        "data_dir": str(raw_data_dir),
        "inventory_sha256": inventory_sha,
    })
    write_json_atomic(
        workspace / "experiments" / "manifests" / "EXP-0001.json",
        {
            "experiment_id": "EXP-0001",
            "change_type": "baseline",
            "config": {
                "training": {"runner": "tabular_classification"},
                "data": {"version": inventory_sha, "train_csv": str(raw_data_dir / "train.csv")},
            },
        },
    )
    write_json_atomic(
        workspace / "experiments" / "results" / "EXP-0001.json",
        {"experiment_id": "EXP-0001", "status": "completed", "validation_metric": 0.8},
    )
    return workspace


class WorkflowExtensionTests(unittest.TestCase):
    def test_task_catalog_recommends_only_supported_runner(self) -> None:
        self.assertEqual(recommend_runner("semantic segmentation")["runner"], "image_segmentation")
        self.assertEqual(recommend_runner("image classification")["runner"], "image_classification")
        self.assertEqual(recommend_runner("regression")["runner"], "tabular_regression")
        self.assertIsNone(recommend_runner("object detection"))

    def test_submission_validation_requires_approved_rules_and_checks_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            spec = _approved_spec("Submission Cup", "classification", "accuracy")
            spec["submission"].update({"required_columns": ["id", "prediction"], "id_column": "id", "expected_rows": 2})
            write_yaml(workspace / "competition_spec.yaml", spec)
            candidate = workspace / "submissions" / "candidate.csv"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("id,prediction\nA,0\nB,1\n", encoding="utf-8")

            outcome = validate_submission(workspace, candidate)

            self.assertEqual(outcome["status"], "passed")
            self.assertTrue(outcome["manual_upload_required"])
            self.assertTrue((workspace / "submissions" / "validation" / "candidate.json").exists())

    def test_local_api_reads_dashboard_and_creates_auditable_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            write_yaml(workspace / "competition_spec.yaml", _approved_spec("API Cup", "classification", "accuracy"))
            handler = type(
                "TestApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/dashboard", timeout=5) as response:  # nosec B310: local test server
                    dashboard = json.loads(response.read())
                with urlopen(base + "/api/workflow", timeout=5) as response:  # nosec B310: local test server
                    workflow = json.loads(response.read())
                with urlopen(base + "/api/capabilities", timeout=5) as response:  # nosec B310: local test server
                    capabilities = json.loads(response.read())
                request = Request(
                    base + "/api/experiments/drafts",
                    data=json.dumps({"hypothesis": "Use focal loss to improve rare-class recall."}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                    draft = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(dashboard["competition"]["name"], "API Cup")
            self.assertEqual(workflow["stage"], "data_audit")
            self.assertTrue(any(item["runner"] == "tabular_classification" for item in capabilities["runners"]))
            self.assertEqual(draft["status"], "awaiting_human_approval")
            self.assertTrue((workspace / "experiments" / "drafts" / "DRAFT-0001.json").exists())

    def test_paper_endpoint_reports_existing_package_without_writing(self) -> None:
        """GET /api/paper 只读报告已有证据包；包还没生成时也不能落任何文件。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            write_yaml(workspace / "competition_spec.yaml", _approved_spec("Paper Cup", "segmentation", "iou"))
            package_dir = root / "paper" / "generated"
            handler = type(
                "TestPaperApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/paper", timeout=5) as response:  # nosec B310: local test server
                    missing = json.loads(response.read())
                self.assertFalse(package_dir.exists())

                generate_paper_package(workspace, package_dir)

                with urlopen(base + "/api/paper", timeout=5) as response:  # nosec B310: local test server
                    generated = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertFalse(missing["available"])
            self.assertEqual(missing["sections"], [])
            self.assertEqual(missing["claims"], [])
            self.assertEqual(missing["submission"]["format"], "csv")
            self.assertEqual(missing["submission"]["daily_limit"], 3)

            self.assertTrue(generated["available"])
            self.assertIn("Scope and compliance", generated["sections"])
            self.assertEqual(generated["bib_entries"], 0)
            self.assertTrue(str(generated["tex_path"]).endswith("competition_report.tex"))
            self.assertTrue(Path(generated["evidence_path"]).exists())

    def test_trace_endpoint_reports_four_read_only_chains(self) -> None:
        """GET /api/trace 汇总四条溯源链，且一次 GET 不落任何文件。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_audited_experiment(root, rules_approved=False)
            # 讯飞档案口径：19 个必备字段，其中 10 个带锚点（上面 helper 写的），9 个缺锚点。
            spec = _approved_spec("Trace Cup", "image_segmentation", "global_water_iou")
            spec["submission"]["validation_profile"] = "xunfei_waterseg_inference_package"
            spec["approval"]["requires_human_confirmation"] = True
            write_yaml(workspace / "competition_spec.yaml", spec)

            (workspace / "docs").mkdir(parents=True, exist_ok=True)
            (workspace / "docs" / "rule_dossier.md").write_text("# 规则档案\n", encoding="utf-8")
            write_json_atomic(workspace / "research" / "papers.json", {
                "query": "water segmentation",
                "searched_at": "2026-01-02T00:00:00+00:00",
                "provider_failures": {"openalex": "HTTPError: HTTP Error 503"},
                "records": [{
                    "paper_id": "arxiv:1",
                    "title": "A segmentation paper",
                    "url": "http://arxiv.org/abs/1",
                    "source": "arxiv",
                    "year": 2026,
                }],
            })
            # 第二条是 synthetic：必须被判为不在当前审计范围内，并给出可核对的原因。
            write_json_atomic(workspace / "experiments" / "manifests" / "EXP-0002.json", {
                "experiment_id": "EXP-0002",
                "change_type": "baseline",
                "config": {
                    "training": {"runner": "synthetic_binary_classification"},
                    "data": {"version": "synthetic-v1"},
                },
            })
            write_json_atomic(workspace / "experiments" / "results" / "EXP-0002.json", {
                "experiment_id": "EXP-0002",
                "status": "completed",
                "validation_metric": 0.5,
                "artifact_paths": [str(workspace / "experiments" / "artifacts" / "EXP-0002" / "model.pt")],
            })

            def snapshot() -> list[str]:
                return sorted(
                    path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
                )

            before = snapshot()
            server, base = _serve_workspace(root, workspace)
            try:
                trace = _get_json(base + "/api/trace")
            finally:
                _stop_server(server)

            self.assertEqual(before, snapshot())

            # 规则链：值有、锚点缺，缺口数量与逐字段标记一致。
            rule = trace["rule"]
            self.assertEqual(rule["profile"], "xunfei_waterseg")
            self.assertFalse(rule["ready"])
            self.assertFalse(rule["approved"])
            self.assertGreater(rule["required_field_count"], 0)
            self.assertGreater(rule["missing_anchor_count"], 0)
            self.assertEqual(rule["missing_anchor_count"], rule["gap_count"] - rule["missing_value_count"] - 1)
            self.assertEqual(rule["missing_value_count"], rule["required_field_count"] - 10)
            self.assertEqual(rule["fields"][0]["field"], "competition.name")
            self.assertTrue(rule["fields"][0]["has_anchor"])
            self.assertEqual(
                rule["missing_anchor_count"],
                len([item for item in rule["fields"] if not item["has_anchor"]]),
            )
            self.assertIsNone([item for item in rule["fields"] if not item["has_anchor"]][0]["anchor"])
            self.assertEqual(rule["documents"][0]["name"], "rule_dossier.md")

            # 数据链：一条在审计范围内，synthetic 那条被排除且原因可核对。
            scope = {item["experiment_id"]: item for item in trace["data"]["experiments"]}
            self.assertTrue(scope["EXP-0001"]["in_scope"])
            self.assertIsNone(scope["EXP-0001"]["exclusion"])
            self.assertEqual(scope["EXP-0002"]["exclusion"], "synthetic_runner")

            # 实验链：产物不存在必须如实标出，不能因为「跑完了」就算有证据。
            experiments = {item["experiment_id"]: item for item in trace["experiments"]["experiments"]}
            self.assertFalse(experiments["EXP-0002"]["in_scope"])
            self.assertFalse(experiments["EXP-0002"]["artifacts"][0]["exists"])
            self.assertEqual(trace["experiments"]["artifact_missing_count"], 1)

            # 文献链与论文终点：检索失败也要上报，包没生成时 claims 为空。
            self.assertEqual(trace["research"]["record_count"], 1)
            self.assertEqual(trace["research"]["provider_failures"]["openalex"], "HTTPError: HTTP Error 503")
            self.assertFalse(trace["paper"]["available"])
            self.assertEqual(trace["paper"]["claims"], [])

    def test_rule_evidence_endpoints_record_anchors_without_approving(self) -> None:
        """GET/POST /api/rules/evidence：录入官方锚点，但录入不等于批准规则。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            spec = _approved_spec("Evidence Cup", "image_segmentation", "global_water_iou")
            spec["submission"]["validation_profile"] = "xunfei_waterseg_inference_package"
            spec["submission"]["contract"] = {
                "package_layout": "one top-level directory containing run.py and model/",
                "required_files": ["run.py", "model/model.ts"],
                "mask_size": [1024, 1024],
                "mask_filename_suffix": "_mask",
            }
            # 锚点清空：19 个必备字段全缺锚点，其中 5 个连值也没确认（与真实项目同形）。
            spec["approval"]["official_evidence"]["fields"] = {}
            spec["approval"]["unresolved_questions"] = []
            write_yaml(workspace / "competition_spec.yaml", spec)

            server, base = _serve_workspace(root, workspace)
            try:
                form = _get_json(base + "/api/rules/evidence")
            finally:
                _stop_server(server)

            self.assertTrue(form["supported"])
            self.assertEqual(form["profile"], "xunfei_waterseg")
            self.assertEqual(form["required_field_count"], 19)
            self.assertEqual(form["missing_anchor_count"], 19)
            self.assertEqual(form["missing_value_count"], 5)
            kinds = {item["field"]: item["kind"] for item in form["fields"]}
            self.assertEqual(kinds["constraints.external_data_allowed"], "boolean")
            self.assertEqual(kinds["submission.contract.runtime_output"], "runtime_output")
            self.assertEqual(kinds["submission.contract.mask_size"], "list")
            self.assertEqual(kinds["competition.name"], "text")

            payload = {
                "source_type": "authenticated_rule_page",
                "source_locator": "https://challenge.xfyun.cn/rules",
                "reviewed_at": "2026-09-20T10:00:00+08:00",
                "fields": [{"field": "competition.name", "anchor": "official section: overview"}],
            }
            spec_path = workspace / "competition_spec.yaml"
            before = spec_path.read_text(encoding="utf-8")

            # 只填了一个字段的锚点：必须在写盘前被拦下，且不留证据文件。
            server, base = _serve_workspace(root, workspace)
            try:
                self.assertEqual(_post_status(base + "/api/rules/evidence", payload), 400)
            finally:
                _stop_server(server)
            self.assertEqual(spec_path.read_text(encoding="utf-8"), before)
            self.assertEqual(
                sorted(path.name for path in (workspace / "docs").glob("rule_evidence_*.yaml")),
                [],
            )

            # 补齐 19 个字段：值沿用规格、缺的 5 个由界面按类型补上。
            entries = []
            for index, item in enumerate(form["fields"]):
                entry = {"field": item["field"], "anchor": f"official section {index + 1}"}
                if not item["has_value"]:
                    if item["kind"] == "boolean":
                        entry["value_flag"] = True
                    elif item["kind"] == "runtime_output":
                        entry["value_text"] = "loose_png"
                    else:
                        entry["value_text"] = f"recorded limit {index + 1}"
                entries.append(entry)
            payload["fields"] = entries

            server, base = _serve_workspace(root, workspace)
            try:
                outcome = _post_json(base + "/api/rules/evidence", payload)
                after = _get_json(base + "/api/rules/evidence")
                # 证据齐了，但批准仍要人单独走关口：先看此时规格仍要求人工确认。
                unapproved = load_yaml(spec_path)["approval"]
                approval = _post_json(base + "/api/rules/approve", {"note": "Reviewed the recorded anchors."})
            finally:
                _stop_server(server)

            self.assertTrue(outcome["requires_human_confirmation"])
            self.assertTrue(outcome["readiness"]["ready"])
            self.assertEqual(after["missing_anchor_count"], 0)
            self.assertEqual(after["missing_value_count"], 0)

            evidence_path = Path(outcome["evidence_path"])
            self.assertTrue(evidence_path.exists())
            self.assertEqual(evidence_path.parent, workspace / "docs")
            applied = unapproved["official_evidence"]
            self.assertEqual(applied["source_locator"], "https://challenge.xfyun.cn/rules")
            self.assertEqual(len(applied["fields"]), 19)
            self.assertEqual(len(applied["confirmation_file_sha256"]), 64)
            self.assertEqual(applied["confirmation_file"], str(evidence_path))
            self.assertTrue(unapproved["requires_human_confirmation"])

            # 关口随后可以正常通过：证据录入这一环真的解锁了规则确认。
            self.assertTrue(approval["approved"])

            # 事件必须落在**这个工作区对应的项目**名下（工作区目录名就是项目 id），
            # 而且别的项目看不到它。账本已按项目隔离，这条断言不能再无过滤地全表查。
            connection = sqlite3.connect(ledger_path(root))
            try:
                own = [
                    row[0]
                    for row in connection.execute(
                        "select event_type from workflow_events where project_id=?", ("current",)
                    )
                ]
                others = [
                    row[0]
                    for row in connection.execute(
                        "select event_type from workflow_events where project_id<>?", ("current",)
                    )
                ]
            finally:
                connection.close()
            self.assertIn("rules_evidence_applied", own)
            self.assertEqual(others, [])

    def test_draft_list_reports_recorded_drafts_newest_first(self) -> None:
        """GET /api/experiments/drafts 列出已登记的草案，最新的在前；未登记时为空。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            write_yaml(workspace / "competition_spec.yaml", _approved_spec("Draft Cup", "classification", "accuracy"))
            handler = type(
                "TestDraftApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/experiments/drafts", timeout=5) as response:  # nosec B310: local test server
                    empty = json.loads(response.read())

                for hypothesis in ("First recorded hypothesis.", "Second recorded hypothesis."):
                    request = Request(
                        base + "/api/experiments/drafts",
                        data=json.dumps({"hypothesis": hypothesis}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                        self.assertEqual(response.status, 201)

                with urlopen(base + "/api/experiments/drafts", timeout=5) as response:  # nosec B310: local test server
                    listed = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(empty["drafts"], [])
            self.assertEqual([item["draft_id"] for item in listed["drafts"]], ["DRAFT-0002", "DRAFT-0001"])
            self.assertEqual(listed["drafts"][0]["status"], "awaiting_human_approval")
            self.assertEqual(listed["drafts"][0]["hypothesis"], "Second recorded hypothesis.")
            self.assertFalse((root / "experiments" / "jobs").exists())

    def test_research_persists_multiple_sources_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace" / "current"
            fake_sources = {
                "arxiv": lambda query, limit: [{"paper_id": "arxiv:1", "source": "arxiv", "title": "Boundary loss supervision", "url": "https://arxiv.org/abs/1", "code_url": None}],
                "github": lambda query, limit: [{"paper_id": "github:repo", "source": "github", "title": "Boundary loss supervision code", "url": "https://github.com/example/repo", "code_url": "https://github.com/example/repo.git"}],
            }
            with patch("agents.research_agent.SOURCES", fake_sources):
                outcome = search_research(workspace, "boundary loss", sources=["arxiv", "github"], limit=3)

            payload = read_json(workspace / "research" / "papers.json")
            self.assertEqual(outcome["records"], 2)
            self.assertEqual(payload["query"], "boundary loss")
            self.assertTrue((workspace / "research" / "research_radar.md").exists())

    def test_reproduction_requires_approval_before_any_clone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            outcome = intake_repository(workspace, "https://github.com/example/repository.git")
            record = read_json(Path(outcome["record_path"]))

            self.assertEqual(outcome["status"], "awaiting_human_approval")
            self.assertFalse(record["approved"])
            self.assertFalse((workspace / "reproductions" / "sources").exists())

    def test_decision_queue_and_tex_are_grounded_in_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            raw_data_dir = workspace / "data" / "raw"
            raw_data_dir.mkdir(parents=True)
            (raw_data_dir / "train.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            inventory_sha = "a" * 64
            write_yaml(workspace / "competition_spec.yaml", _approved_spec("Demo Cup", "classification", "accuracy"))
            write_json_atomic(workspace / "reports" / "data_statistics.json", {
                "file_count": 12,
                "issue_count": 1,
                "exact_duplicate_groups": [],
                "data_dir": str(raw_data_dir),
                "inventory_sha256": inventory_sha,
            })
            write_json_atomic(
                workspace / "experiments" / "manifests" / "EXP-0001.json",
                {
                    "experiment_id": "EXP-0001",
                    "change_type": "baseline",
                    "config": {
                        "training": {"runner": "tabular_classification"},
                        "data": {"version": inventory_sha, "train_csv": str(raw_data_dir / "train.csv")},
                    },
                },
            )
            write_json_atomic(
                workspace / "experiments" / "results" / "EXP-0001.json",
                {
                    "experiment_id": "EXP-0001",
                    "status": "completed",
                    "validation_metric": 0.8,
                    "diagnosis": {"recommendations": ["Try one regularization change."]},
                    "error_analysis": {
                        "failure_modes": [
                            {
                                "kind": "class_recall_asymmetry",
                                "detail": "Class 'rare' recall is materially lower than the best observed class.",
                            }
                        ]
                    },
                },
            )
            plan = recommend_next_actions(workspace)
            package = generate_paper_package(workspace)

            tex = Path(package["tex_path"]).read_text(encoding="utf-8")
            evidence = read_json(Path(package["evidence_map"]))
            self.assertTrue(plan["actions"])
            self.assertTrue(plan["proposals"])
            self.assertEqual(plan["proposals"][0]["rank"], 1)
            self.assertIn("class_balancing", {item["change_type"] for item in plan["proposals"]})
            self.assertTrue((workspace / "experiments" / "proposals.json").exists())
            self.assertIn("EXP-0001", tex)
            self.assertIn("0.8", tex)
            self.assertNotIn("\\bibliography", tex)
            self.assertEqual(evidence["claims"][0]["experiment_id"], "EXP-0001")
            self.assertEqual(workflow_state(workspace)["stage"], "evidence_led_iteration")


    def test_material_intake_saves_selected_records_without_executing_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            write_json_atomic(
                workspace / "research" / "papers.json",
                {
                    "records": [
                        {
                            "paper_id": "arxiv:demo",
                            "source": "arxiv",
                            "title": "Demo paper",
                            "pdf_url": "https://papers.example/demo.pdf",
                            "code_url": "https://github.com/example/demo.git",
                        }
                    ]
                },
            )

            def fake_download(url: str, destination: Path) -> dict:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"%PDF-1.4 demo")
                return {"url": url, "path": str(destination), "sha256": "a" * 64, "bytes": 13, "content_type": "application/pdf"}

            with patch("agents.materials_agent._download_pdf", side_effect=fake_download), patch(
                "agents.materials_agent._pdf_excerpt", return_value="Static paper excerpt."
            ), patch(
                "agents.materials_agent.intake_repository",
                return_value={"status": "static_inspection_complete", "record_path": str(workspace / "reproductions" / "demo.json"), "commit": "abc123"},
            ):
                outcome = intake_selected_materials(workspace, ["arxiv:demo"])

            item = outcome["items"][0]
            self.assertEqual(item["paper"]["status"], "downloaded")
            self.assertEqual(item["code"]["status"], "static_inspection_complete")
            self.assertTrue(Path(outcome["report_path"]).exists())
            self.assertIn("Static paper excerpt.", Path(outcome["markdown_path"]).read_text(encoding="utf-8"))

    def test_material_intake_api_returns_a_persisted_background_job(self) -> None:
        class FakeMaterialScheduler:
            def __init__(self) -> None:
                self.received: list[str] | None = None

            def submit(self, paper_ids: list[str]) -> dict:
                self.received = paper_ids
                return {"job_id": "MAT-0001", "status": "queued", "paper_ids": paper_ids, "items": []}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            scheduler = FakeMaterialScheduler()
            handler = type(
                "MaterialApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace, "material_scheduler": scheduler},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/materials/intake",
                    data=json.dumps({"paper_ids": ["arxiv:demo"]}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                    payload = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(payload["job_id"], "MAT-0001")
            self.assertEqual(scheduler.received, ["arxiv:demo"])

    def test_rule_gate_records_the_review_note_and_refuses_an_empty_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_audited_experiment(root, rules_approved=False)
            server, base = _serve_workspace(root, workspace)
            try:
                # 必填字段齐全但还没人工确认：阶段停在「规则待人工确认」。
                self.assertEqual(_get_json(base + "/api/workflow")["components"]["rules"], "awaiting_human_confirmation")

                # 复核说明是这道关口的留痕，空说明不允许通过。
                self.assertEqual(_post_status(base + "/api/rules/approve", {"note": "   "}), 400)

                note = "已逐条核对官方规则页，确认必填字段与提交契约。"
                approved = _post_json(base + "/api/rules/approve", {"note": note})
                self.assertTrue(approved["approved"])
                self.assertEqual(approved["note"], note)
                self.assertTrue(approved["readiness"]["ready"])

                # 关口过了之后：工作流承认规则已确认，仪表盘也不再要求人工确认。
                self.assertEqual(_get_json(base + "/api/workflow")["components"]["rules"], "approved")
                self.assertFalse(_get_json(base + "/api/dashboard")["competition"]["requires_human_confirmation"])
            finally:
                _stop_server(server)

    def test_experiment_gate_marks_the_ledger_and_flips_the_workflow_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_audited_experiment(root)
            server, base = _serve_workspace(root, workspace)
            try:
                first = _get_json(base + "/api/dashboard")["experiments"][0]
                self.assertEqual(first["id"], "EXP-0001")
                self.assertFalse(first["approved"])

                # 缺 experiment_id 不允许记账。
                self.assertEqual(_post_status(base + "/api/decisions/approve", {}), 400)

                approval = _post_json(base + "/api/decisions/approve", {"experiment_id": "EXP-0001"})
                # 批准只在账本留一条记录，执行仍然是人的事。
                self.assertIn("execution remains manual", approval["scope"])

                marked = _get_json(base + "/api/dashboard")["experiments"][0]
                self.assertTrue(marked["approved"])
                self.assertIsNotNone(marked["approved_at"])
                self.assertEqual(_get_json(base + "/api/workflow")["components"]["approvals"], "recorded")
            finally:
                _stop_server(server)


if __name__ == "__main__":
    unittest.main()
