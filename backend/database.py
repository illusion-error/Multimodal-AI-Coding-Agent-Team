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

DEFAULT_PROMPT_VERSIONS = [
    {
        "agent_name": "ProblemRecognizer",
        "version": "v1.0",
        "content": (
            "Recognize the programming problem from text or image input. "
            "Extract the original statement, input/output requirements, "
            "constraints, and semantic contract without inventing missing facts."
        ),
        "change_log": "Default prompt for problem recognition.",
    },
    {
        "agent_name": "Planner",
        "version": "v1.0",
        "content": (
            "Plan the solution from the recognized semantic contract and RAG "
            "templates. Explain algorithm choice, edge cases, and complexity."
        ),
        "change_log": "Default prompt for solution planning.",
    },
    {
        "agent_name": "TestGenerator",
        "version": "v1.0",
        "content": (
            "Generate test cases only from trusted semantic contracts and "
            "system templates. Model-suggested tests must stay untrusted until "
            "verified by the evaluator."
        ),
        "change_log": "Default prompt for test generation with anti-drift rules.",
    },
    {
        "agent_name": "CodeGenerator",
        "version": "v1.0",
        "content": (
            "Generate Python 3 solution code according to the plan, contract, "
            "retrieved templates, and trusted tests. Keep the public function "
            "signature compatible with the evaluator."
        ),
        "change_log": "Default prompt for code generation.",
    },
    {
        "agent_name": "Debugger",
        "version": "v1.0",
        "content": (
            "Analyze execution logs and failed trusted tests. Repair code at "
            "most three rounds, never overwrite trusted expected outputs, and "
            "return manual_review when the contract is insufficient."
        ),
        "change_log": "Default prompt for execution debugging and repair.",
    },
]


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


