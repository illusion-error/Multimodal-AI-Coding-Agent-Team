# sandbox/evaluator.py
import time
from .code_runner import execute_code_safely  # 调用你之前写的沙盒

def run_auto_tests(code_str: str, test_cases: list) -> dict:
    """
    成员 D 开发：全自动化测试评测机
    功能：接收大模型生成的代码和测试用例，在沙盒中自动运行并出具测试报告
    """
    report = {
        "total": len(test_cases),
        "passed": 0,
        "failed": 0,
        "total_time_ms": 0,
        "details": []
    }

    for case in test_cases:
        # 将用户的解法代码与测试用例的验证逻辑拼接
        # 假设 AI 生成的函数名统一定义为 solution
        test_script = f"""
{code_str}

try:
    result = str(solution({case['input']}))
    expected = str("{case['expected']}")
    if result == expected:
        print("✅ PASS")
    else:
        print(f"❌ FAIL | 预期: {{expected}}, 实际: {{result}}")
except Exception as e:
    print(f"⚠️ ERROR | 运行时报错: {{str(e)}}")
"""
        start_time = time.time()
        # 放入你的安全沙盒执行
        sandbox_res = execute_code_safely(test_script, timeout=3)
        duration_ms = int((time.time() - start_time) * 1000)
        report["total_time_ms"] += duration_ms

        case_detail = {
            "input": case["input"],
            "expected": case["expected"],
            "duration_ms": duration_ms
        }

        # 分析沙盒输出结果
        if sandbox_res.get("status") == "success":
            stdout = sandbox_res.get("stdout", "").strip()
            if "✅ PASS" in stdout:
                report["passed"] += 1
                case_detail["status"] = "Passed"
                case_detail["actual"] = case["expected"]
            else:
                report["failed"] += 1
                case_detail["status"] = "Failed"
                case_detail["actual"] = stdout.split("|")[-1].strip() if "|" in stdout else stdout
        else:
            report["failed"] += 1
            case_detail["status"] = "Error"
            case_detail["actual"] = sandbox_res.get("stderr", "执行异常")

        report["details"].append(case_detail)

    return report