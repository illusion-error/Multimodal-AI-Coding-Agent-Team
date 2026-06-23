import subprocess
import tempfile
import os

def execute_code_safely(code_str: str, task_id: str = "test", timeout_seconds: int = 5) -> dict:
    """
    成员 D 提供：符合文档 P14 (execution_logs) 标准的终极沙盒
    不仅执行代码，还将输出严格格式化，方便 B 成员直接存入数据库
    """
    log_record = {
        "task_id": task_id,
        "code_version": 1,
        "stdout": "",
        "stderr": "",
        "exit_code": -1,
        "timeout": False
    }

    # 1. 危险调用拦截 (危险调用拦截)
    forbidden = ["os.system", "subprocess", "rm -rf", "shutil"]
    for word in forbidden:
        if word in code_str:
            log_record["stderr"] = f"危险调用拦截: 包含禁用关键字 [{word}]"
            log_record["exit_code"] = 1
            return log_record

    # 2. 隔离执行
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, "temp_exec.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_str)
        
        try:
            result = subprocess.run(
                ["python", file_path],
                capture_output=True, text=True, timeout=timeout_seconds
            )
            log_record["stdout"] = result.stdout
            log_record["stderr"] = result.stderr
            log_record["exit_code"] = result.returncode
            
        except subprocess.TimeoutExpired:
            log_record["timeout"] = True
            log_record["stderr"] = f"执行超时（>{timeout_seconds}秒），已强制中断！"
            log_record["exit_code"] = 124
        except Exception as e:
            log_record["stderr"] = f"系统执行异常: {str(e)}"
            log_record["exit_code"] = 1
            
    return log_record

if __name__ == "__main__":
    # 测试一下完美输出
    print("沙盒拦截测试:", execute_code_safely("import os\nos.system('dir')"))
    print("沙盒超时测试:", execute_code_safely("while True: pass", timeout_seconds=2))
    print("沙盒正常测试:", execute_code_safely("print('Hello World')"))