def _seed_default_prompt_versions(conn: sqlite3.Connection) -> None:
    """Ensure a fresh database exposes prompt versions for every Agent."""
    for item in DEFAULT_PROMPT_VERSIONS:
        conn.execute(
            """
            INSERT OR IGNORE INTO prompt_versions
                (agent_name, version, content, is_enabled, change_log)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                item["agent_name"],
                item["version"],
                item["content"],
                item["change_log"],
            ),
        )
        enabled_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM prompt_versions
            WHERE agent_name = ? AND is_enabled = 1
            """,
            (item["agent_name"],),
        ).fetchone()["count"]
        if enabled_count == 0:
            conn.execute(
                """
                UPDATE prompt_versions
                SET is_enabled = 1
                WHERE agent_name = ? AND version = ?
                """,
                (item["agent_name"], item["version"]),
            )


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
                source TEXT NOT NULL DEFAULT 'legacy',
                trusted INTEGER NOT NULL DEFAULT 1,
                validation_status TEXT NOT NULL DEFAULT 'verified',
                contract_id TEXT NOT NULL DEFAULT '',
                contract_fingerprint TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS benchmark_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                total INTEGER NOT NULL,
                passed INTEGER NOT NULL,
                pass_rate REAL NOT NULL,
                avg_duration_ms REAL NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS benchmark_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                difficulty TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                passed INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                version TEXT NOT NULL,
                content TEXT NOT NULL,
                is_enabled INTEGER DEFAULT 0,
                change_log TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_name, version)
            );

            CREATE TABLE IF NOT EXISTS trace_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration_ms INTEGER,
                status TEXT,
                error_message TEXT,
                input_data TEXT,
                output_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_input TEXT,
                tool_output TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration_ms INTEGER,
                status TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cache_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                cache_value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS code_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                problem_hash TEXT NOT NULL,
                image_hash TEXT,
                prompt_version TEXT,
                model_name TEXT,
                cache_type TEXT NOT NULL DEFAULT 'success_code',
                code TEXT NOT NULL,
                solution_markdown TEXT,
                test_cases TEXT,
                semantic_status TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS recognition_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                problem_hash TEXT NOT NULL,
                image_hash TEXT,
                prompt_version TEXT,
                model_name TEXT,
                recognized_text TEXT NOT NULL,
                contract TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS rag_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                problem_hash TEXT NOT NULL,
                prompt_version TEXT,
                model_name TEXT,
                templates TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS rag_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                is_enabled INTEGER DEFAULT 1,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                queue_type TEXT NOT NULL DEFAULT 'agent',
                status TEXT NOT NULL DEFAULT 'queued',
                payload TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                worker_id TEXT
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
        _ensure_column(conn, "test_cases", "source TEXT NOT NULL DEFAULT 'legacy'")
        _ensure_column(conn, "test_cases", "trusted INTEGER NOT NULL DEFAULT 1")
        _ensure_column(
            conn,
            "test_cases",
            "validation_status TEXT NOT NULL DEFAULT 'verified'",
        )
        _ensure_column(conn, "test_cases", "contract_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(
            conn,
            "test_cases",
            "contract_fingerprint TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(conn, "test_cases", "duration_ms INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "test_cases", "error TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "execution_logs", "duration_ms INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "execution_logs", "created_at TEXT NOT NULL DEFAULT ''")

        _ensure_column(conn, "tasks", "trace_id TEXT")
        _ensure_column(conn, "tasks", "prompt_version TEXT")
        _ensure_column(conn, "tasks", "selected_model TEXT")
        _ensure_column(conn, "tasks", "route_reason TEXT")
        _ensure_column(conn, "tasks", "token_usage TEXT")
        _ensure_column(conn, "tasks", "estimated_cost REAL")

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
            CREATE INDEX IF NOT EXISTS idx_benchmark_finished
                ON benchmark_runs(finished_at DESC);
            CREATE INDEX IF NOT EXISTS idx_benchmark_results_run
                ON benchmark_results(run_id, result_id);
            CREATE INDEX IF NOT EXISTS idx_task_queue_status_priority
                ON task_queue(status, priority, created_at);
            CREATE INDEX IF NOT EXISTS idx_code_cache_problem_hash
                ON code_cache(problem_hash);
            CREATE INDEX IF NOT EXISTS idx_code_cache_cache_type
                ON code_cache(cache_type);
            """
        )
        _seed_default_prompt_versions(conn)


def create_task(
    task_id: str,
    status: str,
    data: Dict[str, Any],
    *,
    input_type: str = "text",
    problem: str = "",
    created_at: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    now = created_at or utc_now()
    payload = json.dumps(data, ensure_ascii=False)
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tasks
                    (task_id, status, input_type, problem, created_at, updated_at, data, trace_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, status, input_type, problem, now, now, payload, trace_id),
            )
            conn.commit()
    except Exception as e:
        print(f"[ERROR] create_task 失败: task_id={task_id}, 错误={e}")
        raise


def update_task(task_id: str, status: str, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    trace_id = data.get("trace_id")
    with get_conn() as conn:
        # 先检查任务是否存在
        row = conn.execute(
            "SELECT task_id FROM tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        if not row:
            print(f"[ERROR] update_task: 任务 {task_id} 在 tasks 表中不存在")
            # 尝试重新插入
            try:
                conn.execute(
                    """
                    INSERT INTO tasks
                        (task_id, status, input_type, problem, created_at, updated_at, data, trace_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, status, data.get("input_type", "text"), str(data.get("problem", "")), utc_now(), utc_now(), payload, trace_id),
                )
                conn.commit()
                print(f"[INFO] update_task: 已重新插入任务 {task_id}")
                return
            except Exception as e:
                print(f"[ERROR] update_task: 重新插入失败 {e}")
                raise KeyError(f"Task not found: {task_id}")
        
        # 正常更新
        if trace_id:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status=?, problem=?, updated_at=?, data=?, trace_id=?
                WHERE task_id=?
                """,
                (status, str(data.get("problem", "")), utc_now(), payload, trace_id, task_id),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status=?, problem=?, updated_at=?, data=?
                WHERE task_id=?
                """,
                (status, str(data.get("problem", "")), utc_now(), payload, task_id),
            )
        conn.commit()
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
            SELECT task_id, status, input_type, problem, created_at, updated_at, data, trace_id
            FROM tasks
            WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        return None
    task = dict(row)
    task["data"] = json.loads(task["data"])
    if task.get("trace_id") and "trace_id" not in task["data"]:
        task["data"]["trace_id"] = task["trace_id"]
    return task


