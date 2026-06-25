from backend.database import (
    calc_metrics,
    create_task,
    get_execution_logs_by_task,
    get_steps_by_task,
    get_task_by_id,
    get_tests_by_task,
    replace_task_artifacts,
    update_task,
)


def test_task_update_preserves_child_records():
    create_task("task-1", "running", {"problem": "two sum"}, problem="two sum")
    original_created_at = get_task_by_id("task-1")["created_at"]

    replace_task_artifacts(
        "task-1",
        steps=[
            {
                "agent_name": f"agent-{index}",
                "status": "completed",
                "input": "input",
                "output": "output",
                "duration_ms": index,
            }
            for index in range(1, 6)
        ],
        tests=[
            {
                "args": [1, 2],
                "input": "1, 2",
                "expected": "3",
                "actual": "3",
                "passed": True,
                "source": "system_authoritative",
                "trusted": True,
                "validation_status": "verified",
                "contract_id": "addition",
                "contract_fingerprint": "abc123",
            }
        ],
        repairs=[{"round": 1, "status": "passed", "reason": "fixed"}],
    )
    update_task(
        "task-1",
        "completed",
        {
            "problem": "two sum",
            "total_ms": 100,
            "execution_report": {"exit_code": 0},
        },
    )

    assert len(get_steps_by_task("task-1")) == 5
    stored_tests = get_tests_by_task("task-1")
    assert len(stored_tests) == 1
    assert stored_tests[0]["source"] == "system_authoritative"
    assert stored_tests[0]["trusted"] is True
    assert stored_tests[0]["contract_id"] == "addition"
    assert len(get_execution_logs_by_task("task-1")) == 1
    assert get_task_by_id("task-1")["created_at"] == original_created_at
    assert calc_metrics()["test_pass_rate"] == 100
