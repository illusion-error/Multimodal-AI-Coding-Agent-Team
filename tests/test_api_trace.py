import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db, generate_trace_id, get_conn

client = TestClient(app)

def test_prompt_versions_empty():
    """测试空数据库返回空数组"""
    init_db()
    response = client.get("/api/prompt/versions")
    assert response.status_code == 200
    data = response.json()
    assert data['code'] == 0
    assert isinstance(data['data'], list)

def test_switch_version_not_found():
    """测试切换不存在的版本返回 404"""
    response = client.post("/api/prompt/version", json={
        "agent_name": "test_agent",
        "version": "v1.0"
    })
    assert response.status_code == 404

def test_get_task_trace_not_found():
    """测试获取不存在任务的 trace"""
    response = client.get("/api/tasks/non-existent-id/trace")
    assert response.status_code == 404

def test_start_benchmark(monkeypatch):
    """测试启动跑批"""
    from backend.database import get_conn
    from backend.main import PROJECT_ROOT
    from sandbox.benchmark_runner import benchmark_planned_total

    monkeypatch.setattr(
        "sandbox.benchmark_runner.run_benchmark",
        lambda **kwargs: {
            "run_id": kwargs.get("run_id"),
            "status": "running",
            "total": benchmark_planned_total(PROJECT_ROOT / "benchmark_data.json"),
            "passed": 0,
        },
    )
    
    # 先清理数据
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")
    
    # 读取题库真实计划数量：题库数 × Benchmark 模式数
    benchmark_file = PROJECT_ROOT / "benchmark_data.json"
    total_questions = benchmark_planned_total(benchmark_file)
    
    response = client.post("/api/benchmark/runs")
    assert response.status_code == 200
    data = response.json()
    assert data['code'] == 0
    assert 'run_id' in data['data']
    assert data['data']['status'] == 'running'
    
    # 验证数据库中已插入 running 记录
    run_id = data['data']['run_id']
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, total, passed FROM benchmark_runs WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        assert row is not None
        assert row["status"] == "running"
        assert row["total"] == total_questions
        assert row["passed"] == 0

def test_get_benchmark_status():
    """测试获取跑批状态 - 查询 running 和 completed 状态"""
    from backend.database import save_benchmark_run, get_conn
    from datetime import datetime
    
    # 先清理数据
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")
    
    run_id = "test-run-id-123"
    now = datetime.now().isoformat(timespec="milliseconds")
    
    # 1. 先插入一条 running 记录（模拟 POST 后的状态）
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO benchmark_runs 
            (run_id, started_at, finished_at, total, passed, pass_rate, avg_duration_ms, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, now, now, 0, 0, 0.0, 0.0, "running")
        )
    
    # 2. 查询 running 状态
    response = client.get(f"/api/benchmark/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"]["run_id"] == run_id
    assert data["data"]["status"] == "running"
    assert data["data"]["progress"] == 0
    
    # 3. 更新为 completed（模拟跑批完成）
    summary = {
        "run_id": run_id,
        "started_at": now,
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
        "total": 10,
        "passed": 8,
        "pass_rate": 80.0,
        "avg_duration": 1500.0,
        "status": "completed",
    }
    details = [
        {"id": "1", "title": "测试题1", "difficulty": "easy", "category": "basic", "passed": True, "duration": 1000, "error": ""},
        {"id": "2", "title": "测试题2", "difficulty": "medium", "category": "normal", "passed": False, "duration": 2000, "error": "超时"},
    ]
    save_benchmark_run(summary, details)
    
    # 4. 查询 completed 状态
    response = client.get(f"/api/benchmark/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"]["run_id"] == run_id
    assert data["data"]["status"] == "completed"
    assert data["data"]["total"] == 10
    assert data["data"]["passed"] == 8
    assert data["data"]["failed"] == 2

def test_benchmark_immediate_query(monkeypatch):
    """测试 POST /api/benchmark/runs 后立即查询返回 running（不等待）"""
    from backend.database import get_conn
    from backend.main import PROJECT_ROOT
    from sandbox.benchmark_runner import benchmark_planned_total

    monkeypatch.setattr(
        "sandbox.benchmark_runner.run_benchmark",
        lambda **kwargs: {
            "run_id": kwargs.get("run_id"),
            "status": "running",
            "total": benchmark_planned_total(PROJECT_ROOT / "benchmark_data.json"),
            "passed": 0,
        },
    )
    
    # 先清理数据
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")
    
    # 1. 启动跑批
    response = client.post("/api/benchmark/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    run_id = data["data"]["run_id"]
    assert run_id is not None
    
    # 2. 立即查询（不等待跑批完成）
    response = client.get(f"/api/benchmark/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"]["run_id"] == run_id
    
    # ===== 修改：状态可能是 running 或 completed（如果跑批太快完成） =====
    status = data["data"]["status"]
    assert status in ["running", "completed"]
    
    if status == "running":
        # 如果还在运行，progress 应该是 0
        assert data["data"]["progress"] == 0
    # ===== 修改结束 =====
    
    # 3. 验证数据库中有记录
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM benchmark_runs WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        assert row is not None
        # 状态应该是 running 或 completed
        assert row["status"] in ["running", "completed"]
