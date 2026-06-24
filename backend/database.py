import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

# 和main保持一致路径
current_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(current_dir, "tasks.db")

# 统一获取数据库连接（解决多线程锁、外键、行字典返回）
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # 开启外键约束，级联删除
    conn.execute("PRAGMA foreign_keys = ON;")
    # 查询返回Row字典，不用记元组下标
    conn.row_factory = sqlite3.Row
    return conn

# 初始化四张表（新增execution_logs日志表）
def init_db():
    conn = None
    try:
        conn = get_conn()
        c = conn.cursor()
        # 任务主表，核心字段非空
        c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            data TEXT NOT NULL
        )
        ''')
        # Agent步骤表，外键关联任务，级联删除
        c.execute('''
        CREATE TABLE IF NOT EXISTS agent_steps (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            input TEXT,
            output TEXT,
            status TEXT NOT NULL,
            duration FLOAT DEFAULT 0.0,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        )
        ''')
        # 测试用例表，外键级联删除
        c.execute('''
        CREATE TABLE IF NOT EXISTS test_cases (
            test_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            input TEXT,
            expected TEXT,
            actual TEXT,
            passed BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        )
        ''')
        # 新增执行日志表（文档要求：运行日志、错误、修复记录）
        c.execute('''
        CREATE TABLE IF NOT EXISTS execution_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            repair_round INTEGER DEFAULT 0,
            error_msg TEXT,
            old_code TEXT,
            new_code TEXT,
            repair_success BOOLEAN DEFAULT 0,
            log_time TIMESTAMP NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        )
        ''')
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# 任务增改，增加时间校验、中文正常存储
def upsert_task(task_id: str, status: str, data: dict, created_at: Optional[str] = None):
    conn = None
    try:
        conn = get_conn()
        c = conn.cursor()
        if created_at is None:
            now = datetime.now().isoformat()
        else:
            # 校验时间格式，防止非法字符串
            datetime.fromisoformat(created_at)
            now = created_at
        c.execute('''
        INSERT OR REPLACE INTO tasks (task_id, status, created_at, data)
        VALUES (?, ?, ?, ?)
        ''', (task_id, status, now, json.dumps(data, ensure_ascii=False)))
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# 查询单任务，自动解析data json，返回字典适配main
def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        task["data"] = json.loads(task["data"])
        return task
    finally:
        conn.close()

# 查询所有任务 倒序，返回字典列表
def list_all_tasks() -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute('''
        SELECT task_id, status, created_at FROM tasks ORDER BY created_at DESC
        ''').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# 插入步骤
def insert_step(task_id: str, step_name: str, input_text: str, output_text: str, status: str, duration: float):
    conn = None
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('''
        INSERT INTO agent_steps (task_id, step_name, input, output, status, duration)
        VALUES (?,?,?,?,?,?)
        ''', (task_id, step_name, input_text, output_text, status, duration))
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# 查询任务全部步骤，返回完整字段（含step_id）
def get_steps_by_task(task_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute('''
        SELECT step_id, step_name, input, output, status, duration
        FROM agent_steps WHERE task_id=?
        ''', (task_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# 插入测试用例
def insert_test_case(task_id: str, input_val: str, expected: str, actual: str, passed: bool):
    conn = None
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('''
        INSERT INTO test_cases (task_id, input, expected, actual, passed)
        VALUES (?,?,?,?,?)
        ''', (task_id, input_val, expected, actual, passed))
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# 查询测试用例，返回完整字段（含test_id）
def get_tests_by_task(task_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute('''
        SELECT test_id, input, expected, actual, passed
        FROM test_cases WHERE task_id=?
        ''', (task_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# 新增：删除任务（级联删除步骤、测试用例、日志）适配rerun清理旧任务
def delete_task(task_id: str):
    conn = None
    try:
        conn = get_conn()
        conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# 新增：写入执行修复日志（匹配文档修复记录需求）
def insert_execution_log(task_id: str, repair_round: int, error_msg: str, old_code: str, new_code: str, repair_success: bool):
    conn = None
    try:
        conn = get_conn()
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
        INSERT INTO execution_logs (task_id, repair_round, error_msg, old_code, new_code, repair_success, log_time)
        VALUES (?,?,?,?,?,?,?)
        ''', (task_id, repair_round, error_msg, old_code, new_code, repair_success, now))
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# 重写指标统计：补齐前端看板全部要求字段
def calc_metrics() -> Dict[str, Any]:
    conn = get_conn()
    try:
        c = conn.cursor()
        # 1. 基础任务统计
        total = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        status_stats = c.execute('''
            SELECT status, COUNT(*) cnt FROM tasks GROUP BY status
        ''').fetchall()
        stat_map = {row["status"]: row["cnt"] for row in status_stats}
        success = stat_map.get("completed", 0)
        failed = stat_map.get("failed", 0)
        running = stat_map.get("running", 0)
        success_rate = round(success / total * 100, 2) if total > 0 else 0

        # 2. 平均响应时间 total_ms
        all_task_data = c.execute("SELECT data FROM tasks").fetchall()
        total_ms_sum = 0
        task_with_time = 0
        for item in all_task_data:
            data = json.loads(item["data"])
            ms = data.get("total_ms", 0)
            if ms > 0:
                total_ms_sum += ms
                task_with_time += 1
        avg_response_time = round(total_ms_sum / task_with_time, 2) if task_with_time > 0 else 0

        # 3. 测试通过率
        total_test = c.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0]
        pass_test = c.execute("SELECT COUNT(*) FROM test_cases WHERE passed=1").fetchone()[0]
        test_pass_rate = round(pass_test / total_test * 100, 2) if total_test > 0 else 0

        # 4. 代码运行成功率（execution_report.exit_code=0 视为运行成功）
        run_success = 0
        for item in all_task_data:
            data = json.loads(item["data"])
            exit_code = data.get("execution_report", {}).get("exit_code", -1)
            if exit_code == 0:
                run_success += 1
        code_run_rate = round(run_success / total * 100, 2) if total > 0 else 0

        # 5. 修复成功率
        repair_total = c.execute("SELECT COUNT(*) FROM execution_logs").fetchone()[0]
        repair_ok = c.execute("SELECT COUNT(*) FROM execution_logs WHERE repair_success=1").fetchone()[0]
        repair_rate = round(repair_ok / repair_total * 100, 2) if repair_total > 0 else 0

        return {
            "total_tasks": total,
            "success_tasks": success,
            "failed_tasks": failed,
            "running_tasks": running,
            "success_rate": success_rate,
            "avg_response_time": avg_response_time,
            "test_pass_rate": test_pass_rate,
            "code_run_rate": code_run_rate,
            "repair_rate": repair_rate
        }
    finally:
        conn.close()