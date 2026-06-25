def test_text_task_full_workflow(client):
    assert client.get("/api/health").json()["data"]["agent_loaded"] is True
    assert client.post("/api/tasks/text", json={"problem_text": "   "}).status_code == 400

    created = client.post(
        "/api/tasks/text",
        json={"problem_text": "two sum: return indices for nums and target"},
    )
    assert created.status_code == 200
    task_id = created.json()["data"]["task_id"]

    detail = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert detail["status"] == "completed"
    assert detail["fallback_used"] is True
    assert detail["code"]
    assert detail["project_document"]

    steps = client.get(f"/api/tasks/{task_id}/steps").json()["data"]
    tests = client.get(f"/api/tasks/{task_id}/tests").json()["data"]
    assert len(steps) == 5
    assert len(tests) >= 3

    history = client.get("/api/tasks").json()["data"]
    assert history[0]["task_id"] == task_id
    assert history[0]["problem"]

    report = client.get(f"/api/tasks/{task_id}/report")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    assert "Python" in report.text

    rerun = client.post(f"/api/tasks/{task_id}/rerun").json()["data"]
    assert rerun["task_id"] != task_id
    assert client.get(f"/api/tasks/{rerun['task_id']}").json()["data"]["status"] == "completed"

    metrics = client.get("/api/metrics/summary").json()["data"]
    assert metrics["total_tasks"] == 2
    assert metrics["success_tasks"] == 2


def test_failed_execution_is_not_counted_as_completed(client, monkeypatch):
    import backend.main as backend_main

    original_solve = backend_main.solve_problem

    def return_failed_result(*args, **kwargs):
        result = original_solve(*args, **kwargs)
        result.execution_report = "状态：failed\n\n退出码：1\n\n错误输出：测试失败"
        result.test_cases = [
            {
                "name": "失败用例",
                "input": "1",
                "expected": "2",
                "actual": "1",
                "passed": False,
                "category": "basic",
                "duration_ms": 1,
                "error": "expected 2, got 1",
            }
        ]
        return result

    monkeypatch.setattr(backend_main, "solve_problem", return_failed_result)
    created = client.post(
        "/api/tasks/text",
        json={"problem_text": "two sum: return indices for nums and target"},
    )
    task_id = created.json()["data"]["task_id"]
    detail = client.get(f"/api/tasks/{task_id}").json()["data"]
    metrics = client.get("/api/metrics/summary").json()["data"]

    assert detail["status"] == "failed"
    assert metrics["success_tasks"] == 0
    assert metrics["failed_tasks"] == 1
    assert metrics["test_pass_rate"] == 0


def test_pasted_broken_code_triggers_visible_repair_workflow(client):
    problem = """
请调试并修复下面的两数之和 Python 代码：

```python
def solution(nums, target)
    return []
```
"""
    created = client.post("/api/tasks/text", json={"problem_text": problem})
    task_id = created.json()["data"]["task_id"]
    detail = client.get(f"/api/tasks/{task_id}").json()["data"]
    repairs = client.get(f"/api/tasks/{task_id}/repairs").json()["data"]
    tests = client.get(f"/api/tasks/{task_id}/tests").json()["data"]

    assert detail["status"] == "completed"
    assert len(repairs) == 1
    assert repairs[0]["repair_success"] is True
    assert len(tests) == 3
    assert all(case["passed"] for case in tests)
