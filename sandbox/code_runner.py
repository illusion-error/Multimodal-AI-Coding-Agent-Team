from __future__ import annotations
import ast
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Union
from dataclasses import dataclass, asdict

@dataclass
class SandboxRequest:
    code: str
    language: str = "python"
    timeout: int = 8
    memory_mb: int = 256
    cpu_cores: float = 1.0

@dataclass
class SandboxResult:
    status: str
    stdout: str
    stderr: str
    exit_code: int
    timeout: bool
    duration_ms: int
    resource_usage: Dict[str, Any]

ALLOWED_IMPORT_ROOTS = {"bisect", "collections", "dataclasses", "decimal", "fractions", "functools", "heapq", "itertools", "json", "math", "operator", "re", "statistics", "string", "typing"}
BLOCKED_CALL_NAMES = {"__import__", "breakpoint", "compile", "delattr", "dir", "eval", "exec", "getattr", "globals", "help", "input", "locals", "open", "setattr", "vars"}
BLOCKED_ATTRIBUTES = {"chmod", "chown", "connect", "kill", "open", "popen", "remove", "removedirs", "rename", "replace", "request", "rmdir", "rmtree", "spawn", "system", "terminate", "unlink", "urlopen"}

class SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] not in ALLOWED_IMPORT_ROOTS:
                self.violations.append(f"禁止导入模块: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (node.module or "").split(".")[0] not in ALLOWED_IMPORT_ROOTS:
            self.violations.append(f"禁止导入模块: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALL_NAMES:
            self.violations.append(f"禁止调用函数: {node.func.id}")
        if isinstance(node.func, ast.Attribute) and (node.func.attr in BLOCKED_ATTRIBUTES or node.func.attr.startswith("__")):
            self.violations.append(f"禁止调用属性: {node.func.attr}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr not in {"__name__", "__doc__"}:
            self.violations.append(f"禁止访问属性: {node.attr}")
        self.generic_visit(node)

def validate_code(code_str: str) -> List[str]:
    try:
        tree = ast.parse(code_str)
    except SyntaxError as exc:
        return [f"代码语法错误: {exc.msg}"]
    visitor = SafetyVisitor()
    visitor.visit(tree)
    return list(dict.fromkeys(visitor.violations))

def _result(*, status: str, task_id: str, stdout: str = "", stderr: str = "", exit_code: int = -1, timeout: bool = False, duration_ms: int = 0) -> Dict[str, Any]:
    return {"status": status, "task_id": task_id, "stdout": stdout, "stderr": stderr, "exit_code": exit_code, "timeout": timeout, "duration_ms": duration_ms, "resource_usage": {}}

def execute_code_safely(request: Union[SandboxRequest, str], task_id: str = "test", **kwargs) -> Dict[str, Any]:
    if isinstance(request, str):
        request = SandboxRequest(code=request, timeout=kwargs.get("timeout_seconds", 5))
    
    started = time.perf_counter()
    violations = validate_code(request.code)
    if violations:
        return _result(status="blocked", task_id=task_id, stderr="; ".join(violations), exit_code=126, duration_ms=int((time.perf_counter() - started) * 1000))

    kw = {"prefix": "coding_agent_"}
    if sys.version_info >= (3, 10): kw["ignore_cleanup_errors"] = True

    with tempfile.TemporaryDirectory(**kw) as temp_dir:
        script_path = os.path.join(temp_dir, "solution.py")
        with open(script_path, "w", encoding="utf-8") as f: f.write(request.code)
        env = {"PYTHONIOENCODING": "utf-8", "PATH": os.path.dirname(sys.executable)}
        try:
            res = subprocess.run([sys.executable, "-I", "-B", script_path], cwd=temp_dir, env=env, capture_output=True, text=True, timeout=request.timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            duration = int((time.perf_counter() - started) * 1000)
            return {"status": "success" if res.returncode == 0 else "failed", "task_id": task_id, "stdout": res.stdout, "stderr": res.stderr, "exit_code": res.returncode, "timeout": False, "duration_ms": duration, "resource_usage": {"memory_mb": request.memory_mb}}
        except subprocess.TimeoutExpired:
            return _result(status="timeout", task_id=task_id, exit_code=124, timeout=True, duration_ms=int((time.perf_counter() - started) * 1000))
        except Exception as e:
            return _result(status="failed", task_id=task_id, stderr=str(e), duration_ms=0)