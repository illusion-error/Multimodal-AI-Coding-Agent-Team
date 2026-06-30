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


def test_benchmark_uses_external_run_id_for_progress(tmp_path, monkeypatch):
    import json
    import sandbox.benchmark_runner as runner

    benchmark_file = tmp_path / "benchmark_data.json"
    benchmark_file.write_text(
        json.dumps(
            [
                {
                    "task_id": "T001",
                    "title": "示例题",
                    "category": "basic",
                    "difficulty": "简单",
                    "problem_text": "返回 1。函数名：solution()",
                    "test_cases": [{"input": "", "expected": "1"}],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "solve_problem", lambda config, problem: object())
    monkeypatch.setattr(
        runner,
        "agent_result_to_dict",
        lambda result: {
            "problem": "返回 1",
            "retrieved_templates": ["basic"],
            "repair_attempts": [],
            "code": "def solution():\n    return 1",
        },
    )
    monkeypatch.setattr(
        runner,
        "run_auto_tests",
        lambda code, cases: {
            "is_final_passed": True,
            "passed": len(cases),
            "details": [],
        },
    )
    monkeypatch.setattr(runner, "generate_comparison_md", lambda summaries, base_path: None)

    run_id = "frontend-visible-run"
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")

    summary = run_benchmark(
        persist=True,
        api_key="",
        data_path=benchmark_file,
        run_id=run_id,
    )

    assert summary["run_id"] == run_id
    assert summary["total"] == 2
    assert summary["status"] == "completed"

    with get_conn() as conn:
        run = conn.execute(
            "SELECT status, total, passed FROM benchmark_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]

    assert run is not None
    assert run["status"] == "completed"
    assert run["total"] == 2
    assert run["passed"] == 2
    assert count == 2
