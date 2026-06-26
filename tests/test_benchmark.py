from backend.database import get_latest_benchmark_results, get_conn
from sandbox.benchmark_runner import run_benchmark


def test_benchmark_executes_all_questions_and_persists():
    # 先清理旧的 benchmark 数据，避免干扰
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")
    
    summary = run_benchmark(persist=True, api_key="")

    assert summary["total"] == 5
    assert summary["passed"] == 5
    assert summary["pass_rate"] == 100
    assert all(item["duration"] >= 0 for item in summary["details"])

    # 验证记录已写入数据库
    with get_conn() as conn:
        row = conn.execute(
            "SELECT run_id FROM benchmark_runs WHERE run_id = ?",
            (summary["run_id"],)
        ).fetchone()
        assert row is not None, f"Run {summary['run_id']} not found in database"
        assert row["run_id"] == summary["run_id"]

    stored = get_latest_benchmark_results()
    assert stored["run_id"] == summary["run_id"]
    assert len(stored["details"]) == 5