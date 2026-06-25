# sandbox/evaluator.py
import time
from .code_runner import execute_code_safely

def run_test_cases(code_str: str, test_cases: list) -> dict:
    """
    自动化测试评测机：跑测用例并输出真实指标
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
        test_script = f"""
{code_str}

try:
    # 约定大模型生成的解题函数名统一为 solution
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
        # 修复参数名：传入正确的 timeout_seconds
        sandbox_res = execute_code_safely(test_script, timeout_seconds=3)
        duration_ms = int((time.time() - start_time) * 1000)
        report["total_time_ms"] += duration_ms

        case_detail = {
            "input": case["input"],
            "expected": case["expected"],
            "duration_ms": duration_ms
        }

        if sandbox_res["status"] == "success":
            stdout = sandbox_res["stdout"].strip()
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
            case_detail["actual"] = sandbox_res["stderr"]

        report["details"].append(case_detail)

    return report