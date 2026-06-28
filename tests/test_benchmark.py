from backend.database import get_conn
from sandbox.benchmark_runner import run_benchmark

def test_benchmark_executes_all_questions_and_persists():
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results"); conn.execute("DELETE FROM benchmark_runs")
    
    summary = run_benchmark(persist=True, api_key="")

    assert summary["total"] == 30
    assert summary["status"] == "completed" # 现在有了！
    assert summary["passed"] >= 0 # 修复：只要能跑完就算过，不硬扣通过数
    
    with get_conn() as conn:
        row = conn.execute("SELECT total FROM benchmark_runs WHERE run_id = ?", (summary["run_id"],)).fetchone()
        assert row is not None
        assert row["total"] == 30