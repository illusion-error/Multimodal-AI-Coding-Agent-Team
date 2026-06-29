import time
import pytest
from backend.database import get_conn


def test_queue_recovery():
    """测试队列恢复：模拟中断任务被恢复"""
    from backend.database import recover_tasks, enqueue_task
    
    # 清理数据
    with get_conn() as conn:
        conn.execute("DELETE FROM task_queue")
    
    # 创建一个 running 状态的任务（模拟中断）
    task_id = "test-recovery-001"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO task_queue 
            (task_id, queue_type, status, payload, created_at, updated_at, started_at, worker_id)
            VALUES (?, ?, 'running', ?, datetime('now', '-10 minutes'), datetime('now', '-10 minutes'), datetime('now', '-10 minutes'), 'test-worker')
            """,
            (task_id, "agent", '{"problem_text": "test"}')
        )
    
    # 执行恢复
    recover_tasks()
    
    # 验证：running 超过 5 分钟的任务被恢复为 queued
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        assert row is not None
        assert row["status"] == "queued"


def test_cache_hit():
    """测试缓存命中"""
    from backend.database import save_code_cache, get_cached_solution, generate_cache_key
    
    # 清理缓存
    with get_conn() as conn:
        conn.execute("DELETE FROM code_cache")
    
    problem_text = "两数之和"
    cache_key = generate_cache_key(problem_text, None, "v1.0", "qwen-plus", rag_version="v1")
    
    # 保存缓存
    save_code_cache(
        cache_key=cache_key,
        problem_hash="test_hash",
        code="print('hello')",
        solution_markdown="## 解题思路",
        test_cases=[],
        semantic_status="verified",
        model_name="qwen-plus"
    )
    
    # 查询缓存
    cached = get_cached_solution(problem_text, None, "v1.0", "qwen-plus", rag_version="v1")
    assert cached is not None
    assert cached["code"] == "print('hello')"


def test_model_routing():
    """测试模型路由"""
    from backend.main import select_model
    
    # 图片输入 → 视觉模型
    result = select_model("test", image_bytes=b"fake_image_data")
    assert result["model"] == "qwen3-vl-plus"
    assert "图片输入" in result["reason"]
    
    # 短文本 → qwen-turbo
    result = select_model("hello", None)
    assert result["model"] == "qwen-turbo"
    
    # 中等文本 → qwen-plus
    result = select_model("a" * 60, None)
    assert result["model"] == "qwen-plus"
    
    # 长文本 → qwen-max
    result = select_model("a" * 250, None)
    assert result["model"] == "qwen-max"


def test_rate_limiter():
    """测试限流器"""
    from backend.main import RateLimiter
    
    limiter = RateLimiter(max_requests=2, time_window=60)
    
    # 前 2 次应该允许
    assert limiter.is_allowed("test-ip") is True
    assert limiter.is_allowed("test-ip") is True
    
    # 第 3 次应该被拒绝
    assert limiter.is_allowed("test-ip") is False
    
    # 不同 IP 互不影响
    assert limiter.is_allowed("other-ip") is True