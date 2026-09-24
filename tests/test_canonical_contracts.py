"""契约测试：拿真实产出核对 `schemas/contracts.py` 里声明的字段与类型。

这一层的价值在于把「两边碰巧一样」变成「两边必须一样」：任何一侧改名、加字段或改类型，
这里就会失败，而不是等到某天读文件读出一堆空值才发现。

端侧那半是**源码级检查**（声明的字段名是否还出现在端侧读/写那段源码里），不是运行时校验；
端侧运行时的一致性由验收流程负责，边界写在 `schemas/contracts.py` 与 `docs/architecture.md`。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agents.rules_agent import (
    BASE_CONFIRMATION_FIELDS,
    EVIDENCE_FIELD_KINDS,
    XUNFEI_CONFIRMATION_FIELDS,
    apply_official_rule_evidence,
    build_rule_evidence_record,
)
from app.project_registry import create_project
from database.ledger import ExperimentLedger, ledger_path
from paper.generator import generate_paper_package
from schemas.contracts import CONTRACTS, Contract, resolve, type_matches
from schemas.experiment import ExperimentManifest, ExperimentResult
from tools.configuration import load_yaml, write_yaml
from tools.files import read_json, write_json_atomic

#: 端侧仓库的根。默认按"与后端仓库同级"推断（本机就是 `B:\YouJustLead`），可用环境变量覆盖。
ARKTS_ROOT_ENV = "YJL_ARKTS_ROOT"


def _arkts_root() -> Path | None:
    """端侧仓库的根。它不在后端仓库内部，所以只能按几个约定位置找 + 允许环境变量覆盖。"""
    configured = os.environ.get(ARKTS_ROOT_ENV)
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    # 本机布局：后端 `B:\You Just Lead\competition-agent`，端侧 `B:\YouJustLead`（**同级目录**，不是子目录）。
    repo_root = _repo_root()
    candidates.append(repo_root.parent / "YouJustLead")
    candidates.append(repo_root.parent.parent / "YouJustLead")
    for candidate in candidates:
        if (candidate / "entry" / "src" / "main" / "ets").is_dir():
            return candidate
    return None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _file_of(locator: str) -> str:
    return locator.split("::", 1)[0]


def _xunfei_spec(workspace: Path) -> dict[str, Any]:
    """一份字段值齐全、锚点齐全的讯飞档案规格（用来喂真实生产函数，不喂假数据）。"""
    values: dict[str, Any] = {
        "competition.name": "Water Cup",
        "competition.platform": "iFLYTEK",
        "competition.task_type": "image_segmentation",
        "competition.deadline": "2026-08-27 17:00 Asia/Shanghai",
        "evaluation.primary_metric": "global_water_iou",
        "evaluation.direction": "maximize",
        "submission.format": "tar.gz inference package",
        "submission.filename_rule": "<input_stem>_mask.png",
        "submission.daily_limit": 3,
        "constraints.model_size_limit_mb": 600,
        "submission.contract.package_layout": "one top-level directory containing run.py and model/",
        "submission.contract.required_files": ["run.py", "model/model.ts"],
        "submission.contract.mask_size": [1024, 1024],
        "submission.contract.mask_filename_suffix": "_mask",
        "submission.contract.runtime_output": "loose_png",
        "constraints.external_data_allowed": False,
        "constraints.pretrained_models_allowed": False,
        "constraints.ensemble_allowed": False,
        "constraints.inference_limit_evidence": "rule page section 4",
    }
    required = list(BASE_CONFIRMATION_FIELDS) + list(XUNFEI_CONFIRMATION_FIELDS)
    spec: dict[str, Any] = {"submission": {"validation_profile": "xunfei_waterseg_inference_package"}}
    for name in required:
        node = spec
        parts = name.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = values[name]
    spec["approval"] = {
        "requires_human_confirmation": True,
        "official_evidence": {
            "fields": {name: f"official section: {name}" for name in required},
        },
        "unresolved_questions": [],
    }
    write_yaml(workspace / "competition_spec.yaml", spec)
    return spec


class ContractDeclarationTests(unittest.TestCase):
    """契约本身的自检：声明不能指向不存在的东西。"""

    def test_every_declared_producer_file_exists(self) -> None:
        root = _repo_root()
        for contract in CONTRACTS.values():
            for locator in (contract.python_producer, contract.python_consumer):
                target = root / _file_of(locator)
                self.assertTrue(target.is_file(), f"{contract.name}: 声明的文件不存在 {locator}")

    def test_every_declared_field_type_is_known(self) -> None:
        for contract in CONTRACTS.values():
            self.assertTrue(contract.fields, f"{contract.name}: 没有声明任何字段")
            for path, type_name in contract.fields.items():
                with self.subTest(contract=contract.name, field=path):
                    self.assertIn(type_name, ("str", "bool", "int", "float", "dict", "list", "any"))

    def test_wildcard_only_appears_in_the_middle_or_at_the_end(self) -> None:
        for contract in CONTRACTS.values():
            for path in contract.fields:
                with self.subTest(contract=contract.name, field=path):
                    self.assertNotEqual(path.split(".")[0], "*")

    def test_arkts_sites_point_at_files_that_exist(self) -> None:
        root = _arkts_root()
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {ARKTS_ROOT_ENV} 指向它即可一并检查")
        for contract in CONTRACTS.values():
            for site in contract.arkts_sites:
                target = root / _file_of(site.locator)
                self.assertTrue(target.is_file(), f"{contract.name}: 端侧文件不存在 {site.locator}")

    def test_declared_field_names_still_appear_in_the_arkts_sources(self) -> None:
        root = _arkts_root()
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {ARKTS_ROOT_ENV} 指向它即可一并检查")
        for contract in CONTRACTS.values():
            for site in contract.arkts_sites:
                source = (root / _file_of(site.locator)).read_text(encoding="utf-8")
                for marker in site.markers:
                    with self.subTest(contract=contract.name, site=site.locator, marker=marker):
                        self.assertIn(
                            marker,
                            source,
                            f"{contract.name}: 端侧 {site.role} 处已看不到字段名 {marker}（可能改名了）",
                        )


class ContractPayloadTests(unittest.TestCase):
    """真实产出必须逐条符合契约。"""

    def assertSatisfies(self, contract: Contract, payload: object) -> None:
        for path, type_name in contract.fields.items():
            with self.subTest(contract=contract.name, field=path):
                found = resolve(payload, path)
                self.assertTrue(found, f"{contract.name}: 真实产出里找不到 {path}")
                for value in found:
                    self.assertTrue(
                        type_matches(type_name, value),
                        f"{contract.name}: {path} 期望 {type_name}，实际是 {type(value).__name__}",
                    )

    def assertNoUndeclaredTopLevelFields(self, contract: Contract, payload: dict) -> None:
        """顶层字段必须恰好是声明的那几个：加了字段却没更新契约同样要失败。"""
        declared = {path.split(".")[0] for path in contract.fields}
        self.assertEqual(sorted(payload), sorted(declared), f"{contract.name}: 顶层字段与契约不一致")

    def test_rule_profile_matches_the_declared_shape(self) -> None:
        contract = CONTRACTS["rule_profile"]
        required = list(BASE_CONFIRMATION_FIELDS) + list(XUNFEI_CONFIRMATION_FIELDS)
        payload = {"required_fields": required, "field_kinds": dict(EVIDENCE_FIELD_KINDS)}

        self.assertSatisfies(contract, payload)
        self.assertNoUndeclaredTopLevelFields(contract, payload)
        self.assertEqual(len(required), 19, "讯飞档案的必备字段应当是 19 个")
        self.assertEqual(len(set(required)), len(required), "必备字段里有重复项")
        self.assertLessEqual(set(EVIDENCE_FIELD_KINDS), set(required), "给不存在的字段声明了控件类型")

    def test_rule_evidence_matches_the_declared_shape_and_round_trips(self) -> None:
        contract = CONTRACTS["rule_evidence"]
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            spec = _xunfei_spec(workspace)
            source = {
                "source_type": "authenticated_rule_page",
                "source_locator": "https://example.invalid/water-segmentation/rule",
                "reviewed_at": "2026-09-24",
            }
            record = build_rule_evidence_record(spec=spec, source=source, overrides={})

            self.assertSatisfies(contract, record)
            self.assertNoUndeclaredTopLevelFields(contract, record)
            required = list(BASE_CONFIRMATION_FIELDS) + list(XUNFEI_CONFIRMATION_FIELDS)
            self.assertEqual(sorted(record["fields"]), sorted(required))

            # 生产端与消费端必须对得上：写出来就得能被读回去。
            evidence_path = workspace / "docs" / "rule_evidence_contract.yaml"
            write_yaml(evidence_path, record)
            outcome = apply_official_rule_evidence(workspace, evidence_path)
            self.assertEqual(sorted(outcome["applied_fields"]), sorted(required))

    def test_workflow_event_matches_the_declared_shape(self) -> None:
        contract = CONTRACTS["workflow_event"]
        with tempfile.TemporaryDirectory() as temporary:
            database = ledger_path(Path(temporary))
            ledger = ExperimentLedger(database, "contract-project")
            ledger.record_event("contract_probe", {"note": "shape only"})

            import sqlite3

            connection = sqlite3.connect(database)
            try:
                columns = [row[1] for row in connection.execute("PRAGMA table_info(workflow_events)")]
                row = connection.execute(
                    "SELECT project_id, event_type, created_at, payload_json FROM workflow_events"
                ).fetchone()
            finally:
                connection.close()

            self.assertIn("project_id", columns, "账本表必须带 project_id")
            payload = {"event_type": row[1], "created_at": row[2], "payload": row[3]}
            self.assertSatisfies(contract, payload)
            self.assertNoUndeclaredTopLevelFields(contract, payload)
            # payload 存的是 JSON 文本，读回来必须还能解析成对象。
            self.assertIsInstance(json.loads(payload["payload"]), dict)
            self.assertEqual(row[0], "contract-project")
            # 秒级 UTC，偏移写 +00:00（两端同格式，别用 Z）。
            self.assertRegex(payload["created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_experiment_manifest_matches_the_declared_shape(self) -> None:
        contract = CONTRACTS["experiment_manifest"]
        manifest = ExperimentManifest(
            experiment_id="EXP-0001",
            hypothesis="A contract probe.",
            config_path="configs/probe.yaml",
            config_sha256="0" * 64,
            parent_id=None,
            change_type="baseline",
            data_version="probe-v1",
            seed=7,
            command="python main.py run",
            git={"commit": None, "available": False},
            environment={"python": "3.10"},
            config={"training": {"device": "cpu"}},
        ).to_dict()

        self.assertSatisfies(contract, manifest)
        self.assertNoUndeclaredTopLevelFields(contract, manifest)

    def test_experiment_result_matches_the_declared_shape(self) -> None:
        contract = CONTRACTS["experiment_result"]
        result = ExperimentResult(
            experiment_id="EXP-0001",
            status="completed",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            best_epoch=1,
            validation_metric=0.5,
            metrics={"accuracy": 0.5},
            runtime_seconds=1.0,
            peak_gpu_memory_gb=None,
            diagnosis={},
            conclusion="done",
            decision="keep",
            next_candidates=[],
            artifact_paths=[],
        ).to_dict()

        self.assertSatisfies(contract, result)
        self.assertNoUndeclaredTopLevelFields(contract, result)

    def _workspace_with_one_completed_experiment(self, workspace: Path, runner: str) -> None:
        """造一个"已审计 + 跑完一条实验"的工作区，供证据声明用。

        `inventory_sha256` 是 64 位、数据目录指向工作区里的 `data/raw`，这样这条实验才落在
        `tools/experiment_scope.py` 认定的审计范围内 —— 声明只允许由在范围内的实验产生。
        """
        raw = workspace / "data" / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "probe.txt").write_text("probe\n", encoding="utf-8")
        write_json_atomic(
            workspace / "reports" / "data_statistics.json",
            {
                "data_dir": str(raw),
                "inventory_sha256": "a" * 64,
                "file_count": 1,
                "issue_count": 0,
                "generated_at": "2026-01-01T00:00:00+00:00",
            },
        )
        config = {
            "data": {"version": "probe-v1", "train_images_dir": str(raw)},
            "training": {"runner": runner, "device": "cpu"},
        }
        write_json_atomic(
            workspace / "experiments" / "manifests" / "EXP-0001.json",
            ExperimentManifest(
                experiment_id="EXP-0001",
                hypothesis="A claim probe.",
                config_path="configs/probe.yaml",
                config_sha256="0" * 64,
                parent_id=None,
                change_type="baseline",
                data_version="probe-v1",
                seed=7,
                command="python main.py run",
                git={},
                environment={},
                config=config,
            ).to_dict(),
        )
        write_json_atomic(
            workspace / "experiments" / "results" / "EXP-0001.json",
            ExperimentResult(
                experiment_id="EXP-0001",
                status="completed",
                started_at="2026-01-01T00:00:00+00:00",
                finished_at="2026-01-01T00:01:00+00:00",
                best_epoch=1,
                validation_metric=0.5,
                metrics={"global_water_iou": 0.5},
                runtime_seconds=1.0,
                peak_gpu_memory_gb=None,
                diagnosis={},
                conclusion="done",
                decision="keep",
                next_candidates=[],
                artifact_paths=[],
            ).to_dict(),
        )

    def test_evidence_claim_matches_the_declared_shape(self) -> None:
        contract = CONTRACTS["evidence_claim"]
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _xunfei_spec(workspace)
            self._workspace_with_one_completed_experiment(workspace, runner="waterseg_external")

            generate_paper_package(workspace)
            evidence = read_json(workspace / "paper" / "generated" / "evidence_map.json")

        claims = evidence["claims"]
        self.assertTrue(claims, "在审计范围内跑完的实验必须产出一条声明")
        for claim in claims:
            self.assertSatisfies(contract, claim)
            self.assertNoUndeclaredTopLevelFields(contract, claim)

    def test_out_of_scope_experiment_produces_no_claim(self) -> None:
        """不在审计范围内的实验（这里是合成 runner）不许产出声明 —— 宁可为空也不编。"""
        contract = CONTRACTS["evidence_claim"]
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _xunfei_spec(workspace)
            self._workspace_with_one_completed_experiment(
                workspace, runner="synthetic_binary_classification"
            )

            generate_paper_package(workspace)
            evidence = read_json(workspace / "paper" / "generated" / "evidence_map.json")

        self.assertEqual(evidence["claims"], [])
        self.assertEqual(contract.name, "evidence_claim")

    def test_project_manifest_matches_the_declared_shape(self) -> None:
        contract = CONTRACTS["project_manifest"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_project(root, "Contract Cup")
            registry = read_json(root / "workspace" / "projects.json")

        self.assertSatisfies(contract, registry)
        self.assertNoUndeclaredTopLevelFields(contract, registry)
        self.assertTrue(registry["projects"])

    def test_a_producer_that_gains_a_field_would_fail(self) -> None:
        """证明这套检查不是摆设：多一个未声明的顶层字段就必须失败。"""
        contract = CONTRACTS["workflow_event"]
        payload = {"event_type": "x", "created_at": "2026-01-01T00:00:00+00:00", "payload": "{}", "extra": 1}
        with self.assertRaises(AssertionError):
            self.assertNoUndeclaredTopLevelFields(contract, payload)

    def test_resolve_reports_a_missing_path_as_empty(self) -> None:
        self.assertEqual(resolve({"a": 1}, "b"), [])
        self.assertEqual(resolve({"a": {"b": 1}}, "a.c"), [])
        self.assertEqual(resolve({"a": [1, 2]}, "a.*"), [1, 2])
        self.assertEqual(resolve({}, "a.*"), [])


if __name__ == "__main__":
    unittest.main()