def list_all_tasks() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT task_id, status, input_type, problem, created_at, updated_at, data, trace_id
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
        if item.get("trace_id"):
            item["trace_id"] = item["trace_id"]
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
    source: str = "legacy",
    trusted: bool = True,
    validation_status: str = "verified",
    contract_id: str = "",
    contract_fingerprint: str = "",
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
        source,
        int(bool(trusted)),
        validation_status,
        contract_id,
        contract_fingerprint,
        int(duration_ms),
        error,
    )
    sql = """
        INSERT INTO test_cases
            (task_id, input, expected, actual, passed, category, source, trusted,
             validation_status, contract_id, contract_fingerprint, duration_ms,
             error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                   source, trusted, validation_status, contract_id,
                   contract_fingerprint, duration_ms, error
            FROM test_cases
            WHERE task_id=?
            ORDER BY test_id
            """,
            (task_id,),
        ).fetchall()
    return [
        {
            **dict(row),
            "passed": bool(row["passed"]),
            "trusted": bool(row["trusted"]),
        }
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
                source=str(case.get("source", "legacy")),
                trusted=bool(case.get("trusted", True)),
                validation_status=str(
                    case.get("validation_status", "verified")
                ),
                contract_id=str(case.get("contract_id", "")),
                contract_fingerprint=str(
                    case.get("contract_fingerprint", "")
                ),
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
            WHERE trusted=1 AND validation_status='verified'
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


def save_benchmark_run(
    summary: Dict[str, Any],
    details: Iterable[Dict[str, Any]],
) -> None:
    with get_conn() as conn:
        # 检查记录是否存在
        existing = conn.execute(
            "SELECT run_id FROM benchmark_runs WHERE run_id = ?",
            (summary["run_id"],)
        ).fetchone()
        
        if existing:
            # 记录已存在（由 POST 创建），使用 UPDATE
            conn.execute(
                """
                UPDATE benchmark_runs
                SET started_at = ?,
                    finished_at = ?,
                    total = ?,
                    passed = ?,
                    pass_rate = ?,
                    avg_duration_ms = ?,
                    status = ?
                WHERE run_id = ?
                """,
                (
                    summary["started_at"],
                    summary["finished_at"],
                    int(summary["total"]),
                    int(summary["passed"]),
                    float(summary["pass_rate"]),
                    float(summary["avg_duration"]),
                    str(summary.get("status", "completed")),
                    summary["run_id"],
                )
            )
        else:
            # 记录不存在（直接调用 run_benchmark），使用 INSERT
            conn.execute(
                """
                INSERT INTO benchmark_runs
                    (run_id, started_at, finished_at, total, passed, pass_rate,
                     avg_duration_ms, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["run_id"],
                    summary["started_at"],
                    summary["finished_at"],
                    int(summary["total"]),
                    int(summary["passed"]),
                    float(summary["pass_rate"]),
                    float(summary["avg_duration"]),
                    str(summary.get("status", "completed")),
                )
            )
        
        conn.execute(
            "DELETE FROM benchmark_results WHERE run_id=?",
            (summary["run_id"],),
        )
        conn.executemany(
            """
            INSERT INTO benchmark_results
                (run_id, task_id, title, difficulty, category, passed,
                 duration_ms, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    summary["run_id"],
                    str(item.get("id", item.get("task_id", ""))),
                    str(item.get("title", "")),
                    str(item.get("difficulty", "")),
                    str(item.get("category", "")),
                    int(bool(item.get("passed", False))),
                    int(item.get("duration", item.get("duration_ms", 0)) or 0),
                    str(item.get("error", "")),
                )
                for item in details
            ],
        )


