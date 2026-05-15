"""SQLite persistence for AgentWeb tasks, tool calls, and audits."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agentweb.core import _now

SCHEMA_VERSION = 3

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    goal TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_call_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    status TEXT NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    result TEXT NOT NULL,
    request_id TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
"""


class AgentWebStore:
    """Small SQLite repository for local AgentWeb state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))

    def schema_version(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            return int(row["version"] or 0)

    def upsert_task(
        self,
        task_id: str,
        *,
        status: str,
        goal: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        actor: str = "system",
        request_id: str = "",
    ) -> None:
        now = _now()
        with self.connect() as conn:
            existing = conn.execute("SELECT goal, result_json FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            final_goal = goal if goal is not None else (existing["goal"] if existing else None)
            final_result = result if result is not None else (_load(existing["result_json"]) if existing else {})
            conn.execute(
                """
                INSERT INTO tasks(task_id, status, goal, result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    goal=excluded.goal,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (task_id, status, final_goal, _dump(final_result), error, now, now),
            )
            self._audit(conn, actor=actor, action="task.upsert", target=task_id, result=status, request_id=request_id)

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "status": row["status"],
            "goal": row["goal"],
            "result": _load(row["result_json"]),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def record_tool_call(
        self,
        *,
        task_id: str,
        tool_name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        status: str,
        elapsed_ms: int,
        error: str | None = None,
        actor: str = "system",
        request_id: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_call_records(task_id, tool_name, input_json, output_json, status, elapsed_ms, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, tool_name, _dump(input_payload), _dump(output_payload), status, elapsed_ms, error),
            )
            self._audit(conn, actor=actor, action="tool.invoke", target=tool_name, result=status, request_id=request_id, details={"task_id": task_id})

    def tool_calls(self, *, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_call_records WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "tool_name": row["tool_name"],
                "input_payload": _load(row["input_json"]),
                "output_payload": _load(row["output_json"]),
                "status": row["status"],
                "elapsed_ms": row["elapsed_ms"],
                "error": row["error"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def audit_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "actor": row["actor"],
                "action": row["action"],
                "target": row["target"],
                "result": row["result"],
                "request_id": row["request_id"],
                "details": _load(row["details_json"]),
            }
            for row in rows
        ]

    def dump(self, value: Any) -> str:
        return _dump(value)

    def load(self, value: str) -> Any:
        return _load(value)

    def _audit(
        self,
        conn: sqlite3.Connection,
        *,
        actor: str,
        action: str,
        target: str,
        result: str,
        request_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_logs(actor, action, target, result, request_id, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (actor or "system", action, target, result, request_id or "", _dump(details or {})),
        )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str) -> Any:
    return json.loads(value or "{}")
