"""真实数据端到端：整条链在**真实文件**上按顺序跑通一次。

目标里对工程质量门禁的要求是「前三层主要集中在前两层，后面真正应该新增的是 **Real Project E2E Test**」。
这个文件补的就是那一层：不是把各模块分别测一遍，而是按 Golden Path 的**顺序**走一遍，
每一步的产物都被下一步真实消费，中间没有任何手工塞进去的中间态：

    建项目 → 规则人工批准 → 写真实 CSV → 数据审计（真实指纹）
          → 训练配置人工批准 → 执行真实训练（tabular_classification，CPU）
          → 指标 / 产物 / manifest / 账本 → 论文证据图（真实 Claim）→ 溯源四条链

**范围说明（别把它的结论放大）**：这证明的是「流水线在真实文件上跑得通，且真实训练的七道闸门
真的会拦人」。它**不是**比赛成绩 —— 数据是本测试自己写的 CSV，因为比赛数据（`B:\\2026xunfei`）
已经不在本机了。比赛口径的 G3/G4 仍然要等真实数据回来。
"""

from __future__ import annotations

import csv
import random
import tempfile
import unittest
from pathlib import Path

from agents.data_agent import audit_dataset
from agents.rules_agent import approve_rule_specification
from app.experiment_service import ExperimentService
from app.project_registry import create_project, workspace_path
from app.trace_service import trace_snapshot
from database.ledger import ledger_for_workspace
from paper.generator import generate_paper_package
from tools.configuration import load_yaml, write_yaml
from tools.files import read_json

ROWS = 240
FEATURE_NAMES = ("feature_1", "feature_2")


