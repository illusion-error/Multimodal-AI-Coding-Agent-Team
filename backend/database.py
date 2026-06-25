from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _database_path() -> Path:
    configured = os.getenv("DATABASE_PATH", "backend/data/tasks.db")
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = _database_path()


def utc_now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                input_type TEXT NOT NULL DEFAULT 'text',
                problem TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_steps (
                step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                step_order INTEGER NOT NULL DEFAULT 0,
                step_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                input TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS test_cases (
                test_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                input TEXT NOT NULL DEFAULT '',
                expected TEXT NOT NULL DEFAULT '',
                actual TEXT NOT NULL DEFAULT '',
                passed INTEGER NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT 'normal',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS execution_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                repair_round INTEGER NOT NULL DEFAULT 0,
                error_msg TEXT NOT NULL DEFAULT '',
                old_code TEXT NOT NULL DEFAULT '',
                new_code TEXT NOT NULL DEFAULT '',
                repair_success INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );

            """
        )

        # Upgrade databases created by earlier project revisions without data loss.
        _ensure_column(conn, "tasks", "input_type TEXT NOT NULL DEFAULT 'text'")
        _ensure_column(conn, "tasks", "problem TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "tasks", "updated_at TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "agent_steps", "step_order INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "agent_steps", "role TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "agent_steps", "duration_ms INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "agent_steps", "error TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "test_cases", "category TEXT NOT NULL DEFAULT 'normal'")
        _ensure_column(conn, "test_cases", "duration_ms INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "test_cases", "error TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "execution_logs", "duration_ms INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "execution_logs", "created_at TEXT NOT NULL DEFAULT ''")

        now = utc_now()
        conn.execute(
            "UPDATE tasks SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL"
        )
        conn.execute(
            "UPDATE execution_logs SET created_at=? "
            "WHERE created_at='' OR created_at IS NULL",
            (now,),
        )
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_created_at
                ON tasks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_steps_task_order
                ON agent_steps(task_id, step_order, step_id);
            CREATE INDEX IF NOT EXISTS idx_tests_task
                ON test_cases(task_id, test_id);
            CREATE INDEX IF NOT EXISTS idx_logs_task_round
                ON execution_logs(task_id, repair_round, log_id);
            """
        )


def create_task(
    task_id: str,
    status: str,
    data: Dict[str, Any],
    *,
    input_type: str = "text",
    problem: str = "",
    created_at: Optional[str] = None,
) -> None:
    now = created_at or utc_now()
    payload = json.dumps(data, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tasks
                (task_id, status, input_type, problem, created_at, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, status, input_type, problem, now, now, payload),
        )


def update_task(task_id: str, status: str, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET status=?, problem=?, updated_at=?, data=?
            WHERE task_id=?
            """,
            (status, str(data.get("problem", "")), utc_now(), payload, task_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Task not found: {task_id}")


def upsert_task(
    task_id: str,
    status: str,
    data: Dict[str, Any],
    created_at: Optional[str] = None,
) -> None:
    """Backward-compatible helper that never replaces/deletes an existing row."""

    if get_task_by_id(task_id):
        update_task(task_id, status, data)
    else:
        create_task(
            task_id,
            status,
            data,
            problem=str(data.get("problem", "")),
            created_at=created_at,
        )


def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT task_id, status, input_type, problem, created_at, updated_at, data
            FROM tasks
            WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        return None
    task = dict(row)
    task["data"] = json.loads(task["data"])
    return task


def list_all_tasks() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT task_id, status, input_type, problem, created_at, updated_at, data
            FROM tasks
            ORDER BY created_at DESC
            """
        ).fetchall()
    tasks: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        data = json.loads(item.pop("data"))
        item["problem"] = item["problem"] or str(data.get("problem", ""))
        item["total_ms"] = data.get("total_ms", 0)
        tasks.append(item)
    return tasks


