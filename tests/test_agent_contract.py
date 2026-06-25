from ai_coding_agent_bailian import (
    AgentConfig,
    AgentResult,
    agent_result_to_dict,
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
    assert len(evaluated_cases) == 3
    assert all(case["passed"] for case in evaluated_cases)
    assert api_used is False
    assert fallback_used is True
