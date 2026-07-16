"""SQLite mirror of JSON experiment records for queryable local state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class ExperimentLedger:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
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

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    experiment_id, status, created_at, manifest_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    status=excluded.status,
                    manifest_json=excluded.manifest_json
                """,
                (
                    manifest["experiment_id"],
                    manifest["status"],
                    manifest["created_at"],
                    json.dumps(manifest, ensure_ascii=False),
                ),
            )

    def save_result(self, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE experiments
                SET status=?, finished_at=?, validation_metric=?, result_json=?
                WHERE experiment_id=?
                """,
                (
                    result["status"],
                    result["finished_at"],
                    result["validation_metric"],
                    json.dumps(result, ensure_ascii=False),
                    result["experiment_id"],
                ),
            )

    def summaries(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT experiment_id, status, created_at, finished_at, validation_metric
                FROM experiments
                ORDER BY created_at, experiment_id
                """
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
