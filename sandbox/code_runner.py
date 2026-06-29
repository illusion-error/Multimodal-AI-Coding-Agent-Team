from __future__ import annotations
import ast
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Union
from dataclasses import dataclass, asdict

# === 修复 2：严格的 Docker Daemon 可用性检测 ===
try:
    import docker
    _client = docker.from_env()
    _client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

@dataclass
class SandboxRequest:
    code: str
    language: str = "python"
    timeout: int = 8
    memory_mb: int = 256
    cpu_cores: float = 1.0
    network: bool = False
    files: Dict[str, str] = None
    force_docker: bool = False  # 新增：是否强制要求物理隔离（禁止 fallback）

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
BLOCKED_CALL_NAMES = {"__import__", "eval", "exec", "compile", "getattr", "setattr", "open", "breakpoint", "input", "globals", "locals", "vars"}
BLOCKED_ATTRIBUTES = {"chmod", "chown", "connect", "kill", "open", "popen", "remove", "removedirs", "rename", "replace", "request", "rmdir", "rmtree", "spawn", "system", "terminate", "unlink", "urlopen"}
MAX_OUTPUT_CHARS = 10000

def truncate_with_indicator(text: str, max_len: int = MAX_OUTPUT_CHARS) -> str:
    """截断文本，如果被截断则追加 [Output Truncated] 标识"""
    if len(text) <= max_len:
        return text
    return text[:max_len - 20] + "...[Output Truncated]"

class SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".", 1)[0] not in ALLOWED_IMPORT_ROOTS:
                self.violations.append(f"禁止导入模块: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (node.module or "").split(".", 1)[0] not in ALLOWED_IMPORT_ROOTS:
            self.violations.append(f"禁止导入模块: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALL_NAMES:
            self.violations.append(f"禁止调用函数: {node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_ATTRIBUTES:
            self.violations.append(f"禁止调用属性: {node.func.attr}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr not in {"__name__", "__doc__"}:
            self.violations.append(f"禁止访问属性: {node.attr}")
        self.generic_visit(node)

def validate_code(code_str: str) -> List[str]:
    try:
        tree = ast.parse(code_str)
        visitor = SafetyVisitor()
        visitor.visit(tree)
        return list(dict.fromkeys(visitor.violations))
    except SyntaxError as e:
        return [f"代码语法错误: {str(e)}"]

def execute_code_safely(request: Union[SandboxRequest, str], task_id: str = "test", **kwargs) -> Dict[str, Any]:
    if isinstance(request, str):
        request = SandboxRequest(code=request, timeout=kwargs.get("timeout_seconds", 8))
    
    start_time = time.perf_counter()
    res_usage = {"memory_mb": request.memory_mb, "cpu_cores": request.cpu_cores, "network": request.network}
    
    violations = validate_code(request.code)
    if violations:
        return asdict(SandboxResult("blocked", "", "; ".join(violations), 126, False, int((time.perf_counter()-start_time)*1000), res_usage))

    # === 修复 3：强沙盒测试不够硬 ===
    if request.force_docker and not DOCKER_AVAILABLE:
        return asdict(SandboxResult("system_error", "", "强制要求 Docker 隔离，但宿主机未检测到可用 Daemon", 1, False, 0, res_usage))

    if DOCKER_AVAILABLE:
        try:
            client = docker.from_env()
            with tempfile.TemporaryDirectory(prefix="agent_docker_") as temp_dir:
                file_path = os.path.join(temp_dir, "solution.py")
                with open(file_path, "w", encoding="utf-8") as f: f.write(request.code)
                container = client.containers.run(
                    image="python:3.10-slim", command=["python", "/app/solution.py"],
                    volumes={temp_dir: {'bind': '/app', 'mode': 'ro'}}, working_dir="/app",
                    network_disabled=not request.network, mem_limit=f"{request.memory_mb}m",
                    nano_cpus=int(request.cpu_cores * 1e9), pids_limit=32, detach=True
                )
                try:
                    exit_status = container.wait(timeout=request.timeout)
                    logs = container.logs().decode('utf-8', errors='replace')
                    duration = int((time.perf_counter() - start_time) * 1000)
                    ec = exit_status["StatusCode"]
                    stderr = logs if ec != 0 else ""
                    if ec == 137: stderr = f"Memory Limit Exceeded (OOM > {request.memory_mb}MB)"
                    stdout_text = truncate_with_indicator(logs) if ec == 0 else ""
                    stderr_text = truncate_with_indicator(stderr) if stderr else ""
                    return asdict(SandboxResult("success" if ec==0 else "failed", stdout_text, stderr_text, ec, False, duration, res_usage))
                except Exception as wait_e:
                    if "timed out" in str(wait_e).lower() or "timeout" in str(wait_e).lower() or "readtimeout" in str(wait_e).lower():
                        return asdict(SandboxResult("timeout", "", f"Execution Timeout: >{request.timeout}s", 124, True, request.timeout*1000, res_usage))
                    raise wait_e
                finally:
                    try: container.remove(force=True)
                    except: pass
        except Exception as e:
            if request.force_docker:
                return asdict(SandboxResult("system_error", "", f"Docker 运行异常: {e}", 1, False, 0, res_usage))
            pass # 如果不强求 docker，默默走本地兜底

    # 本地兜底
    with tempfile.TemporaryDirectory(prefix="fallback_") as temp_dir:
        file_path = os.path.join(temp_dir, "solution.py")
        with open(file_path, "w", encoding="utf-8") as f: f.write(request.code)
        try:
            cp = subprocess.run([sys.executable, "-I", "-B", file_path], cwd=temp_dir, capture_output=True, text=True, timeout=request.timeout)
            duration = int((time.perf_counter() - start_time) * 1000)
            stdout_text = truncate_with_indicator(cp.stdout)
            stderr_text = truncate_with_indicator(cp.stderr)
            return asdict(SandboxResult("success" if cp.returncode == 0 else "failed", stdout_text, stderr_text, cp.returncode, False, duration, res_usage))
        except subprocess.TimeoutExpired:
            return asdict(SandboxResult("timeout", "", "Execution Timeout", 124, True, int(request.timeout*1000), res_usage))
        except Exception as e:
            return asdict(SandboxResult("failed", "", str(e), 1, False, 0, res_usage))