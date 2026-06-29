import pytest
from sandbox.code_runner import execute_code_safely, SandboxRequest, DOCKER_AVAILABLE

def test_runner_success_timeout_and_blocking():
    success = execute_code_safely("breadth = 3\nprint(breadth)")
    assert success["status"] == "success"
    assert success["stdout"].strip() == "3"

    timeout = execute_code_safely("while True: pass", timeout_seconds=1)
    assert timeout["status"] == "timeout"
    assert timeout["exit_code"] == 124

    blocked = execute_code_safely("open('secret.txt').read()")
    assert blocked["status"] == "blocked"
    assert blocked["exit_code"] == 126

    obfuscated = execute_code_safely(
        "b=__import__('builtins'); getattr(b, 'open')('secret.txt')"
    )
    assert obfuscated["status"] == "blocked"

def test_runner_output_truncation():
    """专项测试：输出长度防爆截断"""
    req = SandboxRequest(code="print('A' * 20000)")
    res = execute_code_safely(req)
    assert res["status"] == "success"
    assert len(res["stdout"]) < 10100 
    assert "[Output Truncated" in res["stdout"]

def test_skip_static_validation_requires_force_docker():
    """专项测试：验证安全底线 - 任何尝试绕过静态检查但未开启强隔离的请求都应被拦截"""
    res = execute_code_safely(SandboxRequest(
        code="open('unsafe.txt', 'w').write('x')", # 这是一个高危动作
        skip_static_validation=True,
        force_docker=False,
    ))

    # 验证：系统必须拒绝执行并返回 system_error
    assert res["status"] == "system_error"
    assert "force_docker=True" in res["stderr"]

@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="禁网测试需要真实的 Docker 环境支持")
def test_runner_network_isolation():
    """专项测试：物理网络隔离 (断网) - 使用 skip_static_validation 强测底层 Docker"""
    
    # 静态安全拦截测试 (默认走 AST 拦截)
    req_static = SandboxRequest(code="import urllib.request\nurllib.request.urlopen('http://www.baidu.com')", network=False)
    res_static = execute_code_safely(req_static)
    assert res_static["status"] == "blocked"

    # === 核心修复 3：真实 Docker 物理断网测试 ===
    code = """
import urllib.request
try:
    urllib.request.urlopen('http://1.1.1.1', timeout=2)
except Exception as e:
    print(f"Network_Error: {type(e).__name__}")
"""
    # 加入 skip_static_validation=True，穿透第一层防御，直击 Docker
    req_physical = SandboxRequest(
        code=code, network=False, 
        force_docker=True, skip_static_validation=True
    )
    res_physical = execute_code_safely(req_physical)
    
    assert res_physical["status"] == "success" 
    assert "Network_Error" in res_physical["stdout"]

@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="OOM 测试需要真实的 Docker 资源限制支持")
def test_runner_oom_kill():
    """专项测试：内存超限 (OOM) 物理强杀"""
    code = "a = [1] * (10**8)"
    req = SandboxRequest(code=code, memory_mb=64, force_docker=True, skip_static_validation=True) 
    res = execute_code_safely(req)
    
    assert res["status"] == "failed"
    assert res["exit_code"] == 137
    assert "Memory Limit Exceeded" in res["stderr"]