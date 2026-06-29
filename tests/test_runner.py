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

# === 修复 1：将禁网测试拆分，绕过 AST 静态拦截 ===
@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="禁网测试需要真实的 Docker 环境支持")
def test_runner_network_isolation():
    """专项测试：物理网络隔离 (断网) - 使用 eval 绕过静态 AST 检查以测试真实 Docker 隔离"""
    
    # 静态安全拦截测试
    req_static = SandboxRequest(code="import urllib.request\nurllib.request.urlopen('http://www.baidu.com')", network=False)
    res_static = execute_code_safely(req_static)
    assert res_static["status"] == "blocked" # 第一类：静态拦截成功

    # 物理网络拦截测试 (黑魔法绕过 AST，强行发包)
    code = """
import urllib.request
try:
    urllib.request.urlopen('http://1.1.1.1', timeout=2)
except Exception as e:
    print(f"Network_Error: {type(e).__name__}")
"""
    # 强制不许 fallback，必须用 docker 测
    req_physical = SandboxRequest(code=code, network=False, force_docker=True)
    res_physical = execute_code_safely(req_physical)
    
    assert res_physical["status"] == "success" 
    assert "Network_Error" in res_physical["stdout"] or "URLError" in res_physical["stderr"]

@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="OOM 测试需要真实的 Docker 资源限制支持")
def test_runner_oom_kill():
    """专项测试：内存超限 (OOM) 物理强杀"""
    code = "a = [1] * (10**8)"
    req = SandboxRequest(code=code, memory_mb=64, force_docker=True) # 强制必须 Docker 执行
    res = execute_code_safely(req)
    
    assert res["status"] == "failed"
    assert res["exit_code"] == 137
    assert "Memory Limit Exceeded" in res["stderr"]