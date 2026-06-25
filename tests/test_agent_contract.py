from ai_coding_agent_bailian import (
    AgentConfig,
    AgentResult,
    agent_result_to_dict,
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