def insert_step(
    task_id: str,
    step_name: str,
    input_text: str,
    output_text: str,
    status: str,
    duration: float = 0.0,
    *,
    role: str = "",
    error: str = "",
    duration_ms: Optional[int] = None,
    step_order: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    milliseconds = (
        int(duration_ms)
        if duration_ms is not None
        else int(duration * 1000 if duration < 1000 else duration)
    )
    values = (
        task_id,
        step_order,
        step_name,
        role,
        input_text,
        output_text,
        status,
        milliseconds,
        error,
    )
    sql = """
        INSERT INTO agent_steps
            (task_id, step_order, step_name, role, input, output, status,
             duration_ms, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    if conn is not None:
        conn.execute(sql, values)
        return
    with get_conn() as local_conn:
        local_conn.execute(sql, values)


def get_steps_by_task(task_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT step_id, step_order, step_name, role, input, output, status,
                   duration_ms, error
            FROM agent_steps
            WHERE task_id=?
            ORDER BY step_order, step_id
            """,
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_test_case(
    task_id: str,
    input_val: str,
    expected: str,
    actual: str,
    passed: bool,
    *,
    category: str = "normal",
    duration_ms: int = 0,
    error: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    values = (
        task_id,
        input_val,
        expected,
        actual,
        int(bool(passed)),
        category,
        int(duration_ms),
        error,
    )
    sql = """
        INSERT INTO test_cases
            (task_id, input, expected, actual, passed, category, duration_ms, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    if conn is not None:
        conn.execute(sql, values)
        return
    with get_conn() as local_conn:
        local_conn.execute(sql, values)


def get_tests_by_task(task_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT test_id, input, expected, actual, passed, category,
                   duration_ms, error
            FROM test_cases
            WHERE task_id=?
            ORDER BY test_id
            """,
            (task_id,),
        ).fetchall()
    return [
        {**dict(row), "passed": bool(row["passed"])}
        for row in rows
    ]


def insert_execution_log(
    task_id: str,
    repair_round: int,
    error_msg: str,
    old_code: str,
    new_code: str,
    repair_success: bool,
    *,
    duration_ms: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    target_conn = conn or get_conn()
    values = [
        task_id,
        int(repair_round),
        error_msg,
        old_code,
        new_code,
        int(bool(repair_success)),
        int(duration_ms),
        utc_now(),
    ]
    columns = [
        "task_id",
        "repair_round",
        "error_msg",
        "old_code",
        "new_code",
        "repair_success",
        "duration_ms",
        "created_at",
    ]
    if "log_time" in _table_columns(target_conn, "execution_logs"):
        columns.append("log_time")
        values.append(values[-1])
    placeholders = ", ".join("?" for _ in columns)
    sql = f"""
        INSERT INTO execution_logs
            ({", ".join(columns)})
        VALUES ({placeholders})
    """
    try:
        target_conn.execute(sql, values)
        if conn is None:
            target_conn.commit()
    finally:
        if conn is None:
            target_conn.close()


def get_execution_logs_by_task(task_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT log_id, repair_round, error_msg, old_code, new_code,
                   repair_success, duration_ms, created_at
            FROM execution_logs
            WHERE task_id=?
            ORDER BY repair_round, log_id
            """,
            (task_id,),
        ).fetchall()
    return [
        {**dict(row), "repair_success": bool(row["repair_success"])}
        for row in rows
    ]


def replace_task_artifacts(
    task_id: str,
    *,
    steps: Iterable[Dict[str, Any]],
    tests: Iterable[Dict[str, Any]],
    repairs: Iterable[Dict[str, Any]],
) -> None:
    """Replace a task's child records atomically after an Agent run."""

    with get_conn() as conn:
        conn.execute("DELETE FROM agent_steps WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM test_cases WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM execution_logs WHERE task_id=?", (task_id,))
        for index, step in enumerate(steps, start=1):
            insert_step(
                task_id,
                str(step.get("agent_name", step.get("name", "Agent"))),
                str(step.get("input", "")),
                str(step.get("output", "")),
                str(step.get("status", "completed")),
                role=str(step.get("role", "")),
                error=str(step.get("error", "")),
                duration_ms=int(step.get("duration_ms", 0) or 0),
                step_order=index,
                conn=conn,
            )
        for case in tests:
            insert_test_case(
                task_id,
                str(case.get("input", "")),
                str(case.get("expected", "")),
                str(case.get("actual", "")),
                bool(case.get("passed", False)),
                category=str(case.get("category", case.get("name", "normal"))),
                duration_ms=int(case.get("duration_ms", 0) or 0),
                error=str(case.get("error", "")),
                conn=conn,
            )
        for attempt in repairs:
            insert_execution_log(
                task_id,
                int(attempt.get("round", 0) or 0),
                str(attempt.get("error", attempt.get("reason", ""))),
                str(attempt.get("old_code", "")),
                str(attempt.get("new_code", "")),
                str(attempt.get("status", "")).lower() in {"passed", "success"},
                duration_ms=int(attempt.get("duration_ms", 0) or 0),
                conn=conn,
            )


def delete_task(task_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))


def calc_metrics() -> Dict[str, Any]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
        ).fetchall()
        status_map = {row["status"]: row["count"] for row in status_rows}
        completed = status_map.get("completed", 0)
        failed = status_map.get("failed", 0)
        running = status_map.get("running", 0)

        task_rows = conn.execute(
            "SELECT status, data FROM tasks"
        ).fetchall()
        durations: List[float] = []
        run_success = 0
        for row in task_rows:
            data = json.loads(row["data"])
            duration = float(data.get("total_ms", 0) or 0)
            if duration > 0:
                durations.append(duration)
            report = data.get("execution_report", {})
            if isinstance(report, dict) and report.get("exit_code") == 0:
                run_success += 1

        test_total, test_passed = conn.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN passed=1 THEN 1 ELSE 0 END), 0)
            FROM test_cases
            """
        ).fetchone()
        repair_total, repair_passed = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(CASE WHEN repair_success=1 THEN 1 ELSE 0 END), 0)
            FROM execution_logs
            """
        ).fetchone()

    return {
        "total_tasks": total,
        "success_tasks": completed,
        "failed_tasks": failed,
        "running_tasks": running,
        "success_rate": round(completed / total * 100, 2) if total else 0.0,
        "avg_response_time": (
            round(sum(durations) / len(durations), 2) if durations else 0.0
        ),
        "test_pass_rate": (
            round(test_passed / test_total * 100, 2) if test_total else 0.0
        ),
        "code_run_rate": round(run_success / total * 100, 2) if total else 0.0,
        "repair_rate": (
            round(repair_passed / repair_total * 100, 2)
            if repair_total
            else 0.0
        ),
    }


init_db()
