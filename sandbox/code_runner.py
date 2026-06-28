from __future__ import annotations
import os, tempfile, time, sys, subprocess, ast, docker
from typing import Any, Dict, List, Union
from dataclasses import dataclass, asdict

@dataclass
class SandboxRequest:
    code: str
    language: str = "python"
    timeout: int = 8
    memory_mb: int = 256
    cpu_cores: float = 1.0
    network: bool = False
    files: Dict[str, str] = None

@dataclass
class SandboxResult:
    status: str
    stdout: str
    stderr: str
    exit_code: int
    timeout: bool
    duration_ms: int
    resource_usage: Dict[str, Any]

MAX_OUTPUT_CHARS = 10000

# === 核心修复：找回最严厉的黑名单，拦截混淆调用 ===
BLOCKED_CALL_NAMES = {
    "__import__", "eval", "exec", "compile", "getattr", "setattr", 
    "open", "breakpoint", "input", "globals", "locals", "vars"
}

class SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: List[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        # 拦截直接调用，如 __import__('builtins')
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALL_NAMES:
            self.violations.append(f"禁止调用危险函数: {node.func.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # 拦截魔术属性，放行 __name__ 和 __doc__
        if node.attr.startswith("__") and node.attr not in {"__name__", "__doc__"}:
            self.violations.append(f"禁止访问敏感属性: {node.attr}")
        self.generic_visit(node)

def validate_code(code_str: str) -> List[str]:
    try:
        tree = ast.parse(code_str)
        visitor = SafetyVisitor()
        visitor.visit(tree)
        return visitor.violations
    except SyntaxError as e:
        return [f"代码语法错误: {str(e)}"]

def execute_code_safely(request: Union[SandboxRequest, str], task_id: str = "test", **kwargs) -> Dict[str, Any]:
    if isinstance(request, str):
        request = SandboxRequest(code=request, timeout=kwargs.get("timeout_seconds", 8))
    
    start_time = time.perf_counter()
    res_usage = {"memory_mb": request.memory_mb, "cpu_cores": request.cpu_cores, "network": request.network}
    
    # 1. 静态拦截：这次能精准识别 __import__ 和 getattr
    v = validate_code(request.code)
    if v:
        return asdict(SandboxResult("blocked", "", "; ".join(v), 126, False, 0, res_usage))

    # 2. 尝试 Docker
    try:
        client = docker.from_env()
        client.ping()
        with tempfile.TemporaryDirectory(prefix="agent_exec_") as temp_dir:
            file_path = os.path.join(temp_dir, "solution.py")
            with open(file_path, "w", encoding="utf-8") as f: f.write(request.code)
            container = client.containers.run(
                image="python:3.10-slim", command=["python", "/app/solution.py"],
                volumes={temp_dir: {'bind': '/app', 'mode': 'ro'}}, working_dir="/app",
                network_disabled=not request.network, mem_limit=f"{request.memory_mb}m",
                nano_cpus=int(request.cpu_cores * 1e9), pids_limit=32, detach=True
            )
            try:
                s = container.wait(timeout=request.timeout)
                logs = container.logs().decode('utf-8', errors='replace')
                ec = s["StatusCode"]
                return asdict(SandboxResult("success" if ec==0 else "failed", logs[:MAX_OUTPUT_CHARS], logs[:MAX_OUTPUT_CHARS] if ec!=0 else "", ec, False, int((time.perf_counter()-start_time)*1000), res_usage))
            finally:
                try: container.remove(force=True)
                except: pass
    except Exception:
        # 3. 兜底本地子进程
        with tempfile.TemporaryDirectory(prefix="fallback_") as temp_dir:
            file_path = os.path.join(temp_dir, "solution.py")
            with open(file_path, "w", encoding="utf-8") as f: f.write(request.code)
            try:
                cp = subprocess.run([sys.executable, "-I", "-B", file_path], cwd=temp_dir, capture_output=True, text=True, timeout=request.timeout)
                st = "success" if cp.returncode == 0 else "failed"
                return asdict(SandboxResult(st, cp.stdout[:MAX_OUTPUT_CHARS], cp.stderr[:MAX_OUTPUT_CHARS], cp.returncode, False, int((time.perf_counter()-start_time)*1000), res_usage))
            except subprocess.TimeoutExpired:
                return asdict(SandboxResult("timeout", "", "Execution Timeout", 124, True, int(request.timeout*1000), res_usage))
            except Exception as e:
                return asdict(SandboxResult("failed", "", str(e), 1, False, 0, res_usage))