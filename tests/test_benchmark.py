from backend.database import get_conn
from sandbox.benchmark_runner import run_benchmark

def test_benchmark_executes_all_questions_and_persists():
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")
    
    summary = run_benchmark(persist=True, api_key="")

    # 动态验证 30 题
    assert summary["total"] == 30
    assert summary["status"] == "completed"
    assert all(item["duration"] >= 0 for item in summary["details"])

    with get_conn() as conn:
        row = conn.execute("SELECT run_id, total, passed FROM benchmark_runs WHERE run_id = ?", (summary["run_id"],)).fetchone()
        assert row is not None
        assert row["run_id"] == summary["run_id"]
        assert row["total"] == 30