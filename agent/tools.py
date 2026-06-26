"""Tool registry with schema validation and trace persistence."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


ToolHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    timeout_seconds: int
    failure_policy: str
    handler: ToolHandler


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def validate_schema(payload: Dict[str, Any], schema: Dict[str, Any], *, label: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    for key in required:
        if key not in payload:
            raise ValueError(f"{label}.{key} is required")
    for key, value in payload.items():
        if key not in properties:
            raise ValueError(f"{label}.{key} is not allowed")
        expected = properties[key].get("type")
        if expected and not _type_matches(value, expected):
            raise ValueError(f"{label}.{key} must be {expected}")


class ToolRegistry:
    def __init__(self, trace_id: str = "", persist: bool = True):
        self.trace_id = trace_id
        self.persist = persist
        self.tools: Dict[str, ToolDefinition] = {}
        self.calls: list[Dict[str, Any]] = []

    def register(self, tool: ToolDefinition) -> None:
        if not tool.name:
            raise ValueError("tool name is required")
        self.tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        if name not in self.tools:
            raise KeyError(f"unknown tool: {name}")
        return self.tools[name]

    def call(self, name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.get(name)
        validate_schema(tool_input, tool.input_schema, label=f"{name}.input")
        start = time.time()
        status = "success"
        error = ""
        try:
            output = tool.handler(tool_input)
            if not isinstance(output, dict):
                raise ValueError(f"{name} output must be an object")
            validate_schema(output, tool.output_schema, label=f"{name}.output")
        except Exception as exc:
            status = "failed"
            error = str(exc)
            output = {"ok": False, "error": error}
            if tool.failure_policy == "raise":
                self._record_call(name, tool_input, output, start, status, error)
                raise
        self._record_call(name, tool_input, output, start, status, error)
        return output

    def _record_call(
        self,
        name: str,
        tool_input: Dict[str, Any],
        output: Dict[str, Any],
        start: float,
        status: str,
        error: str,
    ) -> None:
        end = time.time()
        record = {
            "trace_id": self.trace_id,
            "tool_name": name,
            "input": tool_input,
            "output": output,
            "status": status,
            "error": error,
            "duration_ms": int((end - start) * 1000),
        }
        self.calls.append(record)
        if self.persist and self.trace_id:
            try:
                from backend.database import insert_tool_call, utc_now

                started = utc_now()
                insert_tool_call(
                    trace_id=self.trace_id,
                    tool_name=name,
                    tool_input=tool_input,
                    tool_output=output,
                    start_time=started,
                    end_time=utc_now(),
                    duration_ms=record["duration_ms"],
                    status=status,
                    error_message=error,
                )
            except Exception:
                pass

    def summary(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "tool_count": len(self.tools),
            "registered_tools": sorted(self.tools),
            "call_count": len(self.calls),
            "calls": self.calls,
        }


def _rag_search_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    from .rag import hybrid_retrieve

    results = hybrid_retrieve(payload.get("problem", ""), top_k=payload.get("top_k", 5))
    return {"ok": True, "results": results}


def _code_execute_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from sandbox.code_runner import execute_code_safely

        result = execute_code_safely(
            payload.get("code", ""),
            task_id="tool_registry",
            timeout_seconds=int(payload.get("timeout_seconds", 8)),
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _test_evaluate_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from sandbox.evaluator import run_auto_tests

        result = run_auto_tests(
            payload.get("code", ""),
            payload.get("test_cases", []),
            task_id="tool_registry_eval",
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _report_generate_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    report = str(payload.get("report", ""))
    return {"ok": True, "report": report, "length": len(report)}


def _history_lookup_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    from .rag import retrieve_history_successes

    results = retrieve_history_successes(payload.get("problem", ""), limit=payload.get("limit", 5))
    return {"ok": True, "results": results}


def _cache_lookup_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    key = payload.get("key", "")
    try:
        from backend.database import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT cache_value FROM cache_entries WHERE cache_key=? ORDER BY id DESC LIMIT 1",
                (key,),
            ).fetchone()
        if row:
            value = row["cache_value"] if hasattr(row, "keys") else row[0]
            try:
                value = json.loads(value)
            except Exception:
                pass
            return {"ok": True, "hit": True, "value": value}
    except Exception:
        pass
    return {"ok": True, "hit": False, "value": None}


def create_default_registry(trace_id: str = "", persist: bool = True) -> ToolRegistry:
    registry = ToolRegistry(trace_id=trace_id, persist=persist)
    registry.register(
        ToolDefinition(
            name="rag_search",
            description="Retrieve algorithm templates and trusted historical successes.",
            input_schema={
                "type": "object",
                "required": ["problem"],
                "properties": {"problem": {"type": "string"}, "top_k": {"type": "integer"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok", "results"],
                "properties": {"ok": {"type": "boolean"}, "results": {"type": "array"}},
            },
            timeout_seconds=3,
            failure_policy="raise",
            handler=_rag_search_handler,
        )
    )
    registry.register(
        ToolDefinition(
            name="code_execute",
            description="Run generated Python code in the local sandbox.",
            input_schema={
                "type": "object",
                "required": ["code"],
                "properties": {"code": {"type": "string"}, "timeout_seconds": {"type": "integer"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}, "result": {"type": "object"}, "error": {"type": "string"}},
            },
            timeout_seconds=8,
            failure_policy="continue",
            handler=_code_execute_handler,
        )
    )
    registry.register(
        ToolDefinition(
            name="test_evaluate",
            description="Evaluate generated code against structured test cases.",
            input_schema={
                "type": "object",
                "required": ["code", "test_cases"],
                "properties": {"code": {"type": "string"}, "test_cases": {"type": "array"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}, "result": {"type": "object"}, "error": {"type": "string"}},
            },
            timeout_seconds=8,
            failure_policy="continue",
            handler=_test_evaluate_handler,
        )
    )
    registry.register(
        ToolDefinition(
            name="report_generate",
            description="Record generated report metadata for tracing.",
            input_schema={
                "type": "object",
                "required": ["report"],
                "properties": {"report": {"type": "string"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok", "report", "length"],
                "properties": {"ok": {"type": "boolean"}, "report": {"type": "string"}, "length": {"type": "integer"}},
            },
            timeout_seconds=2,
            failure_policy="continue",
            handler=_report_generate_handler,
        )
    )
    registry.register(
        ToolDefinition(
            name="history_lookup",
            description="Lookup verified successful historical tasks only.",
            input_schema={
                "type": "object",
                "required": ["problem"],
                "properties": {"problem": {"type": "string"}, "limit": {"type": "integer"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok", "results"],
                "properties": {"ok": {"type": "boolean"}, "results": {"type": "array"}},
            },
            timeout_seconds=3,
            failure_policy="continue",
            handler=_history_lookup_handler,
        )
    )
    registry.register(
        ToolDefinition(
            name="cache_lookup",
            description="Lookup cached task or model outputs.",
            input_schema={
                "type": "object",
                "required": ["key"],
                "properties": {"key": {"type": "string"}},
            },
            output_schema={
                "type": "object",
                "required": ["ok", "hit"],
                "properties": {"ok": {"type": "boolean"}, "hit": {"type": "boolean"}, "value": {}},
            },
            timeout_seconds=1,
            failure_policy="continue",
            handler=_cache_lookup_handler,
        )
    )
    return registry
