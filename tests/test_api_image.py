def test_image_validation_and_workflow(client):
    invalid = client.post(
        "/api/tasks/image",
        files={"image": ("problem.txt", b"text", "text/plain")},
    )
    assert invalid.status_code == 400

    empty = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", b"", "image/png")},
    )
    assert empty.status_code == 400

    created = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", b"not-a-real-image", "image/png")},
        data={"supplement": "two sum: nums and target"},
    )
    assert created.status_code == 200
    task_id = created.json()["data"]["task_id"]
    detail = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert detail["status"] == "completed"
    assert detail["input_type"] == "image"
    assert len(client.get(f"/api/tasks/{task_id}/steps").json()["data"]) == 5
