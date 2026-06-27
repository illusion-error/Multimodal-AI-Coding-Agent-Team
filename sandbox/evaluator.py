from __future__ import annotations
import ast
import json
from typing import Any, Dict, List, Tuple
from sandbox.code_runner import execute_code_safely

RESULT_PREFIX = "__AGENT_EVAL_RESULT__="
SELF_TEST_FUNCTION_NAMES = {"_run_tests", "run_tests", "_test", "test", "main", "_main"}

def _literal(value: Any) -> Any:
    if not isinstance(value, str): return value
    try: return ast.literal_eval(value)
    except (SyntaxError, ValueError): return value

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

def _is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.If): return False
    test = node.test
    if not isinstance(test, ast.Compare): return False
    if not isinstance(test.left, ast.Name) or test.left.id != "__name__": return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq): return False
    if len(test.comparators) != 1: return False
    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value == "__main__"

def prepare_runtime_code(code_str: str) -> str:
    try: tree = ast.parse(code_str)
    except SyntaxError: return code_str
    filtered_body: List[ast.stmt] = []
    for node in tree.body:
        if _is_main_guard(node): continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in SELF_TEST_FUNCTION_NAMES: continue
        filtered_body.append(node)
    tree.body = filtered_body
    ast.fix_missing_locations(tree)
    try: return ast.unparse(tree)
    except Exception: return code_str

def _parse_result(stdout: str) -> Dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX) :])
    return {"passed": False, "actual": "", "expected": "", "error": "评测脚本没有返回结构化结果"}

def run_auto_tests(code_str: str, test_cases: List[Dict[str, Any]], *, timeout_seconds: int = 3, task_id: str = "evaluation") -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "total": len(test_cases),
        "passed": 0, "failed": 0,
        "public_passed": 0, "hidden_passed": 0,
        "hidden_total": sum(1 for c in test_cases if c.get("category") == "hidden"),
        "pass_rate": 0.0, "total_time_ms": 0, "details": [],
        "is_final_passed": False # 目标6：新增终极通过标志
    }

    for index, case in enumerate(test_cases, start=1):
        args, kwargs, expected = normalize_case(case)
        execution = execute_code_safely(build_test_script(code_str, args, kwargs, expected), task_id=f"{task_id}:{index}", timeout_seconds=timeout_seconds)
        
        payload = _parse_result(execution["stdout"]) if execution["status"] == "success" else {"passed": False, "actual": "", "expected": repr(expected), "error": execution["stderr"] or execution["status"]}
        
        passed = bool(payload.get("passed"))
        case_category = case.get("category", "public")
        
        if passed:
            report["passed"] += 1
            if case_category == "public": report["public_passed"] += 1
            if case_category == "hidden": report["hidden_passed"] += 1
        else:
            report["failed"] += 1
            
        report["total_time_ms"] += execution["duration_ms"]
        
        report["details"].append({
            "name": case.get("name", f"用例 {index}"), "category": case_category,
            "input": case.get("input", case.get("args", [])), "expected": payload.get("expected", repr(expected)),
            "actual": payload.get("actual", ""), "passed": passed, "duration_ms": execution["duration_ms"],
            "error": payload.get("error", ""), "status": execution["status"]
        })

    # 核心判断：隐藏用例全部通过才算真正的通过 (覆盖目标 6)
    if report["hidden_total"] > 0:
        report["is_final_passed"] = (report["hidden_passed"] == report["hidden_total"])
    else:
        report["is_final_passed"] = (report["passed"] == report["total"])

    if report["total"]:
        report["pass_rate"] = round(report["passed"] / report["total"] * 100, 2)
    return report