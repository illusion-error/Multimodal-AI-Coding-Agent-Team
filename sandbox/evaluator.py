from __future__ import annotations
import ast
import json
from typing import Any, Dict, List, Tuple
from sandbox.code_runner import execute_code_safely, SandboxRequest

RESULT_PREFIX = "__AGENT_EVAL_RESULT__="
SELF_TEST_FUNCTION_NAMES = {"_run_tests", "run_tests", "_test", "test", "main", "_main"}

def _literal(value: Any) -> Any:
    if not isinstance(value, str): return value
    try: return ast.literal_eval(value)
    except: return value

def normalize_case(case: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Any], Any]:
    if "args" in case: args = list(case.get("args") or [])
    else:
        raw_input = case.get("input", "")
        parsed = _literal(raw_input)
        args = list(parsed) if isinstance(parsed, tuple) else [parsed]
    kwargs = dict(case.get("kwargs") or {})
    expected = _literal(case.get("expected"))
    return args, kwargs, expected

def build_test_script(code_str: str, args: List[Any], kwargs: Dict[str, Any], expected: Any) -> str:
    runtime_code = prepare_runtime_code(code_str)
    return f"""
{runtime_code}
import json as _agent_json
try:
    _agent_actual = solution(*{args!r}, **{kwargs!r})
    _agent_expected = {expected!r}
    _agent_payload = {{"passed": _agent_actual == _agent_expected, "actual": repr(_agent_actual), "expected": repr(_agent_expected), "error": ""}}
except Exception as _agent_exc:
    _agent_payload = {{"passed": False, "actual": "", "expected": repr({expected!r}), "error": str(_agent_exc)}}
print("{RESULT_PREFIX}" + _agent_json.dumps(_agent_payload, ensure_ascii=False))
""".strip()

def prepare_runtime_code(code_str: str) -> str:
    try:
        tree = ast.parse(code_str)
        tree.body = [n for n in tree.body if not (isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__")]
        return ast.unparse(tree)
    except: return code_str

def _parse_result(stdout: str) -> Dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(RESULT_PREFIX): return json.loads(line[len(RESULT_PREFIX) :])
    return {"passed": False, "error": "No result from script"}

def run_auto_tests(code_str: str, test_cases: List[Dict[str, Any]], *, timeout_seconds: int = 3, task_id: str = "evaluation") -> Dict[str, Any]:
    report = {"total": len(test_cases), "passed": 0, "failed": 0, "pass_rate": 0.0, "total_time_ms": 0, "details": [], "is_final_passed": False, "hidden_passed": 0, "hidden_total": sum(1 for c in test_cases if c.get("category") == "hidden")}
    
    for index, case in enumerate(test_cases, start=1):
        args, kwargs, expected = normalize_case(case)
        req = SandboxRequest(code=build_test_script(code_str, args, kwargs, expected), timeout=timeout_seconds)
        execution = execute_code_safely(req, task_id=f"{task_id}:{index}")
        payload = _parse_result(execution["stdout"]) if execution["status"] == "success" else {"passed": False, "error": execution["stderr"]}
        
        case_passed = bool(payload.get("passed"))
        cat = case.get("category", "public")
        if case_passed:
            report["passed"] += 1
            if cat == "hidden": report["hidden_passed"] += 1
        else: report["failed"] += 1
        
        report["total_time_ms"] += execution.get("duration_ms", 0)
        
        # 核心找回：提供绝对全量的字段，防止任何 KeyError
        report["details"].append({
            "name": case.get("name", f"用例 {index}"),
            "input": case.get("input", case.get("args", [])),
            "args": args, "kwargs": kwargs,
            "expected": payload.get("expected", repr(expected)),
            "actual": payload.get("actual", ""),
            "passed": case_passed,
            "category": cat,
            "purpose": case.get("purpose", ""),
            "source": case.get("source", "system_authoritative"), # 关键恢复
            "trusted": bool(case.get("trusted", True)),           # 关键恢复
            "validation_status": case.get("validation_status", "verified"),
            "contract_id": case.get("contract_id", ""),
            "contract_fingerprint": case.get("contract_fingerprint", ""),
            "duration_ms": execution.get("duration_ms", 0),
            "error": payload.get("error", ""),
            "status": execution.get("status", "unknown"),
        })

    if report["hidden_total"] > 0: report["is_final_passed"] = (report["hidden_passed"] == report["hidden_total"])
    else: report["is_final_passed"] = (report["passed"] == report["total"])
    if report["total"]: report["pass_rate"] = round(report["passed"] / report["total"] * 100, 2)
    return report