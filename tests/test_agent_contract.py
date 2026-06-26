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
    validate_model_test_cases,
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


def test_hello_world_has_locked_contract_and_authoritative_expected_value():
    result = solve_problem(
        AgentConfig(api_key="", enable_offline_fallback=True),
        "write a simple hello world script",
    )

    contract = result.metrics["problem_contract"]
    assert contract["id"] == "hello_world"
    assert contract["signature"] == "solution() -> str"
    assert contract["fingerprint"]
    assert result.metrics["semantic_verification_status"] == "verified"
    assert len(result.test_cases) == 1
    assert result.test_cases[0]["source"] == "system_authoritative"
    assert result.test_cases[0]["trusted"] is True
    assert result.test_cases[0]["expected"] == "'Hello, World!'"
    assert result.test_cases[0]["actual"] == "'Hello, World!'"
    assert result.test_cases[0]["passed"] is True
    assert result.repair_attempts == []


def test_authoritative_evaluator_ignores_model_written_self_tests():
    problem = "write a simple hello world script"
    contract = infer_problem_contract(problem)
    cases = authoritative_test_cases(contract)
    code = '''
def solution():
    return "Hello, World!"


def _run_tests():
    result = solution()
    assert result == "Hello, World!", f"Expected str, got {type(result).__name__}"


if __name__ == "__main__":
    _run_tests()
'''

    (
        final_code,
        report,
        repairs,
        evaluated_cases,
        api_used,
        fallback_used,
    ) = run_execution_debug_agent(
        AgentConfig(api_key="", enable_offline_fallback=True),
        problem,
        code,
        "trusted hello world case",
        cases,
        contract,
    )

    assert final_code == code
    assert "自动测试通过率：100.0%" in report
    assert repairs == []
    assert len(evaluated_cases) == 1
    assert evaluated_cases[0]["passed"] is True
    assert api_used is False
    assert fallback_used is False


def test_placeholder_expected_is_rejected_for_generic_contract():
    contract = infer_problem_contract("implement a custom transformation")
    accepted, rejected = validate_model_test_cases(
        [
            {
                "name": "bad fallback",
                "args": [],
                "expected": "已生成兜底代码：请根据题目补充核心算法逻辑。",
                "contract_id": contract["id"],
                "contract_fingerprint": contract["fingerprint"],
            }
        ],
        contract,
    )

    assert accepted == []
    assert any("占位文本" in message for message in rejected)


def test_generic_model_cases_are_advisory_and_cannot_trigger_repair(monkeypatch):
    import ai_coding_agent_bailian as agent_module

    contract = infer_problem_contract("implement a custom transformation")
    monkeypatch.setattr(
        agent_module,
        "call_bailian_chat",
        lambda *args, **kwargs: f"""
## 测试策略
模型建议。
```json
[
  {{
    "name": "建议用例",
    "args": [],
    "expected": "wrong expected",
    "contract_id": "{contract["id"]}",
    "contract_fingerprint": "{contract["fingerprint"]}"
  }}
]
```
""",
    )
    _, cases, _ = generate_tests_with_bailian(
        AgentConfig(api_key="test"),
        "implement a custom transformation",
        "custom plan",
        contract,
    )

    assert len(cases) == 1
    assert cases[0]["source"] == "model_advisory"
    assert cases[0]["trusted"] is False

    code = """
def solution():
    return "correct result"

if __name__ == "__main__":
    print(solution())
"""
    final_code, report, repairs, evaluated, _, _ = run_execution_debug_agent(
        AgentConfig(api_key="test"),
        "implement a custom transformation",
        code,
        "custom plan",
        cases,
        contract,
    )
    assert final_code == code
    assert "需人工确认" in report
    assert repairs == []
    assert evaluated == []


def test_corrupted_text_detection():
    assert looks_like_corrupted_text("???????? nums ???? target ????????")
    assert not looks_like_corrupted_text("给定 nums 和 target，返回两个数的下标")
