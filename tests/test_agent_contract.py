from ai_coding_agent_bailian import (
    AgentConfig,
    AgentResult,
    agent_result_to_dict,
    authoritative_test_cases,
    generate_tests_with_bailian,
    infer_problem_contract,
    looks_like_corrupted_text,
    offline_test_plan,
    run_execution_debug_agent,
    solve_problem,
)


def test_agent_result_contract_has_five_steps_and_tests():
    result = solve_problem(
        AgentConfig(api_key="", enable_offline_fallback=True),
        "two sum: return indices for nums and target",
    )
    data = agent_result_to_dict(result)

    assert isinstance(result, AgentResult)
    assert len(data["agent_steps"]) == 5
    assert [step["agent_name"] for step in data["agent_steps"]] == [
        "题目识别 Agent",
        "解题规划 Agent",
        "测试生成 Agent",
        "代码生成 Agent",
        "执行调试 Agent",
    ]
    assert len(data["test_cases"]) >= 3
    assert data["retrieved_templates"]
    assert data["execution_report"]["exit_code"] == 0
    assert data["fallback_used"] is True


def test_offline_debug_agent_repairs_broken_code_and_runs_real_cases():
    _, cases = offline_test_plan("两数之和：给定 nums 和 target，返回下标")
    (
        final_code,
        report,
        repairs,
        evaluated_cases,
        api_used,
        fallback_used,
    ) = run_execution_debug_agent(
        AgentConfig(api_key="", enable_offline_fallback=True),
        "两数之和：给定 nums 和 target，返回下标",
        "def solution(:\n    pass",
        "执行基础、重复元素和无解用例",
        cases,
    )

    assert "def two_sum" in final_code
    assert "自动测试通过率：100.0%" in report
    assert repairs[0]["status"] == "passed"
    assert repairs[0]["old_code"]
    assert repairs[0]["new_code"]
    assert len(evaluated_cases) == 4
    assert all(case["passed"] for case in evaluated_cases)
    assert api_used is False
    assert fallback_used is True


def test_two_sum_contract_requires_indices_and_authoritative_cases():
    contract = infer_problem_contract(
        "给定 nums 和 target，请返回两个数之和对应的数组下标"
    )
    cases = authoritative_test_cases(contract)

    assert contract["id"] == "two_sum_indices"
    assert "list[int]" in contract["signature"]
    assert all(isinstance(case["expected"], list) for case in cases)
    assert [case["expected"] for case in cases] == [
        [0, 1],
        [1, 2],
        [0, 1],
        [],
    ]


def test_model_boolean_tests_cannot_override_two_sum_index_contract(monkeypatch):
    import ai_coding_agent_bailian as agent_module

    monkeypatch.setattr(
        agent_module,
        "call_bailian_chat",
        lambda *args, **kwargs: """
## 测试策略
错误地测试是否存在答案。
```json
[
  {"name": "错误语义", "args": [[2,7], 9], "expected": true}
]
""",
    )
    problem = "two sum: return indices for nums and target"
    contract = infer_problem_contract(problem)
    _, cases, used = generate_tests_with_bailian(
        AgentConfig(api_key="test"),
        problem,
        "使用哈希表",
        contract,
    )

    assert used is True
    assert len(cases) == 4
    assert all(isinstance(case["expected"], list) for case in cases)


def test_corrupted_text_detection():
    assert looks_like_corrupted_text("???????? nums ???? target ????????")
    assert not looks_like_corrupted_text("给定 nums 和 target，返回两个数的下标")
