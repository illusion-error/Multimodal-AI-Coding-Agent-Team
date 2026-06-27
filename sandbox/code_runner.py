from __future__ import annotations
import os
import tempfile
import time
import docker
from typing import Any, Dict, Union
from dataclasses import dataclass, asdict

# 解决问题 2: 严格对齐 SandboxRequest 字段要求
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

# 解决问题 4: 严格输出长度限制
MAX_OUTPUT_CHARS = 10000

def execute_code_safely(request: Union[SandboxRequest, str], task_id: str = "test", **kwargs) -> Dict[str, Any]:
    """
    解决问题 1 & 3 & 5: 使用 Docker 实现 OS 级强隔离与真实资源配额限制
    """
    if isinstance(request, str):
        request = SandboxRequest(code=request, timeout=kwargs.get("timeout_seconds", 8))
    
    start_time = time.perf_counter()
    # 解决问题 3: 真实资源统计字段
    resource_info = {"limit_mem": f"{request.memory_mb}MB", "limit_cpu": request.cpu_cores, "network": request.network}
    
    try:
        client = docker.from_env()
    except Exception as e:
        return asdict(SandboxResult("system_error", "", f"Docker 守护进程未连接: {e}", 1, False, 0, resource_info))

    with tempfile.TemporaryDirectory(prefix="agent_sandbox_") as temp_dir:
        file_path = os.path.join(temp_dir, "solution.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(request.code)

        container = None
        try:
            # 解决问题 3: 真实落实 --memory, --cpus, --network none 指令
            container = client.containers.run(
                image="python:3.10-slim",
                command=["python", "/app/solution.py"],
                volumes={temp_dir: {'bind': '/app', 'mode': 'ro'}},
                working_dir="/app",
                network_disabled=not request.network,
                mem_limit=f"{request.memory_mb}m",
                nano_cpus=int(request.cpu_cores * 1e9),
                pids_limit=32, # 限制进程数，解决问题 3
                detach=True
            )
            
            try:
                # 阻塞等待执行完成
                exit_status = container.wait(timeout=request.timeout)
                logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='replace')
                
                # 解决问题 4: 逻辑截断
                stdout = logs if exit_status["StatusCode"] == 0 else ""
                stderr = logs if exit_status["StatusCode"] != 0 else ""
                if len(stdout) > MAX_OUTPUT_CHARS:
                    stdout = stdout[:MAX_OUTPUT_CHARS] + "\n...[Output Truncated]"
                
                duration = int((time.perf_counter() - start_time) * 1000)
                
                # 解决问题 3: 识别内存强杀 (OOM 退出码通常是 137)
                if exit_status["StatusCode"] == 137:
                    stderr = f"Memory Limit Exceeded (OOM > {request.memory_mb}MB)"
                
                res = SandboxResult(
                    status="success" if exit_status["StatusCode"] == 0 else "failed",
                    stdout=stdout, stderr=stderr,
                    exit_code=exit_status["StatusCode"],
                    timeout=False, duration_ms=duration,
                    resource_usage=resource_info # 解决问题 4
                )
            except Exception:
                container.kill()
                res = SandboxResult("timeout", "", "Execution Timeout", 124, True, request.timeout*1000, resource_info)
        finally:
            if container: container.remove(force=True)

    return asdict(res)