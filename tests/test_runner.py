from sandbox.code_runner import execute_code_safely


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
