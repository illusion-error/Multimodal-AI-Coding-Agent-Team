from backend.database import get_latest_benchmark_results
from sandbox.benchmark_runner import run_benchmark


def test_benchmark_executes_all_questions_and_persists():
    summary = run_benchmark(persist=True, api_key="")

    assert summary["total"] == 5
    assert summary["passed"] == 5
    assert summary["pass_rate"] == 100
    assert all(item["duration"] >= 0 for item in summary["details"])

    stored = get_latest_benchmark_results()
    assert stored["run_id"] == summary["run_id"]
    assert len(stored["details"]) == 5
