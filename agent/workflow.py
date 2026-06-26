"""Workflow orchestration and reflection decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .state import WorkflowState, WorkflowStatus


ALLOWED_REFLECT_DECISIONS = {"pass", "repair", "replan", "ask_user", "stop"}


@dataclass
class ReflectDecision:
    decision: str
    reason: str
    category: str

    def to_dict(self) -> Dict[str, str]:
        return {"decision": self.decision, "reason": self.reason, "category": self.category}


def reflect_on_result(
    *,
    execution_success: bool,
    semantic_status: str,
    error_text: str = "",
    repair_attempt_count: int = 0,
    max_repairs: int = 3,
    problem: str = "",
) -> ReflectDecision:
    """Choose the next action without fabricating test expectations."""

    text = (error_text or "").lower()
    if repair_attempt_count >= max_repairs and not execution_success:
        return ReflectDecision("stop", "repair limit reached", "repair_limit")
    if not (problem or "").strip():
        return ReflectDecision("ask_user", "problem statement is empty or insufficient", "insufficient_problem")
    if semantic_status == "manual_review":
        return ReflectDecision("ask_user", "no authoritative oracle is available", "untrusted_tests")
    if semantic_status == "failed":
        if execution_success:
            return ReflectDecision("replan", "code ran but authoritative semantic tests failed", "semantic_mismatch")
        return ReflectDecision("repair", "code failed authoritative tests or execution", "code_error")
    if not execution_success:
        if any(token in text for token in ["syntaxerror", "traceback", "exception", "nameerror", "typeerror", "timeout"]):
            return ReflectDecision("repair", "runtime or syntax error detected", "code_error")
        return ReflectDecision("repair", "execution failed", "code_error")
    return ReflectDecision("pass", "execution and semantic checks are acceptable", "success")


class AgentWorkflow:
    """Small patch-based node runner for compatibility and tests."""

    def __init__(self, state: Optional[WorkflowState] = None):
        self.state = state or WorkflowState()

    def run_node(
        self,
        name: str,
        to_status: str,
        func: Callable[[WorkflowState], Dict[str, Any]],
    ) -> WorkflowState:
        try:
            patch = func(self.state)
            if not isinstance(patch, dict):
                raise TypeError(f"node {name} must return a patch dict")
            self.state.apply_patch(name, to_status, patch)
        except Exception as exc:
            if to_status == WorkflowStatus.REPAIRING:
                self.state.mark_failed(name, str(exc))
            else:
                self.state.mark_failed(name, str(exc))
            raise
        return self.state
