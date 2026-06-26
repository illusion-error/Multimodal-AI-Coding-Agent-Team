"""Traceable workflow state machine primitives."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class WorkflowStatus:
    CREATED = "created"
    RECOGNIZED = "recognized"
    RETRIEVED = "retrieved"
    PLANNED = "planned"
    TESTS_DESIGNED = "tests_designed"
    GENERATED = "generated"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"

    ALL = {
        CREATED,
        RECOGNIZED,
        RETRIEVED,
        PLANNED,
        TESTS_DESIGNED,
        GENERATED,
        EXECUTING,
        REFLECTING,
        REPAIRING,
        COMPLETED,
        FAILED,
    }


@dataclass
class WorkflowTransition:
    from_status: str
    to_status: str
    node: str
    timestamp_ms: int
    patch_keys: List[str] = field(default_factory=list)
    error: str = ""


@dataclass
class WorkflowState:
    """Mutable workflow state with patch-only updates from nodes."""

    problem: str = ""
    input_type: str = "text"
    trace_id: str = ""
    status: str = WorkflowStatus.CREATED
    contract: Dict[str, Any] = field(default_factory=dict)
    templates: List[Dict[str, Any]] = field(default_factory=list)
    plan: str = ""
    test_plan: str = ""
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    solution_markdown: str = ""
    code: str = ""
    execution_report: str = ""
    semantic_status: str = "manual_review"
    repair_attempts: List[Dict[str, Any]] = field(default_factory=list)
    reflect_decision: str = ""
    errors: List[str] = field(default_factory=list)
    transitions: List[WorkflowTransition] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def apply_patch(
        self,
        node: str,
        to_status: str,
        patch: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> None:
        """Apply a node patch and record the transition.

        Nodes are expected to return only the fields they own. Unknown fields are
        rejected so a node cannot accidentally mutate unrelated state.
        """

        if to_status not in WorkflowStatus.ALL:
            raise ValueError(f"unknown workflow status: {to_status}")
        patch = patch or {}
        allowed_fields = set(self.__dataclass_fields__.keys()) - {"transitions"}
        for key, value in patch.items():
            if key not in allowed_fields:
                raise ValueError(f"node {node} tried to patch unknown field: {key}")
            setattr(self, key, value)
        old_status = self.status
        self.status = to_status
        if error:
            self.errors.append(error)
        self.transitions.append(
            WorkflowTransition(
                from_status=old_status,
                to_status=to_status,
                node=node,
                timestamp_ms=int(time.time() * 1000),
                patch_keys=sorted(patch.keys()),
                error=error,
            )
        )

    def mark_failed(self, node: str, error: str) -> None:
        self.apply_patch(node=node, to_status=WorkflowStatus.FAILED, patch={}, error=error)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem": self.problem,
            "input_type": self.input_type,
            "trace_id": self.trace_id,
            "status": self.status,
            "semantic_status": self.semantic_status,
            "reflect_decision": self.reflect_decision,
            "error_count": len(self.errors),
            "transitions": [
                {
                    "from": item.from_status,
                    "to": item.to_status,
                    "node": item.node,
                    "timestamp_ms": item.timestamp_ms,
                    "patch_keys": item.patch_keys,
                    "error": item.error,
                }
                for item in self.transitions
            ],
        }