def get_latest_benchmark_results() -> Dict[str, Any]:
    with get_conn() as conn:
        run = conn.execute(
            """
            SELECT run_id, started_at, finished_at, total, passed, pass_rate,
                   avg_duration_ms, status
            FROM benchmark_runs
            ORDER BY finished_at DESC
            LIMIT 1
            """
        ).fetchone()
        if not run:
            return {}
        rows = conn.execute(
            """
            SELECT task_id, title, difficulty, category, passed, duration_ms, error
            FROM benchmark_results
            WHERE run_id=?
            ORDER BY result_id
            """,
            (run["run_id"],),
        ).fetchall()
    return {
        "run_id": run["run_id"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "status": run["status"],
        "total": run["total"],
        "passed": run["passed"],
        "pass_rate": run["pass_rate"],
        "avg_duration": run["avg_duration_ms"],
        "details": [
            {
                "id": row["task_id"],
                "title": row["title"],
                "difficulty": row["difficulty"],
                "category": row["category"],
                "passed": bool(row["passed"]),
                "duration": row["duration_ms"],
                "error": row["error"],
            }
            for row in rows
        ],
    }


init_db()

# ========== 新增：Trace 相关函数 ==========

import uuid

def generate_trace_id() -> str:
    """生成新的 trace_id"""
    return str(uuid.uuid4())

def insert_trace_node(
    trace_id: str,
    node_name: str,
    node_type: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    duration_ms: Optional[int] = None,
    status: str = 'pending',
    error_message: Optional[str] = None,
    input_data: Optional[Dict] = None,
    output_data: Optional[Dict] = None
) -> int:
    """插入 trace 节点记录"""
    with get_conn() as conn:
        cursor = conn.execute('''
            INSERT INTO trace_nodes 
            (trace_id, node_name, node_type, start_time, end_time, duration_ms, 
             status, error_message, input_data, output_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trace_id, node_name, node_type, start_time, end_time, duration_ms,
            status, error_message,
            json.dumps(input_data, ensure_ascii=False) if input_data else None,
            json.dumps(output_data, ensure_ascii=False) if output_data else None
        ))
        return cursor.lastrowid

def insert_tool_call(
    trace_id: str,
    tool_name: str,
    tool_input: Optional[Dict] = None,
    tool_output: Optional[Dict] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    duration_ms: Optional[int] = None,
    status: str = 'pending',
    error_message: Optional[str] = None
) -> int:
    """插入工具调用记录"""
    with get_conn() as conn:
        cursor = conn.execute('''
            INSERT INTO tool_calls 
            (trace_id, tool_name, tool_input, tool_output, start_time, end_time, 
             duration_ms, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trace_id, tool_name,
            json.dumps(tool_input, ensure_ascii=False) if tool_input else None,
            json.dumps(tool_output, ensure_ascii=False) if tool_output else None,
            start_time, end_time, duration_ms, status, error_message
        ))
        return cursor.lastrowid

def get_trace_by_trace_id(trace_id: str) -> Dict[str, Any]:
    """根据 trace_id 查询完整的 trace 数据"""
    with get_conn() as conn:
        # 获取任务信息
        task = conn.execute(
            'SELECT * FROM tasks WHERE trace_id = ?', (trace_id,)
        ).fetchone()
        
        # 获取节点
        nodes = conn.execute(
            'SELECT * FROM trace_nodes WHERE trace_id = ? ORDER BY start_time, id',
            (trace_id,)
        ).fetchall()
        
        # 获取工具调用
        tools = conn.execute(
            'SELECT * FROM tool_calls WHERE trace_id = ? ORDER BY start_time, id',
            (trace_id,)
        ).fetchall()
    
    result = {
        'task': dict(task) if task else None,
        'nodes': [],
        'tool_calls': []
    }
    
    for node in nodes:
        node_dict = dict(node)
        # 解析 JSON 字段
        if node_dict.get('input_data'):
            try:
                node_dict['input_data'] = json.loads(node_dict['input_data'])
            except:
                pass
        if node_dict.get('output_data'):
            try:
                node_dict['output_data'] = json.loads(node_dict['output_data'])
            except:
                pass
        result['nodes'].append(node_dict)
    
    for tool in tools:
        tool_dict = dict(tool)
        if tool_dict.get('tool_input'):
            try:
                tool_dict['tool_input'] = json.loads(tool_dict['tool_input'])
            except:
                pass
        if tool_dict.get('tool_output'):
            try:
                tool_dict['tool_output'] = json.loads(tool_dict['tool_output'])
            except:
                pass
        result['tool_calls'].append(tool_dict)
    
    return result

def get_task_by_task_id_for_trace(task_id: str) -> Optional[Dict[str, Any]]:
    """获取任务的 trace_id（用于 trace 查询）"""
    with get_conn() as conn:
        row = conn.execute(
            'SELECT task_id, trace_id FROM tasks WHERE task_id = ?',
            (task_id,)
        ).fetchone()
    return dict(row) if row else None


# ========== 新增：任务队列操作函数 ==========

def enqueue_task(task_id: str, payload: Dict[str, Any], queue_type: str = "agent") -> int:
    """将任务加入队列"""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO task_queue 
            (task_id, queue_type, status, payload, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (task_id, queue_type, json.dumps(payload, ensure_ascii=False))
        )
        conn.commit()
        return cursor.lastrowid


def dequeue_task(worker_id: str, queue_type: str = "agent") -> Optional[Dict[str, Any]]:
    """获取一个待执行任务（原子操作）"""
    with get_conn() as conn:
        # 找到一个 queued 任务并锁定为 running
        row = conn.execute(
            """
            SELECT id, task_id, payload, retry_count, max_retries
            FROM task_queue
            WHERE status = 'queued' AND queue_type = ?
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            """,
            (queue_type,)
        ).fetchone()
        
        if not row:
            return None
        
        # 更新状态为 running
        conn.execute(
            """
            UPDATE task_queue
            SET status = 'running', 
                started_at = CURRENT_TIMESTAMP, 
                updated_at = CURRENT_TIMESTAMP,
                worker_id = ?
            WHERE id = ?
            """,
            (worker_id, row["id"])
        )
        
        return dict(row)


def complete_task(task_id: str, status: str, error_message: str = ""):
    """标记任务完成"""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE task_queue
            SET status = ?,
                finished_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE task_id = ?
            """,
            (status, error_message, task_id)
        )


def fail_task(task_id: str, error_message: str):
    """标记任务失败，如果重试次数未满则重新入队"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT retry_count, max_retries, payload
            FROM task_queue
            WHERE task_id = ?
            """,
            (task_id,)
        ).fetchone()
        
        if not row:
            return
        
        if row["retry_count"] < row["max_retries"]:
            # 重新入队
            conn.execute(
                """
                UPDATE task_queue
                SET status = 'queued',
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    worker_id = NULL,
                    error_message = ?
                WHERE task_id = ?
                """,
                (f"重试 {row['retry_count'] + 1}: {error_message}", task_id)
            )
        else:
            # 最终失败
            conn.execute(
                """
                UPDATE task_queue
                SET status = 'failed',
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    error_message = ?
                WHERE task_id = ?
                """,
                (f"重试耗尽: {error_message}", task_id)
            )


def recover_tasks():
    """启动时恢复中断的任务"""
    with get_conn() as conn:
        # 将 running 超过 5 分钟的任务标记为中断并重新入队
        conn.execute(
            """
            UPDATE task_queue
            SET status = 'queued',
                worker_id = NULL,
                updated_at = CURRENT_TIMESTAMP,
                error_message = '任务在启动时恢复，之前状态为 running'
            WHERE status = 'running' 
              AND datetime(started_at) < datetime('now', '-5 minutes')
            """
        )


def generate_cache_key(problem_text: str, image_bytes: Optional[bytes] = None, prompt_version: str = "", model: str = "", rag_version: str = "", test_mode: bool = False) -> str:
    import hashlib
    import os
    import sys
    
    normalized_problem = problem_text.strip().lower()
    problem_hash = hashlib.md5(normalized_problem.encode('utf-8')).hexdigest()
    
    image_hash = ""
    if image_bytes:
        image_hash = hashlib.md5(image_bytes).hexdigest()
    
    is_test = test_mode or os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules
    test_suffix = "_test" if is_test else ""
    
    key_parts = [problem_hash, image_hash, prompt_version, model, rag_version, test_suffix]
    full_key = "|".join(key_parts)
    cache_key = hashlib.md5(full_key.encode('utf-8')).hexdigest()
    
    return cache_key


def get_cache_by_key(cache_key: str) -> Optional[Dict[str, Any]]:
    """根据缓存键获取缓存"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, cache_key, problem_hash, image_hash, prompt_version, model_name,
                   cache_type, code, solution_markdown, test_cases, semantic_status,
                   hit_count, created_at, updated_at
            FROM code_cache
            WHERE cache_key = ?
            """,
            (cache_key,)
        ).fetchone()
    
    if not row:
        return None
    
    result = dict(row)
    # 增加命中次数
    with get_conn() as conn:
        conn.execute(
            "UPDATE code_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (cache_key,)
        )
    
    return result


def save_code_cache(
    cache_key: str,
    problem_hash: str,
    code: str,
    solution_markdown: str,
    test_cases: List[Dict[str, Any]],
    semantic_status: str,
    image_hash: str = "",
    prompt_version: str = "",
    model_name: str = "",
    cache_type: str = "success_code"
) -> int:
    """保存代码缓存（只有语义 verified 才能缓存）"""
    if semantic_status != "verified":
        return 0  # 不缓存非 verified 的结果
    
    with get_conn() as conn:
        # 先删除旧的
        conn.execute(
            "DELETE FROM code_cache WHERE cache_key = ?",
            (cache_key,)
        )
        
        # 插入新的
        cursor = conn.execute(
            """
            INSERT INTO code_cache
            (cache_key, problem_hash, image_hash, prompt_version, model_name,
             cache_type, code, solution_markdown, test_cases, semantic_status,
             hit_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                cache_key,
                problem_hash,
                image_hash,
                prompt_version,
                model_name,
                cache_type,
                code,
                solution_markdown,
                json.dumps(test_cases, ensure_ascii=False) if test_cases else "[]",
                semantic_status,
            )
        )
        return cursor.lastrowid


