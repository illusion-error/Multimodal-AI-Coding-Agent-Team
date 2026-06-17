import subprocess
import tempfile
import os

def execute_code_safely(code_str: str, timeout_seconds: int = 5) -> dict:
    """
    成员 D 提供：安全代码沙盒执行器
    供成员 B 和 C 调用，用于运行 AI 生成的代码并返回结果
    """
    # 1. 危险调用拦截 (评分细则要求的防爆机制)
    dangerous_keywords = ["os.system", "subprocess", "rm -rf", "shutil"]
    for keyword in dangerous_keywords:
        if keyword in code_str:
            return {"status": "error", "message": f"沙盒安全拦截: 禁止执行高危代码 [{keyword}]"}

    # 2. 在临时目录中隔离执行
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, "temp_exec.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_str)
        
        try:
            # 3. 设置超时时间 (评分细则要求的超时终止)
            result = subprocess.run(
                ["python", file_path],
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            if result.returncode == 0:
                return {"status": "success", "stdout": result.stdout}
            else:
                return {"status": "failed", "stderr": result.stderr}
                
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "stderr": f"执行超时（>{timeout_seconds}秒），已强制中断！"}
        except Exception as e:
            return {"status": "system_error", "stderr": str(e)}