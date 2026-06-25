import backend.main as backend_main


def test_request_api_key_is_forwarded_without_persistence(client, monkeypatch):
    captured = {}
    original_solve = backend_main.solve_problem

    def capture_key(config, *args, **kwargs):
        captured["api_key"] = config.api_key
        config.api_key = ""
        return original_solve(config, *args, **kwargs)

    monkeypatch.setattr(backend_main, "solve_problem", capture_key)
    created = client.post(
        "/api/tasks/text",
        json={"problem_text": "two sum: return indices for nums and target"},
        headers={"X-DashScope-API-Key": "request-only-test-key"},
    )

    assert created.status_code == 200
    task_id = created.json()["data"]["task_id"]
    detail = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert captured["api_key"] == "request-only-test-key"
    assert detail["api_key_source"] == "request"
    assert "request-only-test-key" not in str(detail)
    assert "request-only-test-key" not in str(client.get("/api/tasks").json())
