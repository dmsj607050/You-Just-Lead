"""SQLite mirror of JSON experiment records for queryable local state.

两张表都带 `project_id`，**所有读取都必须显式带上项目**。界面层早就是多项目
（`workspace/projects.json`），持久层不能再靠「当前项目」这种隐含状态，否则 A 项目
的事件与实验会出现在 B 项目里，而且是静默的——不报错，只是读到别人的数据。

改成带项目维度之前，这张库上有两个真实缺陷：

1. 实验号是**按工作区各自从 1 编号**的（`app/experiment_service.py::next_experiment_id`），
   而 `experiments` 的主键只有 `experiment_id`，所以 B 项目跑出 `EXP-0001` 会**无声覆盖**
   A 项目的同号记录（`ON CONFLICT(experiment_id)`）。现在主键是
   `(project_id, experiment_id)`。
2. `recent_events()` / `summaries()` 没有任何过滤，跨项目混读。现在都按项目过滤。

加项目维度之前写进去的历史数据，在第一次打开时迁移到 `LEGACY_PROJECT_ID`。这次迁移是
必需的：`database/migrations/` 在此之前是空的，库上也从没写过 `user_version`，
所以版本只能按「表在不在、列全不全」来判断。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

#: 当前 schema 版本。加项目维度是 v2；v1 是「全局一张表」那版。
SCHEMA_VERSION = 2

DATABASE_FILENAME = "competition_agent.sqlite"

#: 加项目隔离之前只有一个工作区，历史数据一律归它。这是事实，不是猜测。
LEGACY_PROJECT_ID = "current_competition"

_PROJECT_ID_COLUMN = "project_id"
_V1_EXPERIMENTS = "experiments_before_project_isolation"
_V1_EVENTS = "workflow_events_before_project_isolation"


def ledger_path(project_root: Path) -> Path:
    """账本库的位置。只有这里知道它在哪，调用方别再自己拼路径。"""
    return Path(project_root) / "database" / DATABASE_FILENAME


def project_id_for_workspace(workspace: Path) -> str:
    """由工作区目录推出项目 id。

    注册表定的规矩是「一个项目 = 一个工作区目录 `workspace/<id>`」，所以目录名就是 id，
    这里只是把它读出来，不另立一套规则。命令行 `--workspace` 指向别的目录时同样照此取名，
    不同目录天然拿到不同的 id，不会互相覆盖。
    """
    return Path(workspace).resolve().name


def ledger_for_workspace(project_root: Path, workspace: Path) -> ExperimentLedger:
    """某个工作区所属项目的账本。

    这是**唯一**推荐的构造方式：既定位数据库，又把项目定下来。直接 `ExperimentLedger(...)`
    要求调用方自己给出 project_id，给不出就该去查工作区，而不是退回全局读写。
    """
    return ExperimentLedger(ledger_path(project_root), project_id_for_workspace(workspace))


class ExperimentLedger:
    def __init__(self, database_path: Path, project_id: str):
        if not str(project_id).strip():
            # 明确拒绝：没有项目的账本等于回到「全局一张表」，那正是要修掉的东西。
            raise ValueError("ExperimentLedger requires a project_id")
        self.project_id = str(project_id)
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            if self._schema_version(connection) < SCHEMA_VERSION:
                self._migrate_to_v2(connection)
            self._create_schema(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()

    def _schema_version(self, connection: sqlite3.Connection) -> int:
        """判断现有库的 schema 版本。

        迁移之前的库**从没写过** `user_version`（一直是 0），所以不能只看 PRAGMA：
        表存在但没有 `project_id` 列就是 v1；一张表都没有的空库直接按当前版本建。
        """
        recorded = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if recorded:
            return recorded
        if not self._has_table(connection, "experiments"):
            return SCHEMA_VERSION
        columns = {row[1] for row in connection.execute("PRAGMA table_info(experiments)")}
        return SCHEMA_VERSION if _PROJECT_ID_COLUMN in columns else 1

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                project_id TEXT NOT NULL,
                experiment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                validation_metric REAL,
                manifest_json TEXT NOT NULL,
                result_json TEXT,
                PRIMARY KEY (project_id, experiment_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS workflow_events_by_project
            ON workflow_events (project_id, event_id)
            """
        )

    def _migrate_to_v2(self, connection: sqlite3.Connection) -> None:
        """把没有项目维度的旧表搬到带 `project_id` 的新表，旧行归 `LEGACY_PROJECT_ID`。

        SQLite 的 DDL 本身可回滚，但 Python 的 sqlite3 只在 DML 前隐式开事务，
        所以这里显式接管事务：要么整体迁移，要么一点都不动（不留半迁移的库）。
        """
        previous = connection.isolation_level
        connection.isolation_level = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            for source, legacy in (("experiments", _V1_EXPERIMENTS), ("workflow_events", _V1_EVENTS)):
                if self._has_table(connection, source):
                    connection.execute(f"ALTER TABLE {source} RENAME TO {legacy}")
            self._create_schema(connection)
            if self._has_table(connection, _V1_EXPERIMENTS):
                connection.execute(
                    f"""
                    INSERT INTO experiments (
                        project_id, experiment_id, status, created_at, finished_at,
                        validation_metric, manifest_json, result_json
                    )
                    SELECT ?, experiment_id, status, created_at, finished_at,
                           validation_metric, manifest_json, result_json
                    FROM {_V1_EXPERIMENTS}
                    """,
                    (LEGACY_PROJECT_ID,),
                )
                connection.execute(f"DROP TABLE {_V1_EXPERIMENTS}")
            if self._has_table(connection, _V1_EVENTS):
                connection.execute(
                    f"""
                    INSERT INTO workflow_events (
                        event_id, project_id, event_type, created_at, payload_json
                    )
                    SELECT event_id, ?, event_type, created_at, payload_json
                    FROM {_V1_EVENTS}
                    """,
                    (LEGACY_PROJECT_ID,),
                )
                connection.execute(f"DROP TABLE {_V1_EVENTS}")
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.isolation_level = previous

    @staticmethod
    def _has_table(connection: sqlite3.Connection, name: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    project_id, experiment_id, status, created_at, manifest_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, experiment_id) DO UPDATE SET
                    status=excluded.status,
                    manifest_json=excluded.manifest_json
                """,
                (
                    self.project_id,
                    manifest["experiment_id"],
                    manifest["status"],
                    manifest["created_at"],
                    json.dumps(manifest, ensure_ascii=False),
                ),
            )
            connection.commit()

    def save_result(self, result: dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE experiments
                SET status=?, finished_at=?, validation_metric=?, result_json=?
                WHERE project_id=? AND experiment_id=?
                """,
                (
                    result["status"],
                    result["finished_at"],
                    result["validation_metric"],
                    json.dumps(result, ensure_ascii=False),
                    self.project_id,
                    result["experiment_id"],
                ),
            )
            connection.commit()

    def summaries(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT experiment_id, status, created_at, finished_at, validation_metric
                FROM experiments
                WHERE project_id=?
                ORDER BY created_at, experiment_id
                """,
                (self.project_id,),
            ).fetchall()
        return [
            {
                "experiment_id": row[0],
                "status": row[1],
                "created_at": row[2],
                "finished_at": row[3],
                "validation_metric": row[4],
            }
            for row in rows
        ]

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append an immutable workflow event for non-experiment actions."""
        from tools.provenance import utc_now

        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO workflow_events (project_id, event_type, created_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (self.project_id, event_type, utc_now(), json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, created_at, payload_json
                FROM workflow_events
                WHERE project_id=?
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (self.project_id, limit),
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "event_type": row[1],
                "created_at": row[2],
                "payload": json.loads(row[3]),
            }
            for row in rows
        ]
