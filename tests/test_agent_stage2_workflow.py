from __future__ import annotations

import pytest

from agent.contracts import MODEL_AUTHORITY, semantic_status_from_cases
from agent.rag import RAG_TEMPLATES, hybrid_retrieve, retrieve_history_successes
from agent.state import WorkflowState, WorkflowStatus
from agent.tools import create_default_registry
from agent.workflow import AgentWorkflow, reflect_on_result


def test_workflow_state_records_required_transitions():
    state = WorkflowState(problem="two sum", trace_id="trace-unit")
    workflow = AgentWorkflow(state)

    workflow.run_node(
        "recognition",
        WorkflowStatus.RECOGNIZED,
        lambda current: {"problem": current.problem, "contract": {"id": "two_sum_indices"}},
    )
    workflow.run_node(
        "retrieval",
        WorkflowStatus.RETRIEVED,
        lambda _current: {"templates": [{"id": "hash_table"}]},
    )
    workflow.run_node(
        "planning",
        WorkflowStatus.PLANNED,
        lambda _current: {"plan": "use dict"},
    )

    assert state.status == WorkflowStatus.PLANNED
    assert [item.to_status for item in state.transitions] == [
        WorkflowStatus.RECOGNIZED,
        WorkflowStatus.RETRIEVED,
        WorkflowStatus.PLANNED,
    ]
    assert state.to_dict()["trace_id"] == "trace-unit"


def test_workflow_rejects_unknown_patch_field():
    workflow = AgentWorkflow(WorkflowState(problem="x"))

    with pytest.raises(ValueError):
        workflow.run_node(
            "bad_node",
            WorkflowStatus.RECOGNIZED,
            lambda _current: {"not_a_state_field": "bad"},
        )


def test_tool_registry_has_six_tools_and_rejects_bad_params():
    registry = create_default_registry(trace_id="trace-tools", persist=False)

    assert set(registry.tools) >= {
        "rag_search",
        "code_execute",
        "test_evaluate",
        "report_generate",
        "history_lookup",
        "cache_lookup",
    }
    assert registry.summary()["tool_count"] >= 6

    with pytest.raises(ValueError):
        registry.call("rag_search", {"top_k": 3})

    result = registry.call("rag_search", {"problem": "return indices for two sum", "top_k": 3})
    assert result["ok"] is True
    assert registry.summary()["call_count"] == 1
    assert registry.summary()["calls"][0]["trace_id"] == "trace-tools"


def test_hybrid_rag_returns_topk_scores_sources_and_rerank_reason():
    results = hybrid_retrieve(
        "Given nums and target, return the indices of two numbers whose sum is target.",
        top_k=5,
    )

    assert len(RAG_TEMPLATES) >= 20
    assert len(results) == 5
    assert results[0]["id"] == "hash_table"
    assert all("score" in item for item in results)
    assert all(item["source"] in {"template", "history"} for item in results)
    assert all(item.get("rerank_reason") for item in results)


def test_reflect_decision_categories_are_explicit():
    assert reflect_on_result(
        execution_success=False,
        semantic_status="failed",
        error_text="Traceback SyntaxError",
        problem="two sum",
    ).decision == "repair"

    manual = reflect_on_result(
        execution_success=True,
        semantic_status="manual_review",
        problem="write a small script",
    )
    assert manual.decision == "ask_user"
    assert manual.category == "untrusted_tests"

    replan = reflect_on_result(
        execution_success=True,
        semantic_status="failed",
        problem="two sum",
    )
    assert replan.decision == "replan"

    insufficient = reflect_on_result(
        execution_success=True,
        semantic_status="verified",
        problem="",
    )
    assert insufficient.decision == "ask_user"


def test_model_generated_cases_never_become_authoritative_oracle():
    model_cases = [
        {
            "name": "bad model expectation",
            "expected": "generated fallback",
            "passed": True,
            "authority": MODEL_AUTHORITY,
            "trusted": False,
        }
    ]

    assert semantic_status_from_cases(model_cases) == "manual_review"
    decision = reflect_on_result(
        execution_success=True,
        semantic_status=semantic_status_from_cases(model_cases),
        problem="print hello world",
    )
    assert decision.decision == "ask_user"
    assert decision.category == "untrusted_tests"


def test_history_rag_only_indexes_verified_authoritative_successes():
    from backend.database import create_task

    create_task(
        "verified-history",
        "completed",
        {
            "problem": "two sum return indices for nums and target",
            "metrics": {
                "semantic_verification_status": "verified",
                "trusted_test_count": 3,
            },
            "code": "def solution(nums, target): return [0, 1]",
        },
        problem="two sum return indices for nums and target",
    )
    create_task(
        "manual-history",
        "completed",
        {
            "problem": "two sum return indices for nums and target",
            "metrics": {
                "semantic_verification_status": "manual_review",
                "trusted_test_count": 0,
            },
            "code": "def solution(*args): return True",
        },
        problem="two sum return indices for nums and target",
    )
    create_task(
        "failed-history",
        "failed",
        {
            "problem": "two sum return indices for nums and target",
            "metrics": {
                "semantic_verification_status": "failed",
                "trusted_test_count": 3,
            },
            "code": "def solution(*args): return []",
        },
        problem="two sum return indices for nums and target",
    )

    results = retrieve_history_successes("two sum return indices for nums and target")

    assert [item["id"] for item in results] == ["history:verified-history"]
