import subprocess
import tempfile
import os

def execute_code_safely(code_str: str, timeout_seconds: int = 5) -> dict:
    # 静态安全检查
    forbidden_words = ["os.system", "subprocess", "open", "read", "shutil", "__file__"]
    for word in forbidden_words:
        if word in code_str:
            return {"status": "error", "message": f"沙盒静态拦截: 代码包含高危操作汇编汇编 '{word}'"}

    # 动态沙盒隔离执行
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, "solution.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_str)
        
        # 核心修复：切断宿主机环境变量，防止代码读取系统密钥
        clean_env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": temp_dir}
        
        try:
            # 核心修复：通过 cwd 限制工作目录，使其无法使用相对路径 ../ 逃逸到根目录
            result = subprocess.run(
                ["python", "solution.py"],
                cwd=temp_dir,    
                env=clean_env,   
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            if result.returncode == 0:
                return {"status": "success", "stdout": result.stdout}
            else:
                return {"status": "failed", "stderr": result.stderr}
                
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "stderr": "运行超时，沙盒强制终止"}