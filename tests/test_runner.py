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


# =====================================================================
# 成员 D 补充：Docker 沙盒物理隔离专项测试 (OOM、禁网、输出截断)
# =====================================================================

def test_runner_output_truncation():
    """专项测试 1：输出长度防爆截断"""
    req = SandboxRequest(code="print('A' * 20000)")
    res = execute_code_safely(req)
    
    assert res["status"] == "success"
    # 验证长度被强制截断到 10000 以内
    assert len(res["stdout"]) < 10100


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="禁网测试需要真实的 Docker 环境支持")
def test_runner_network_isolation():
    """专项测试 2：物理网络隔离 (断网)"""
    # 尝试向百度发请求
    code = """
import urllib.request
urllib.request.urlopen('http://www.baidu.com', timeout=2)
"""
    # 确保 network=False
    req = SandboxRequest(code=code, network=False)
    res = execute_code_safely(req)
    
    # 验证请求必定失败，被阻断
    assert res["status"] == "failed"
    assert "URLError" in res["stderr"] or "Name or service not known" in res["stderr"]


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="OOM 测试需要真实的 Docker 资源限制支持")
def test_runner_oom_kill():
    """专项测试 3：内存超限 (OOM) 物理强杀"""
    # 尝试分配约 800MB 内存的巨型数组，而限制只有 64MB
    code = "a = [1] * (10**8)"
    req = SandboxRequest(code=code, memory_mb=64) 
    res = execute_code_safely(req)
    
    # 验证容器被系统底层以 137 (OOM Killer) 强杀
    assert res["status"] == "failed"
    assert res["exit_code"] == 137
    assert "Memory Limit Exceeded" in res["stderr"]