def get_cached_solution(
    problem_text: str,
    image_bytes: Optional[bytes] = None,
    prompt_version: str = "",
    model: str = "",
    rag_version: str = "",
    test_mode: bool = False
) -> Optional[Dict[str, Any]]:
    """根据题目获取缓存的解决方案"""
    cache_key = generate_cache_key(problem_text, image_bytes, prompt_version, model, rag_version, test_mode)
    return get_cache_by_key(cache_key)


def get_hit_count_by_problem(problem_text: str) -> int:
    """获取某道题目的缓存命中次数"""
    import hashlib
    problem_hash = hashlib.md5(problem_text.strip().lower().encode('utf-8')).hexdigest()
    
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT SUM(hit_count) as total_hits
            FROM code_cache
            WHERE problem_hash = ?
            """,
            (problem_hash,)
        ).fetchone()
    
    return row["total_hits"] if row and row["total_hits"] else 0



def save_recognition_cache(
    cache_key: str,
    problem_hash: str,
    recognized_text: str,
    contract: Optional[Dict[str, Any]] = None,
    image_hash: str = "",
    prompt_version: str = "",
    model_name: str = "",
) -> int:
    """保存题目识别缓存"""
    with get_conn() as conn:
        # 先删除旧的
        conn.execute(
            "DELETE FROM recognition_cache WHERE cache_key = ?",
            (cache_key,)
        )
        
        cursor = conn.execute(
            """
            INSERT INTO recognition_cache
            (cache_key, problem_hash, image_hash, prompt_version, model_name,
             recognized_text, contract)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                problem_hash,
                image_hash,
                prompt_version,
                model_name,
                recognized_text,
                json.dumps(contract, ensure_ascii=False) if contract else None,
            )
        )
        return cursor.lastrowid


