"""账本的项目隔离。

界面层早就是多项目（`workspace/projects.json`），持久层却是全局一张表，于是有两个
**静默**缺陷：实验号按工作区各自从 1 编号，而 `experiments` 主键只有 `experiment_id`，
所以 B 项目跑出 `EXP-0001` 会把 A 项目的同号记录无声覆盖；`recent_events()` / `summaries()`
也没有过滤，跨项目混读。

这个文件把「Project A 与 Project B 的任何实验、事件都不许串读」钉死，并覆盖
从 v1（无 project_id）库迁移过来的那条路径。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from app.api_server import CompetitionApiHandler
from app.experiment_service import ExperimentService
from app.project_registry import select_project, workspace_path
from database.ledger import (
    LEGACY_PROJECT_ID,
    SCHEMA_VERSION,
    ExperimentLedger,
    ledger_for_workspace,
    ledger_path,
    project_id_for_workspace,
)
from tools.configuration import write_yaml


def _database(root: Path) -> Path:
    return ledger_path(root)


def _legacy_workspace(root: Path, name: str) -> Path:
    workspace = root / "workspace" / LEGACY_PROJECT_ID
    write_yaml(workspace / "competition_spec.yaml", {"competition": {"name": name}})
    return workspace


def _manifest(experiment_id: str, note: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "status": "completed",
        "created_at": "2026-01-01T00:00:00+00:00",
        "note": note,
    }


def _result(experiment_id: str, metric: float) -> dict:
    return {
        "experiment_id": experiment_id,
        "status": "completed",
        "finished_at": "2026-01-01T00:01:00+00:00",
        "validation_metric": metric,
    }


def _table_columns(database: Path, table: str) -> list[str]:
    connection = sqlite3.connect(database)
    try:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    finally:
        connection.close()


def _raw_count(database: Path, table: str) -> int:
    connection = sqlite3.connect(database)
    try:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def _write_v1_database(database: Path) -> None:
    """按 v1 的建表语句造一个旧库：没有 project_id、没有 user_version。"""
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE experiments (
                experiment_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                validation_metric REAL,
                manifest_json TEXT NOT NULL,
                result_json TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE workflow_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "EXP-0001",
                "completed",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:01:00+00:00",
                0.5,
                json.dumps({"experiment_id": "EXP-0001"}),
                json.dumps({"experiment_id": "EXP-0001"}),
            ),
        )
        connection.execute(
            "INSERT INTO workflow_events (event_type, created_at, payload_json) VALUES (?, ?, ?)",
            ("rules_approved", "2026-01-01T00:02:00+00:00", json.dumps({"note": "legacy"})),
        )
        connection.execute(
            "INSERT INTO workflow_events (event_type, created_at, payload_json) VALUES (?, ?, ?)",
            ("data_audited", "2026-01-01T00:03:00+00:00", json.dumps({"files": 3})),
        )
        connection.commit()
    finally:
        connection.close()


class LedgerProjectIsolationTests(unittest.TestCase):
    """单元层：同一张库上两个项目互不可见。"""

    def test_two_projects_can_own_the_same_experiment_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            alpha = ExperimentLedger(database, "alpha")
            beta = ExperimentLedger(database, "beta")

            alpha.save_manifest(_manifest("EXP-0001", "alpha baseline"))
            alpha.save_result(_result("EXP-0001", 0.11))
            beta.save_manifest(_manifest("EXP-0001", "beta baseline"))
            beta.save_result(_result("EXP-0001", 0.99))

            # 曾经 B 的写入会把 A 的那一行覆盖掉，两边都只剩 0.99。
            self.assertEqual([row["validation_metric"] for row in alpha.summaries()], [0.11])
            self.assertEqual([row["validation_metric"] for row in beta.summaries()], [0.99])
            self.assertEqual(_raw_count(database, "experiments"), 2)

    def test_events_are_not_readable_across_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            alpha = ExperimentLedger(database, "alpha")
            beta = ExperimentLedger(database, "beta")

            alpha.record_event("alpha_only", {"project": "alpha"})
            beta.record_event("beta_only", {"project": "beta"})

            self.assertEqual([row["event_type"] for row in alpha.recent_events()], ["alpha_only"])
            self.assertEqual([row["event_type"] for row in beta.recent_events()], ["beta_only"])
            self.assertEqual(_raw_count(database, "workflow_events"), 2)

    def test_ledger_refuses_to_be_built_without_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))

            for blank in ("", "   "):
                with self.assertRaises(ValueError):
                    ExperimentLedger(database, blank)

    def test_workspace_directory_name_is_the_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = workspace_path(root, "alpha")

            self.assertEqual(project_id_for_workspace(workspace), "alpha")
            self.assertEqual(ledger_for_workspace(root, workspace).project_id, "alpha")

    def test_fresh_database_starts_at_the_current_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))

            ExperimentLedger(database, "alpha")

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            finally:
                connection.close()
            self.assertIn("project_id", _table_columns(database, "experiments"))
            self.assertIn("project_id", _table_columns(database, "workflow_events"))


class LegacyLedgerMigrationTests(unittest.TestCase):
    """迁移路径：v1 旧库的历史行必须一条不少地落到 LEGACY_PROJECT_ID 名下。"""

    def test_v1_rows_are_kept_and_attributed_to_the_legacy_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            _write_v1_database(database)

            ledger = ExperimentLedger(database, LEGACY_PROJECT_ID)

            self.assertEqual([row["experiment_id"] for row in ledger.summaries()], ["EXP-0001"])
            self.assertEqual([row["validation_metric"] for row in ledger.summaries()], [0.5])
            # event_id 也原样保留，账本是流水，编号不能重排。
            self.assertEqual([row["event_id"] for row in ledger.recent_events()], [2, 1])
            self.assertEqual(
                [row["event_type"] for row in ledger.recent_events()],
                ["data_audited", "rules_approved"],
            )

    def test_migrated_rows_are_invisible_to_other_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            _write_v1_database(database)

            other = ExperimentLedger(database, "another-project")

            self.assertEqual(other.summaries(), [])
            self.assertEqual(other.recent_events(), [])

    def test_new_events_continue_the_migrated_numbering(self) -> None:
        """迁移搬过来的是带显式 event_id 的行，自增号不能因此回退去重号。"""
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            _write_v1_database(database)

            ledger = ExperimentLedger(database, LEGACY_PROJECT_ID)
            ledger.record_event("rules_approved", {"note": "after migration"})

            self.assertEqual([row["event_id"] for row in ledger.recent_events()], [3, 2, 1])

    def test_migration_leaves_no_scratch_table_and_runs_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            _write_v1_database(database)

            ExperimentLedger(database, LEGACY_PROJECT_ID)
            ExperimentLedger(database, "alpha")

            connection = sqlite3.connect(database)
            try:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()
            self.assertNotIn("experiments_before_project_isolation", tables)
            self.assertNotIn("workflow_events_before_project_isolation", tables)
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(_raw_count(database, "experiments"), 1)
            self.assertEqual(_raw_count(database, "workflow_events"), 2)

    def test_migration_can_also_start_from_a_database_with_only_one_v1_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary))
            _write_v1_database(database)
            connection = sqlite3.connect(database)
            try:
                connection.execute("DROP TABLE workflow_events")
                connection.commit()
            finally:
                connection.close()

            ledger = ExperimentLedger(database, LEGACY_PROJECT_ID)

            self.assertEqual([row["experiment_id"] for row in ledger.summaries()], ["EXP-0001"])
            self.assertEqual(ledger.recent_events(), [])
            self.assertIn("project_id", _table_columns(database, "workflow_events"))


class LedgerIsolationOnTheRealPathTests(unittest.TestCase):
    """生产路径：两个工作区各自从 1 编号，两条 EXP-0001 必须共存。"""

    def _config(self, workspace: Path) -> Path:
        config_path = workspace / "configs" / "smoke.yaml"
        write_yaml(
            config_path,
            {
                "experiment": {
                    "hypothesis": "A tiny deterministic run validates the workflow.",
                    "change_type": "baseline",
                },
                "data": {
                    "version": "smoke-v1",
                    "synthetic_samples": 96,
                    "synthetic_features": 4,
                    "synthetic_label_noise": 0.2,
                },
                "model": {"hidden_dim": 8},
                "training": {
                    "runner": "synthetic_binary_classification",
                    "seed": 7,
                    "epochs": 2,
                    "batch_size": 16,
                    "device": "cpu",
                },
                "optimizer": {"learning_rate": 0.02},
                "validation": {"metric": "accuracy", "direction": "maximize"},
            },
        )
        return config_path

    def test_two_workspaces_record_the_same_experiment_number_without_clobbering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            alpha = workspace_path(root, "alpha")
            beta = workspace_path(root, "beta")

            alpha_service = ExperimentService(root, alpha)
            alpha_result = alpha_service.run(self._config(alpha), experiment_id="EXP-0001")
            beta_service = ExperimentService(root, beta)
            beta_result = beta_service.run(self._config(beta), experiment_id="EXP-0001")

            # 两个工作区各自留下自己的产物文件。
            self.assertTrue((alpha / "experiments" / "manifests" / "EXP-0001.json").exists())
            self.assertTrue((beta / "experiments" / "manifests" / "EXP-0001.json").exists())

            alpha_rows = alpha_service.ledger.summaries()
            beta_rows = beta_service.ledger.summaries()
            self.assertEqual([row["experiment_id"] for row in alpha_rows], ["EXP-0001"])
            self.assertEqual([row["experiment_id"] for row in beta_rows], ["EXP-0001"])
            self.assertEqual(alpha_rows[0]["validation_metric"], alpha_result[1]["validation_metric"])
            self.assertEqual(beta_rows[0]["validation_metric"], beta_result[1]["validation_metric"])
            self.assertEqual(_raw_count(_database(root), "experiments"), 2)

    def test_created_projects_keep_events_apart_on_the_api_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy_workspace(root, "Legacy Cup")
            handler = type("TestIsolationApiHandler", (CompetitionApiHandler,), {"project_root": root})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                self._post(base, "/api/experiments/drafts", {"hypothesis": "legacy evidence run"})
                created = self._post(base, "/api/projects", {"name": "Draft Cup"})
                project_id = str(created["project"]["id"])
                self._post(base, "/api/experiments/drafts", {"hypothesis": "draft cup candidate"})

                draft_cup = self._get(base, "/api/dashboard")["recent_events"]
                hypotheses = [entry["payload"].get("hypothesis") for entry in draft_cup]
                self.assertIn("draft cup candidate", hypotheses)
                # 新项目自己的建立事件也在它自己的时间线里。
                self.assertIn("project_created", [entry["event_type"] for entry in draft_cup])
                self.assertNotIn("legacy evidence run", hypotheses)

                select_project(root, LEGACY_PROJECT_ID)
                legacy = self._get(base, "/api/dashboard")["recent_events"]
                legacy_hypotheses = [entry["payload"].get("hypothesis") for entry in legacy]
                self.assertIn("legacy evidence run", legacy_hypotheses)
                self.assertNotIn("draft cup candidate", legacy_hypotheses)
                self.assertNotIn("project_created", [entry["event_type"] for entry in legacy])
                self.assertTrue(project_id)
            finally:
                server.shutdown()
                server.server_close()

    def _get(self, base: str, path: str) -> dict:
        with urlopen(base + path, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def _post(self, base: str, path: str, payload: dict) -> dict:
        request = Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())


if __name__ == "__main__":
    unittest.main()
