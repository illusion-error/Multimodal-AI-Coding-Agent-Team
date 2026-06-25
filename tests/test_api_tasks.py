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