def get_recognition_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    """获取题目识别缓存"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT cache_key, problem_hash, image_hash, prompt_version, model_name,
                   recognized_text, contract, created_at
            FROM recognition_cache
            WHERE cache_key = ?
            """,
            (cache_key,)
        ).fetchone()
    
    if not row:
        return None
    
    result = dict(row)
    if result.get("contract"):
        try:
            result["contract"] = json.loads(result["contract"])
        except:
            pass
    return result


def save_rag_cache(
    cache_key: str,
    problem_hash: str,
    templates: List[Dict[str, Any]],
    prompt_version: str = "",
    model_name: str = "",
) -> int:
    """保存 RAG 检索缓存"""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM rag_cache WHERE cache_key = ?",
            (cache_key,)
        )
        
        cursor = conn.execute(
            """
            INSERT INTO rag_cache
            (cache_key, problem_hash, prompt_version, model_name, templates)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                problem_hash,
                prompt_version,
                model_name,
                json.dumps(templates, ensure_ascii=False),
            )
        )
        return cursor.lastrowid


def get_rag_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    """获取 RAG 检索缓存"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT cache_key, problem_hash, prompt_version, model_name,
                   templates, created_at
            FROM rag_cache
            WHERE cache_key = ?
            """,
            (cache_key,)
        ).fetchone()
    
    if not row:
        return None
    
    result = dict(row)
    if result.get("templates"):
        try:
            result["templates"] = json.loads(result["templates"])
        except:
            pass
    return result


def get_current_rag_version() -> str:
    """获取当前启用的 RAG 版本"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT version FROM rag_versions
            WHERE is_enabled = 1
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    
    if not row:
        return "v1"  # 默认版本
    
    return row["version"]


def set_rag_version(version: str, description: str = "") -> None:
    """设置 RAG 版本（将指定版本设为启用，其他版本禁用）"""
    with get_conn() as conn:
        # 禁用所有版本
        conn.execute(
            "UPDATE rag_versions SET is_enabled = 0, updated_at = CURRENT_TIMESTAMP"
        )
        
        # 检查版本是否存在
        row = conn.execute(
            "SELECT id FROM rag_versions WHERE version = ?",
            (version,)
        ).fetchone()
        
        if row:
            # 启用该版本
            conn.execute(
                "UPDATE rag_versions SET is_enabled = 1, updated_at = CURRENT_TIMESTAMP WHERE version = ?",
                (version,)
            )
        else:
            # 插入新版本
            conn.execute(
                """
                INSERT INTO rag_versions (version, is_enabled, description)
                VALUES (?, 1, ?)
                """,
                (version, description)
            )
