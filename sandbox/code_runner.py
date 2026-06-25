# sandbox/code_runner.py
import subprocess
import tempfile
import os
import ast
import time

def is_safe_code(code_str: str) -> tuple[bool, str]:
    """
    使用 AST (抽象语法树) 算法解析代码，精准拦截危险调用
    防止使用简单字符串匹配时误伤 'breadth' 或 'import threading' 等正常代码
    """
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"语法错误: {str(e)}"
    
    # 禁用模块
    forbidden_modules = {'os', 'subprocess', 'sys', 'shutil', 'socket', 'requests', 'urllib'}
    # 禁用内置函数
    forbidden_funcs = {'open', 'eval', 'exec', 'compile', 'globals', 'locals'}

    for node in ast.walk(tree):
        # 1. 检查 import 语句
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in forbidden_modules:
                    return False, f"禁用导入模块: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in forbidden_modules:
                return False, f"禁用导入模块: {node.module}"
        
        # 2. 检查危险函数调用
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in forbidden_funcs:
                    return False, f"禁用内置函数调用: {node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                # 拦截黑魔法双下划线调用，如 __subclasses__ 等
                if node.func.attr in {'__subclasses__', '__builtins__', 'eval', 'exec'}:
                    return False, f"禁用属性访问: {node.func.attr}"
                    
    return True, ""

def execute_code_safely(code_str: str, timeout_seconds: int = 5) -> dict:
    """
    统一返回结构的受限子进程执行器
    """
    response = {
        "status": "success",
        "stdout": "",
        "stderr": "",
        "exit_code": 0,
        "timeout": False,
        "duration_ms": 0
    }

    # 1. AST 安全检查
    is_safe, msg = is_safe_code(code_str)
    if not is_safe:
        response["status"] = "blocked"
        response["stderr"] = msg
        response["exit_code"] = 1
        return response

    # 2. 创建临时目录隔离运行
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, "solution.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_str)
        
        # 清空环境变量，防止泄露宿主机信息
        clean_env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": temp_dir}
        
        start_time = time.time()
        try:
            result = subprocess.run(
                ["python", "solution.py"],
                cwd=temp_dir,
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            response["duration_ms"] = int((time.time() - start_time) * 1000)
            response["stdout"] = result.stdout
            response["stderr"] = result.stderr
            response["exit_code"] = result.returncode
            if result.returncode != 0:
                response["status"] = "failed"
                
        except subprocess.TimeoutExpired:
            response["status"] = "timeout"
            response["timeout"] = True
            response["exit_code"] = 124
            response["stderr"] = f"执行超时（>{timeout_seconds}秒），已强制中断！"
            response["duration_ms"] = int((time.time() - start_time) * 1000)
        except Exception as e:
            response["status"] = "failed"
            response["stderr"] = f"系统执行异常: {str(e)}"
            response["exit_code"] = 1
            
    return response