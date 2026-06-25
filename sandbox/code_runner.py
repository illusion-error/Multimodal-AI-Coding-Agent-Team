from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List


ALLOWED_IMPORT_ROOTS = {
    "bisect",
    "collections",
    "dataclasses",
    "decimal",
    "fractions",
    "functools",
    "heapq",
    "itertools",
    "json",
    "math",
    "operator",
    "re",
    "statistics",
    "string",
    "typing",
}
BLOCKED_CALL_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
BLOCKED_ATTRIBUTES = {
    "chmod",
    "chown",
    "connect",
    "kill",
    "open",
    "popen",
    "remove",
    "removedirs",
    "rename",
    "replace",
    "request",
    "rmdir",
    "rmtree",
    "spawn",
    "system",
    "terminate",
    "unlink",
    "urlopen",
}
MAX_OUTPUT_CHARS = 100_000


class SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                self.violations.append(f"禁止导入模块: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if not root or root not in ALLOWED_IMPORT_ROOTS:
            self.violations.append(f"禁止导入模块: {node.module or '(relative)'}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALL_NAMES:
            self.violations.append(f"禁止调用函数: {node.func.id}")
        if isinstance(node.func, ast.Attribute):
            attribute = node.func.attr
            if attribute in BLOCKED_ATTRIBUTES or attribute.startswith("__"):
                self.violations.append(f"禁止调用属性: {attribute}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self.violations.append(f"禁止访问属性: {node.attr}")
        self.generic_visit(node)


def validate_code(code_str: str) -> List[str]:
    try:
        tree = ast.parse(code_str)
    except SyntaxError as exc:
        return [f"代码语法错误: {exc.msg} (line {exc.lineno})"]
    visitor = SafetyVisitor()
    visitor.visit(tree)
    return list(dict.fromkeys(visitor.violations))


def _result(
    *,
    status: str,
    task_id: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = -1,
    timeout: bool = False,
    duration_ms: int = 0,
) -> Dict[str, Any]:
    return {
        "status": status,
        "task_id": task_id,
        "stdout": stdout[:MAX_OUTPUT_CHARS],
        "stderr": stderr[:MAX_OUTPUT_CHARS],
        "exit_code": exit_code,
        "timeout": timeout,
        "duration_ms": duration_ms,
    }


def execute_code_safely(
    code_str: str,
    task_id: str = "test",
    timeout_seconds: int = 5,
) -> Dict[str, Any]:
    """Execute algorithm code in a restricted local subprocess.

    This is a first-stage constrained runner, not a security boundary. The
    second-stage deployment uses a Docker/E2B sandbox for OS-level isolation.
    """

    started = time.perf_counter()
    violations = validate_code(code_str)
    if violations:
        return _result(
            status="blocked",
            task_id=task_id,
            stderr="; ".join(violations),
            exit_code=126,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    with tempfile.TemporaryDirectory(prefix="coding_agent_") as temp_dir:
        script_path = os.path.join(temp_dir, "solution.py")
        with open(script_path, "w", encoding="utf-8", newline="\n") as file:
            file.write(code_str)

        clean_env = {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PATH": os.path.dirname(sys.executable),
        }
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-B", script_path],
                cwd=temp_dir,
                env=clean_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout_seconds)),
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            return _result(
                status="timeout",
                task_id=task_id,
                stdout=stdout,
                stderr=stderr or f"执行超过 {timeout_seconds} 秒，已终止。",
                exit_code=124,
                timeout=True,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return _result(
                status="failed",
                task_id=task_id,
                stderr=f"{type(exc).__name__}: {exc}",
                exit_code=1,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    status = "success" if completed.returncode == 0 else "failed"
    return _result(
        status=status,
        task_id=task_id,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        exit_code=completed.returncode,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