def _write_dataset(raw_dir: Path, *, rows: int = ROWS, seed: int = 7) -> None:
    """写一份**真实落盘**的数值 CSV：特征 + 目标列，线性可分（指标稳定且不靠运气）。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    header = ["id", *FEATURE_NAMES, "target"]
    for name in ("train.csv", "test.csv"):
        with (raw_dir / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for index in range(rows):
                first = rng.uniform(-1.0, 1.0)
                second = rng.uniform(-1.0, 1.0)
                writer.writerow([f"row-{index}", f"{first:.6f}", f"{second:.6f}", 1 if first + second > 0 else 0])


def _generic_spec(workspace: Path) -> None:
    """一份**通用**档案的规格：没有讯飞那 19 个固定字段，所以批准只要求"无未澄清问题 + 人工确认"。

    先把 `requires_human_confirmation` 留成 true，再走真实的批准函数把它翻过来 ——
    不直接写 false，那样就绕过了这道闸门，测不到东西。
    """
    write_yaml(
        workspace / "competition_spec.yaml",
        {
            "competition": {"name": "E2E Cup", "task_type": "tabular_classification"},
            "evaluation": {"primary_metric": "accuracy", "direction": "maximize"},
            "approval": {"requires_human_confirmation": True, "unresolved_questions": []},
        },
    )


def _config(workspace: Path, raw_dir: Path, fingerprint: str) -> Path:
    """训练配置：真实数据 runner + CPU + 绝对数据路径。

    数据路径必须是**绝对**且落在审计目录内 —— `app/authorization.py::AuditedInputScopePolicy`
    按提交上来的参数原样检查，相对路径会被解析到当前工作目录而不是工作区，所以会被拒。
    `data.version` 记审计指纹，与 `tools/experiment_scope.py` 的口径对上。
    """
    config_path = workspace / "configs" / "e2e_tabular.yaml"
    write_yaml(
        config_path,
        {
            "experiment": {
                "hypothesis": "A shallow MLP reproduces a held-out tabular baseline on audited local data.",
                "change_type": "baseline",
                "estimated_gpu_hours": 0,
                "rollback_plan": "Keep this frozen baseline if later changes underperform.",
            },
            "data": {
                "version": fingerprint,
                "train_csv": str(raw_dir / "train.csv"),
                "test_csv": str(raw_dir / "test.csv"),
                "target_column": "target",
                "id_column": "id",
                "prediction_column": "target",
                "validation_fraction": 0.2,
                "feature_columns": list(FEATURE_NAMES),
            },
            "model": {"hidden_dim": 32, "dropout": 0.0},
            "training": {
                "runner": "tabular_classification",
                "seed": 42,
                "epochs": 12,
                "batch_size": 32,
                "device": "cpu",
            },
            "optimizer": {"name": "adamw", "learning_rate": 0.01, "weight_decay": 0.0},
            "validation": {"metric": "accuracy", "direction": "maximize"},
        },
    )
    return config_path


class RealDataEndToEndTests(unittest.TestCase):
    """一遍走完 Golden Path；两处各断言一次，避免把长流程写成"跑完就算数"。"""

    def _prepare(self, root: Path) -> tuple[Path, Path, Path]:
        project = create_project(root, "E2E Cup")
        workspace = workspace_path(root, str(project["id"]))
        _generic_spec(workspace)
        raw_dir = workspace / "data" / "raw"
        _write_dataset(raw_dir)
        return project, workspace, raw_dir

    def test_rules_are_approved_by_a_human_before_anything_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, workspace, _ = self._prepare(Path(temporary))

            outcome = approve_rule_specification(workspace, "Reviewed the generic tabular rules.")

            spec = load_yaml(workspace / "competition_spec.yaml")
            self.assertFalse(spec["approval"]["requires_human_confirmation"])
            self.assertTrue(outcome["approved"])

    def test_audit_records_a_fingerprint_of_the_real_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, workspace, raw_dir = self._prepare(Path(temporary))

            report = audit_dataset(workspace, raw_dir)

            stored = read_json(workspace / "reports" / "data_statistics.json")
            self.assertEqual(report["file_count"], 2)
            self.assertEqual(stored["data_dir"], str(raw_dir))
            self.assertEqual(len(str(stored["inventory_sha256"])), 64)

    def _approved_and_audited(self, root: Path) -> tuple[Path, Path, Path]:
        """走到"可以开跑"之前的全部前置步骤：批准规则 → 审计数据 → 写配置。"""
        _, workspace, raw_dir = self._prepare(root)
        approve_rule_specification(workspace, "Reviewed the generic tabular rules.")
        audit_dataset(workspace, raw_dir)
        fingerprint = str(read_json(workspace / "reports" / "data_statistics.json")["inventory_sha256"])
        return workspace, raw_dir, _config(workspace, raw_dir, fingerprint)

    def test_training_is_blocked_until_a_human_confirms_the_rules(self) -> None:
        """闸门真的会拦人之一：规则没人工确认，真实训练起不来。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, workspace, raw_dir = self._prepare(root)
            # 故意**不**批准规则。
            audit_dataset(workspace, raw_dir)
            fingerprint = str(read_json(workspace / "reports" / "data_statistics.json")["inventory_sha256"])
            config_path = _config(workspace, raw_dir, fingerprint)

            with self.assertRaises(PermissionError) as caught:
                ExperimentService(root, workspace).run(config_path, experiment_id="EXP-0001")

            self.assertIn("human confirmation", str(caught.exception))

    def test_training_is_blocked_when_the_audited_data_changed(self) -> None:
        """闸门真的会拦人之二：审计之后动了数据，跑就被拒。

        「审计过」不等于「一直是审计过的那份数据」—— 这条把数据指纹那道策略端到端验了一次。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, raw_dir, config_path = self._approved_and_audited(Path(temporary))

            with (raw_dir / "train.csv").open("a", encoding="utf-8") as handle:
                handle.write("row-extra,0.5,0.5,1\n")

            with self.assertRaises(PermissionError) as caught:
                ExperimentService(root, workspace).run(config_path, experiment_id="EXP-0001")

            self.assertIn("changed after its audit", str(caught.exception))

    def test_full_chain_from_real_files_to_a_traceable_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, _, config_path = self._approved_and_audited(root)
            fingerprint = str(read_json(workspace / "reports" / "data_statistics.json")["inventory_sha256"])

            service = ExperimentService(root, workspace)
            manifest, result = service.run(
                config_path,
                experiment_id="EXP-0001",
                command="python main.py run --config configs/e2e_tabular.yaml",
            )

            # 1) 真实训练跑完了，指标是真算出来的。
            self.assertEqual(result["status"], "completed", result.get("error"))
            self.assertIsNotNone(result["validation_metric"])
            self.assertGreater(float(result["validation_metric"]), 0.5)
            self.assertEqual(manifest["data_version"], fingerprint)
            self.assertEqual(manifest["config"]["training"]["runner"], "tabular_classification")

            # 2) 产物真的落在工作区里，且 manifest/result 都在盘上。
            self.assertTrue((workspace / "experiments" / "manifests" / "EXP-0001.json").is_file())
            self.assertTrue((workspace / "experiments" / "results" / "EXP-0001.json").is_file())
            self.assertTrue(result["artifact_paths"], "真实跑完必须留下产物")
            for artifact in result["artifact_paths"]:
                self.assertTrue(Path(str(artifact)).exists(), artifact)

            # 3) 账本按项目记录，且记到了这次实验。
            ledger = ledger_for_workspace(root, workspace)
            self.assertEqual(ledger.summaries()[0]["experiment_id"], "EXP-0001")

            # 4) 论文证据图产出**真实 Claim**（不是空列表，也不是编的）。
            generate_paper_package(workspace)
            evidence = read_json(workspace / "paper" / "generated" / "evidence_map.json")
            claims = evidence["claims"]
            self.assertTrue(claims, "在审计范围内跑完的实验必须产出一条声明")
            self.assertEqual(claims[0]["experiment_id"], "EXP-0001")
            self.assertEqual(claims[0]["result_path"], "experiments/results/EXP-0001.json")

            # 5) 溯源四条链 + 论文终点都能读到同一次实验。
            trace = trace_snapshot(root, workspace)
            self.assertTrue(trace["rule"]["ready"])
            self.assertTrue(trace["rule"]["approved"], "规则已经人工确认过")
            self.assertEqual(trace["data"]["audit"]["file_count"], 2)
            # 这一条很关键：这次实验被判定为**在审计范围内**（合成 runner 会被排除）。
            self.assertEqual(trace["data"]["in_scope_count"], 1)
            scope = {item["experiment_id"]: item for item in trace["data"]["experiments"]}
            self.assertTrue(scope["EXP-0001"]["in_scope"])
            self.assertEqual(scope["EXP-0001"]["exclusion"], None)
            self.assertIn("EXP-0001", {item["experiment_id"] for item in trace["experiments"]["experiments"]})
            self.assertTrue(trace["paper"]["available"])
            self.assertEqual(len(trace["paper"]["claims"]), 1)
            self.assertTrue(trace["paper"]["claims"][0]["result_exists"])

    def test_the_same_inputs_reproduce_the_same_metric(self) -> None:
        """可复跑：同一份数据指纹 + 同一份配置 + 同一个种子 → 同一个指标。

        这是目标里 Phase C 对"可复跑"的定义。指标对不上就说明有隐藏的随机性或外部状态。
        """
        metrics: list[float] = []
        for run_index in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, workspace, raw_dir = self._prepare(root)
                approve_rule_specification(workspace, "Reviewed the generic tabular rules.")
                audit_dataset(workspace, raw_dir)
                fingerprint = str(
                    read_json(workspace / "reports" / "data_statistics.json")["inventory_sha256"]
                )
                config_path = _config(workspace, raw_dir, fingerprint)

                _, result = ExperimentService(root, workspace).run(config_path, experiment_id="EXP-0001")
                self.assertEqual(result["status"], "completed", result.get("error"))
                metrics.append(float(result["validation_metric"]))
                if run_index == 0:
                    first_fingerprint = fingerprint
                else:
                    self.assertEqual(fingerprint, first_fingerprint, "同一份数据必须得到同一个指纹")

        self.assertEqual(metrics[0], metrics[1], "同种子同配置必须复现同一个指标")


if __name__ == "__main__":
    unittest.main()
