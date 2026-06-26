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

def test_start_benchmark():
    """测试启动跑批"""
    response = client.post("/api/benchmark/runs")
    assert response.status_code == 200
    data = response.json()
    assert data['code'] == 0
    assert 'run_id' in data['data']
    assert data['data']['status'] == 'running'

def test_get_benchmark_status():
    """测试获取跑批状态"""
    response = client.get("/api/benchmark/runs/test-run-id")
    assert response.status_code == 200
    data = response.json()
    assert data['code'] == 0
    assert data['data']['run_id'] == 'test-run-id'