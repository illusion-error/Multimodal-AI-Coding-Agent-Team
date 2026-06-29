from __future__ import annotations

import sys  
from pathlib import Path  

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  

import io
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from ai_coding_agent_bailian import (  # noqa: E402
    AgentConfig,
    agent_result_to_dict,
    looks_like_corrupted_text,
    solve_problem,
)
from backend.database import (  # noqa: E402
    create_task,
    get_execution_logs_by_task,
    get_latest_benchmark_results,
    get_steps_by_task,
    get_task_by_id,
    get_tests_by_task,
    init_db,
    list_all_tasks,
    calc_metrics,
    replace_task_artifacts,
    update_task,
    generate_trace_id,          
    get_trace_by_trace_id,      
    get_task_by_task_id_for_trace,  
    insert_trace_node,          
    insert_tool_call,
    save_recognition_cache,
    get_recognition_cache,
    save_rag_cache,
    get_rag_cache,
)


APP_VERSION = "1.1.0"
AGENT_AVAILABLE = True
AGENT_IMPORT_ERROR = ""
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", str(25_000_000)))


def _allowed_origins() -> list[str]:
    value = os.getenv(
        "ALLOW_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # ===== 新增：启动时恢复中断的任务 =====
    from backend.database import recover_tasks
    recover_tasks()
    print("[INFO] 已执行任务恢复检查")
    # ===== 新增结束 =====
    # 启动后台 Worker
    from backend.worker import start_worker
    start_worker()
    print("AI Coding Agent API started")
    print(f"Agent module loaded: {AGENT_AVAILABLE}")
    print(f"Database path: {os.getenv('DATABASE_PATH', 'backend/data/tasks.db')}")
    yield
    # 关闭时停止 Worker
    from backend.worker import stop_worker
    stop_worker()


app = FastAPI(title="AI Coding Agent API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 新增：统一错误码 =====
ERROR_CODES = {
    400: {"code": 400, "message": "请求参数错误"},
    404: {"code": 404, "message": "资源不存在"},
    409: {"code": 409, "message": "资源冲突"},
    429: {"code": 429, "message": "请求过于频繁，请稍后再试"},
    500: {"code": 500, "message": "服务器内部错误"},
}

app = FastAPI(title="AI Coding Agent API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 新增：统一错误码 =====
ERROR_CODES = {
    400: {"code": 400, "message": "请求参数错误"},
    404: {"code": 404, "message": "资源不存在"},
    409: {"code": 409, "message": "资源冲突"},
    429: {"code": 429, "message": "请求过于频繁，请稍后再试"},
    500: {"code": 500, "message": "服务器内部错误"},
}


from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一处理 HTTP 异常"""
    error_info = ERROR_CODES.get(exc.status_code, ERROR_CODES.get(500))
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail or error_info["message"],
            "data": None
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """统一处理参数验证异常"""
    return JSONResponse(
        status_code=400,
        content={
            "code": 400,
            "message": "请求参数验证失败",
            "data": None
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """统一处理未捕获的异常"""
    import traceback
    print(f"[ERROR] 未捕获异常: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误，请稍后重试",
            "data": None
        }
    )


def error_response(code: int, message: str = "") -> dict:
    """统一错误响应格式"""
    error_info = ERROR_CODES.get(code, ERROR_CODES[500])
    return {
        "code": code,
        "message": message or error_info["message"],
        "data": None
    }
# ===== 新增结束 =====

# ===== 新增：简单内存限流器 =====
class RateLimiter:
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        """
        max_requests: 时间窗口内最大请求数
        time_window: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.records: Dict[str, List[float]] = {}
    
    def is_allowed(self, key: str) -> bool:
        """检查是否允许请求"""
        import time
        now = time.time()
        
        if key not in self.records:
            self.records[key] = []
        
        # 清理过期记录
        self.records[key] = [t for t in self.records[key] if now - t < self.time_window]
        
        if len(self.records[key]) >= self.max_requests:
            return False
        
        self.records[key].append(now)
        return True
    
    def get_remaining(self, key: str) -> int:
        """获取剩余请求次数"""
        import time
        now = time.time()
        
        if key not in self.records:
            return self.max_requests
        
        self.records[key] = [t for t in self.records[key] if now - t < self.time_window]
        return max(0, self.max_requests - len(self.records[key]))

# 全局限流器：每个 IP 每分钟最多 30 次请求
rate_limiter = RateLimiter(max_requests=30, time_window=60)
# ===== 新增结束 =====

class TaskRequest(BaseModel):
    problem_text: str = Field(min_length=1, max_length=20_000)


def api_response(data: Any = None, message: str = "success", code: int = 0) -> dict:
    return {"code": code, "message": message, "data": data}


def normalize_request_api_key(value: str) -> str:
    api_key = value.strip()
    if len(api_key) > 512 or any(ord(char) < 32 for char in api_key):
        raise HTTPException(status_code=400, detail="API Key 格式无效")
    return api_key


def build_agent_config(api_key_override: str = "") -> AgentConfig:
    return AgentConfig(
        api_key=api_key_override.strip() or os.getenv("DASHSCOPE_API_KEY", "").strip(),
        request_timeout=int(os.getenv("AGENT_REQUEST_TIMEOUT", "60")),
        max_retries=int(os.getenv("AGENT_MAX_RETRIES", "2")),
        execution_timeout=int(os.getenv("AGENT_EXECUTION_TIMEOUT", "8")),
        enable_local_execution=True,
        enable_offline_fallback=True,
    )

def select_model(problem_text: str, image_bytes: Optional[bytes] = None) -> Dict[str, str]:
    """
    根据题目特征选择模型
    返回: {"model": 模型名称, "reason": 选择原因}
    """
    if image_bytes:
        return {
            "model": "qwen3-vl-plus",
            "reason": "图片输入，使用视觉模型"
        }
    
    text_len = len(problem_text.strip())
    if text_len < 50:
        return {
            "model": "qwen-turbo",
            "reason": f"短文本({text_len}字符)，使用低成本模型"
        }
    elif text_len < 200:
        return {
            "model": "qwen-plus",
            "reason": f"中等长度文本({text_len}字符)，使用标准模型"
        }
    else:
        return {
            "model": "qwen-max",
            "reason": f"长文本({text_len}字符)，使用高性能模型"
        }


def validate_image(content: bytes, declared_mime: str) -> Dict[str, Any]:
    """Decode the image and verify that its real format matches the request."""

    try:
        with Image.open(io.BytesIO(content)) as image:
            detected_format = str(image.format or "").upper()
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=400, detail="图片尺寸无效或像素过大")
            image.verify()
    except HTTPException:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail="文件内容不是有效图片") from exc

    detected_mime = IMAGE_FORMAT_TO_MIME.get(detected_format)
    if detected_mime not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPEG、WebP 图片")
    if declared_mime and declared_mime != detected_mime:
        raise HTTPException(
            status_code=400,
            detail=f"图片声明格式与真实格式不一致，真实格式为 {detected_mime}",
        )
    return {
        "mime": detected_mime,
        "format": detected_format,
        "width": width,
        "height": height,
    }


def run_agent_task(
    task_id: str,
    problem_text: str,
    *,
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/png",
    api_key_override: str = "",
) -> None:
    """Run the real five-Agent workflow and persist its complete result."""

    # ===== 修改：获取 trace_id 和 prompt_versions =====
    from backend.database import utc_now, get_conn, get_cached_solution, save_code_cache, generate_cache_key
    import json
    import hashlib
    task_info = get_task_by_id(task_id)
    trace_id = task_info.get("data", {}).get("trace_id", "") if task_info else ""
    
    # ===== 新增：读取任务中保存的 Prompt 版本 =====
    prompt_versions = {}
    if task_info:
        data = task_info.get("data", {})
        prompt_versions = data.get("prompt_versions", {})
    
    # ===== 新增：如果存在启用的版本，打印日志 =====
    if prompt_versions:
        print(f"[INFO] Task {task_id} using Prompt versions: {prompt_versions}")
   
    # ===== 检测是否为测试环境 =====
    is_test = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules
    if not is_test:
        prompt_version_str = str(prompt_versions.get("CodeGenerator", ""))
        model_name = "qwen-plus"
        cached_result = get_cached_solution(problem_text, image_bytes, prompt_version_str, model_name, test_mode=is_test)
        
        if cached_result:
            print(f"[Cache] 命中缓存: {cached_result['cache_key'][:8]}...")
            data = {
                "task_id": task_id,
                "status": "completed",
                "code": cached_result["code"],
                "solution_markdown": cached_result["solution_markdown"],
                "test_cases": json.loads(cached_result["test_cases"]) if cached_result["test_cases"] else [],
                "semantic_verification_status": cached_result["semantic_status"],
                "notes": "从缓存恢复结果",
                "input_type": "image" if image_bytes else "text",
                "trace_id": trace_id,
                "prompt_versions": prompt_versions,
                "fallback_used": False,
            }
            replace_task_artifacts(
                task_id,
                steps=[],
                tests=data["test_cases"],
                repairs=[]
            )
            update_task(task_id, "completed", data)
            
            if trace_id:
                insert_trace_node(
                    trace_id=trace_id,
                    node_name="Cache_Hit",
                    node_type="cache",
                    status="completed",
                    start_time=utc_now(),
                    end_time=utc_now(),
                )
            return


    if not is_test:
        import hashlib
        prompt_version_str = str(prompt_versions.get("CodeGenerator", ""))
        model_choice = select_model(problem_text, image_bytes)
        model_name = model_choice.get("model", "qwen-plus")
        
        # 生成缓存键
        recog_cache_key = generate_cache_key(problem_text, image_bytes, prompt_version_str, model_name, rag_version="", test_mode=is_test)
        
        # 尝试读取识别缓存
        recog_cached = get_recognition_cache(recog_cache_key)
        if recog_cached:
            print(f"[Cache] 命中识别缓存: {recog_cached['cache_key'][:8]}...")
            # 使用缓存的识别结果
            problem_text = recog_cached.get("recognized_text", problem_text)
        
        # 尝试读取 RAG 缓存
        rag_cached = get_rag_cache(recog_cache_key)
        if rag_cached:
            print(f"[Cache] 命中 RAG 缓存: {rag_cached['cache_key'][:8]}...")
            # RAG 缓存会在 solve_problem 中自动使用

    if trace_id:
        insert_trace_node(
            trace_id=trace_id,
            node_name="Agent_Workflow_Start",
            node_type="workflow",
            status="running",
            start_time=utc_now(),
        )


    try:
        model_choice = select_model(problem_text, image_bytes)
        print(f"[Route] 选择模型: {model_choice['model']}, 原因: {model_choice['reason']}")
        config = build_agent_config(api_key_override)
        config.trace_id = trace_id
        config.text_model = model_choice["model"]  # 使用路由选择的模型
        if prompt_versions:
            config.prompt_versions = prompt_versions
        
        result = solve_problem(
            config=config,  
            text_problem=problem_text,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )


        if trace_id:
            for idx, step in enumerate(result.agent_steps):
                insert_trace_node(
                    trace_id=trace_id,
                    node_name=getattr(step, "name", f"Agent_{idx}"),
                    node_type="agent",
                    status=getattr(step, "status", "completed"),
                    start_time=utc_now(),
                    end_time=utc_now(),
                    duration_ms=getattr(step, "duration_ms", 0),
                    input_data={"input": getattr(step, "input_summary", "")},
                    output_data={"output": getattr(step, "output_summary", "")},
                    error_message=getattr(step, "error", ""),
                )

        # ===== 调试：打印 Agent 返回的数据量 =====
        print(f"[DEBUG] result.agent_steps: {len(result.agent_steps)}")
        print(f"[DEBUG] result.test_cases: {len(result.test_cases)}")
        print(f"[DEBUG] result.repair_attempts: {len(result.repair_attempts)}")
        if result.agent_steps:
            print(f"[DEBUG] First step example: {result.agent_steps[0]}")
        # ===== 调试结束 =====

        existing_task = get_task_by_id(task_id)  
        initial_data = dict(existing_task["data"]) if existing_task else {}
        data = {**initial_data, **agent_result_to_dict(result)}
        data["task_id"] = task_id
        data["input_type"] = "image" if image_bytes else "text"
        data["fallback_reason"] = result.error if result.fallback_used else ""
        data["notes"] = (
            "模型调用失败后使用离线兜底完成任务。"
            if result.fallback_used
            else "任务已由多 Agent 工作流完成。"
        )
        data["api_key_source"] = (
            "request"
            if api_key_override.strip()
            else ("server" if os.getenv("DASHSCOPE_API_KEY", "").strip() else "none")
        )
        data["selected_model"] = model_choice["model"]
        data["route_reason"] = model_choice["reason"]
        data["token_usage"] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "unknown"  # 标记数据来源：unknown 表示无供应商数据
        }
        # 没有真实 token 数据时，成本为 0
        data["estimated_cost"] = 0.0

        tests = data.get("test_cases", [])
        execution_ok = data["execution_report"].get("exit_code") == 0
        trusted_tests = [
            case
            for case in tests
            if bool(case.get("trusted", True))
            and case.get("validation_status", "verified") == "verified"
        ]
        tests_ok = bool(trusted_tests) and all(
            bool(case.get("passed")) for case in trusted_tests
        )
        semantic_status = str(
            data.get("semantic_verification_status", "manual_review")
        )
        manual_review_ok = semantic_status == "manual_review" and execution_ok
        final_status = (
            "completed"
            if execution_ok and (tests_ok or manual_review_ok)
            else "failed"
        )
        data["status"] = final_status
        if manual_review_ok:
            data["notes"] = (
                "代码已成功运行，但当前题型没有系统权威测试；"
                "模型建议用例已隔离，需人工确认算法语义。"
            )
        elif not tests_ok:
            data["notes"] = "生成代码未通过全部自动测试，请查看失败用例和修复记录。"

                # ===== 格式化数据，确保 database.py 能正确写入 =====
        raw_steps = data.get("agent_steps", [])
        raw_tests = data.get("test_cases", [])
        raw_repairs = data.get("repair_attempts", [])
        
        # 把 steps 转成 database.py 需要的格式
        formatted_steps = []
        for step in raw_steps:
            formatted_steps.append({
                "agent_name": step.get("agent_name", step.get("name", "Agent")),
                "role": step.get("role", ""),
                "status": step.get("status", "completed"),
                "input": step.get("input", ""),
                "output": step.get("output", ""),
                "duration_ms": step.get("duration_ms", 0),
                "error": step.get("error", ""),
            })
        
        # tests 直接用，格式已经对了
        formatted_tests = raw_tests
        formatted_repairs = raw_repairs
        
        print(f"[DEBUG] formatted_steps: {len(formatted_steps)}")
        print(f"[DEBUG] formatted_tests: {len(formatted_tests)}")
        print(f"[DEBUG] formatted_repairs: {len(formatted_repairs)}")
        
        replace_task_artifacts(
            task_id,
            steps=formatted_steps,
            tests=formatted_tests,
            repairs=formatted_repairs,
        )
        update_task(task_id, final_status, data)
        
        
        if final_status == "completed":
            try:
                problem_hash = hashlib.md5(problem_text.strip().lower().encode('utf-8')).hexdigest()
                image_hash = hashlib.md5(image_bytes).hexdigest() if image_bytes else ""
                prompt_version_str = str(prompt_versions.get("CodeGenerator", ""))
                model_name = model_choice["model"] 
                cache_key = generate_cache_key(problem_text, image_bytes, prompt_version_str, model_name, rag_version="", test_mode=is_test)
                
                # 1. 保存识别缓存（无论是否 verified 都保存）
                save_recognition_cache(
                    cache_key=cache_key,
                    problem_hash=problem_hash,
                    image_hash=image_hash,
                    prompt_version=prompt_version_str,
                    model_name=model_name,
                    recognized_text=problem_text,
                    contract=data.get("problem_contract", {})
                )
                print(f"[Cache] 已保存识别缓存: {cache_key[:8]}...")
                
                # 2. 保存 RAG 缓存（无论是否 verified 都保存）
                if data.get("retrieved_templates"):
                    save_rag_cache(
                        cache_key=cache_key,
                        problem_hash=problem_hash,
                        prompt_version=prompt_version_str,
                        model_name=model_name,
                        templates=data.get("retrieved_templates", [])
                    )
                    print(f"[Cache] 已保存 RAG 缓存: {cache_key[:8]}...")
                
                # 3. 保存代码缓存（只有 verified 才缓存）
                if data.get("semantic_verification_status") == "verified":
                    save_code_cache(
                        cache_key=cache_key,
                        problem_hash=problem_hash,
                        image_hash=image_hash,
                        prompt_version=prompt_version_str,
                        model_name=model_name,
                        code=data.get("code", ""),
                        solution_markdown=data.get("solution_markdown", ""),
                        test_cases=data.get("test_cases", []),
                        semantic_status=data.get("semantic_verification_status", ""),
                        cache_type="success_code"
                    )
                    print(f"[Cache] 已保存代码缓存: {cache_key[:8]}...")
            except Exception as e:
                print(f"[Cache] 保存缓存失败: {e}")


        if trace_id:
            insert_trace_node(
                trace_id=trace_id,
                node_name="Agent_Workflow_Complete",
                node_type="workflow",
                status="completed",
                end_time=utc_now(),
            )
        # ===== 新增结束 =====
            
    except Exception as exc:
        # ===== 新增：记录错误节点 =====
        if trace_id:
            insert_trace_node(
                trace_id=trace_id,
                node_name="Agent_Workflow_Error",
                node_type="workflow",
                status="failed",
                error_message=str(exc),
                end_time=utc_now(),
            )
        # ===== 新增结束 =====
        
        error_data = {
            "task_id": task_id,
            "status": "failed",
            "problem": problem_text,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "notes": "Agent 工作流执行失败。",
            "traceback": traceback.format_exc(limit=8),
        }
        update_task(task_id, "failed", error_data)


def create_background_task(
    background_tasks: BackgroundTasks,
    *,
    problem_text: str,
    input_type: str = "text",
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/png",
    api_key_override: str = "",
    extra_data: Optional[Dict[str, Any]] = None,
) -> str:
    from backend.database import get_conn, enqueue_task
    import base64
    import time
    import sys
    import os
    
    task_id = str(uuid.uuid4())
    trace_id = generate_trace_id()
    
    # 获取所有 Agent 的启用版本
    prompt_versions = {}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT agent_name, version FROM prompt_versions WHERE is_enabled = 1"
        ).fetchall()
        for row in rows:
            prompt_versions[row["agent_name"]] = row["version"]
    
    initial_data: Dict[str, Any] = {
        "task_id": task_id,
        "status": "running",
        "problem": problem_text,
        "input_type": input_type,
        "notes": "任务已创建，正在执行多 Agent 工作流。",
        "trace_id": trace_id,
        "prompt_versions": prompt_versions,
    }
    if extra_data:
        initial_data.update(extra_data)
    create_task(
        task_id,
        "running",
        initial_data,
        input_type=input_type,
        problem=problem_text,
        trace_id=trace_id,
    )
    
    # ===== 验证任务已写入 =====
    for attempt in range(3):
        with get_conn() as conn:
            row = conn.execute(
                "SELECT task_id FROM tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            if row:
                print(f"[INFO] 任务 {task_id} 写入验证成功")
                break
        print(f"[INFO] 等待任务 {task_id} 写入 (尝试 {attempt+1}/3)")
        time.sleep(0.1)
    # ===== 结束 =====
    
    # ===== 测试环境同步执行，生产环境使用队列 =====
    is_test = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules
    
    if is_test:
        # 测试环境：直接同步执行
        print(f"[INFO] 测试环境，同步执行任务 {task_id}")
        run_agent_task(
            task_id,
            problem_text,
            image_bytes=image_bytes,
            image_mime=image_mime,
            api_key_override=api_key_override,
        )
    else:
        # 生产环境：入队让 Worker 执行
        image_b64 = base64.b64encode(image_bytes).decode('utf-8') if image_bytes else None
        payload = {
            "problem_text": problem_text,
            "input_type": input_type,
            "image_b64": image_b64,
            "image_mime": image_mime,
            "api_key_override": api_key_override,
            "extra_data": extra_data,
        }
        enqueue_task(task_id, payload)
    # ===== 结束 =====
    
    return task_id


def task_detail(task: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(task["data"])
    data.update(
        {
            "task_id": task["task_id"],
            "status": task["status"],
            "input_type": task["input_type"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }
    )
    return data


@app.get("/api/health")
async def health() -> dict:
    return api_response(
        {
            "status": "ok" if AGENT_AVAILABLE else "degraded",
            "agent_loaded": AGENT_AVAILABLE,
            "agent_import_error": AGENT_IMPORT_ERROR,
            "database": "ok",
            "api_key_configured": bool(os.getenv("DASHSCOPE_API_KEY")),
            "request_api_key_supported": True,
            "version": APP_VERSION,
        }
    )


@app.post("/api/tasks/text")
async def process_text(
    task: TaskRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    x_dashscope_api_key: str = Header("", alias="X-DashScope-API-Key"),
) -> dict:
    # ===== 新增：限流检查 =====
    if request is None:
        from fastapi import Request as FastAPIRequest
        request = FastAPIRequest
    client_ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail=ERROR_CODES[429]["message"]
        )
    # ===== 新增结束 =====
    
    problem_text = task.problem_text.strip()
    if not problem_text:
        raise HTTPException(status_code=400, detail="题目不能为空")
    if looks_like_corrupted_text(problem_text):
        raise HTTPException(
            status_code=400,
            detail="题目文本疑似乱码（大量字符变成 ?），请重新输入并使用 UTF-8",
        )
    request_api_key = normalize_request_api_key(x_dashscope_api_key)
    task_id = create_background_task(
        background_tasks,
        problem_text=problem_text,
        api_key_override=request_api_key,
    )
    return api_response(
        {"task_id": task_id, "status": "running"},
        message="任务已创建",
    )


@app.post("/api/tasks/image")
async def process_image(
    background_tasks: BackgroundTasks,
    request: Request,  # 新增
    image: UploadFile = File(...),
    supplement: str = Form(""),
    x_dashscope_api_key: str = Header("", alias="X-DashScope-API-Key"),
) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail=ERROR_CODES[429]["message"]
        )
    
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="仅支持 PNG、JPEG、WebP 图片",
        )
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="图片文件不能为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片大小不能超过 10MB")

    image_info = validate_image(content, image.content_type or "")
    problem_text = supplement.strip()
    if looks_like_corrupted_text(problem_text):
        raise HTTPException(
            status_code=400,
            detail="补充说明疑似乱码（大量字符变成 ?），请重新输入",
        )
    request_api_key = normalize_request_api_key(x_dashscope_api_key)
    effective_key = request_api_key or os.getenv(
        "DASHSCOPE_API_KEY",
        "",
    ).strip()
    if not effective_key and not problem_text:
        raise HTTPException(
            status_code=400,
            detail="识别截图需要百炼 API Key；未填写 Key 时请同时输入题目补充说明",
        )
    task_id = create_background_task(
        background_tasks,
        problem_text=problem_text,
        input_type="image",
        image_bytes=content,
        image_mime=image_info["mime"],
        api_key_override=request_api_key,
        extra_data={
            "image_filename": image.filename or "problem-image",
            "image_size": len(content),
            "image_format": image_info["format"],
            "image_width": image_info["width"],
            "image_height": image_info["height"],
        },
    )
    return api_response(
        {
            "task_id": task_id,
            "status": "running",
            "filename": image.filename,
            "size": len(content),
        },
        message="图片任务已创建",
    )


@app.get("/api/tasks")
async def get_tasks() -> dict:
    return api_response(list_all_tasks())


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return api_response(task_detail(task))


@app.get("/api/tasks/{task_id}/steps")
async def get_task_steps(task_id: str) -> dict:
    if not get_task_by_id(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = get_steps_by_task(task_id)
    data = [
        {
            "step_id": row["step_id"],
            "agent_name": row["step_name"],
            "role": row["role"],
            "status": row["status"],
            "input": row["input"],
            "output": row["output"],
            "duration_ms": row["duration_ms"],
            "error": row["error"],
        }
        for row in rows
    ]
    return api_response(data)


@app.get("/api/tasks/{task_id}/tests")
async def get_task_tests(task_id: str) -> dict:
    if not get_task_by_id(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return api_response(get_tests_by_task(task_id))


@app.get("/api/tasks/{task_id}/repairs")
async def get_task_repairs(task_id: str) -> dict:
    if not get_task_by_id(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return api_response(get_execution_logs_by_task(task_id))


@app.get("/api/tasks/{task_id}/report")
async def get_task_report(task_id: str) -> Response:
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    data = task["data"]
    document = str(data.get("project_document", "")).strip()
    if not document:
        document = (
            "# AI 代码生成报告\n\n"
            f"## 题目\n\n{data.get('problem', '')}\n\n"
            f"## 解题说明\n\n{data.get('solution_markdown', '')}\n\n"
            "## Python 代码\n\n"
            f"```python\n{data.get('code', '')}\n```\n"
        )
    headers = {
        "Content-Disposition": f'attachment; filename="report_{task_id}.md"'
    }
    return Response(
        content=document,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@app.post("/api/tasks/{task_id}/rerun")
async def rerun_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    x_dashscope_api_key: str = Header("", alias="X-DashScope-API-Key"),
) -> dict:
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    problem_text = str(task["data"].get("problem", task["problem"])).strip()
    if not problem_text:
        raise HTTPException(status_code=400, detail="原任务缺少题目文本")
    request_api_key = normalize_request_api_key(x_dashscope_api_key)
    new_task_id = create_background_task(
        background_tasks,
        problem_text=problem_text,
        input_type="text",
        api_key_override=request_api_key,
        extra_data={"original_task_id": task_id},
    )
    return api_response(
        {"task_id": new_task_id, "status": "running", "original_task_id": task_id},
        message="重新执行任务已创建",
    )


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    """取消正在运行或排队中的任务"""
    from backend.database import get_conn, utc_now  # ← 新增 utc_now
    
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    status = task.get("status", "")
    if status not in ["running", "queued"]:
        raise HTTPException(
            status_code=409,
            detail=f"任务状态为 {status}，无法取消（只能取消 running 或 queued 状态）"
        )
    
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE task_id = ?",
            (utc_now(), task_id)
        )
        conn.execute(
            "UPDATE task_queue SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
            (task_id,)
        )
    
    return api_response(
        {"task_id": task_id, "status": "cancelled"},
        message="任务已取消"
    )

@app.get("/api/metrics/summary")
async def get_metrics_summary() -> dict:
    return api_response(calc_metrics())


@app.get("/api/benchmark/results")
async def get_benchmark_results() -> dict:
    return api_response(get_latest_benchmark_results())


@app.get("/api/prompt/versions")
async def get_prompt_versions(agent_name: str | None = None) -> dict:
    """获取各 Agent 的版本列表"""
    from backend.database import get_conn
    
    with get_conn() as conn:
        if agent_name:
            rows = conn.execute(
                'SELECT * FROM prompt_versions WHERE agent_name = ? ORDER BY created_at DESC',
                (agent_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM prompt_versions ORDER BY agent_name, created_at DESC'
            ).fetchall()
    
    return api_response([dict(row) for row in rows])


class SwitchVersionRequest(BaseModel):
    agent_name: str
    version: str


@app.post("/api/prompt/version")
async def switch_prompt_version(request: SwitchVersionRequest) -> dict:
    """切换指定 Agent 的版本"""
    from backend.database import get_conn
    
    with get_conn() as conn:
        # 先取消所有启用
        conn.execute(
            'UPDATE prompt_versions SET is_enabled = 0 WHERE agent_name = ?',
            (request.agent_name,)
        )
        
        # 启用指定版本
        cursor = conn.execute(
            'UPDATE prompt_versions SET is_enabled = 1 '
            'WHERE agent_name = ? AND version = ?',
            (request.agent_name, request.version)
        )
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="版本不存在")
    
    return api_response(
        {"agent_name": request.agent_name, "version": request.version},
        message=f"已切换到版本 {request.version}"
    )


@app.get("/api/tasks/{task_id}/trace")
async def get_task_trace(task_id: str) -> dict:
    """获取任务的完整 trace"""
    from backend.database import get_task_by_task_id_for_trace, get_trace_by_trace_id
    
    task_info = get_task_by_task_id_for_trace(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    trace_id = task_info.get("trace_id")
    if not trace_id:
        return api_response({"task": task_info, "nodes": [], "tool_calls": []})
    
    trace_data = get_trace_by_trace_id(trace_id)
    return api_response(trace_data)


@app.post("/api/benchmark/runs")
async def start_benchmark_run(background_tasks: BackgroundTasks) -> dict:
    """启动跑批任务"""
    from sandbox.benchmark_runner import run_benchmark
    from backend.database import get_conn
    import threading
    from datetime import datetime
    import json
    
    run_id = str(uuid.uuid4())
    now = datetime.now().isoformat(timespec="milliseconds")
    
    # ===== 新增：读取题库真实数量 =====
    benchmark_file = PROJECT_ROOT / "benchmark_data.json"
    total_questions = 0
    if benchmark_file.exists():
        try:
            with open(benchmark_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                total_questions = len(data) if isinstance(data, list) else 0
        except Exception:
            total_questions = 0
    # ===== 新增结束 =====
    
    # ===== 修改：插入 running 记录，total 使用真实值 =====
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO benchmark_runs 
            (run_id, started_at, finished_at, total, passed, pass_rate, avg_duration_ms, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, now, now, total_questions, 0, 0.0, 0.0, "running")
        )
    # ===== 修改结束 =====
    
    def run_benchmark_task():
        try:
            summary = run_benchmark(
                data_path=PROJECT_ROOT / "benchmark_data.json",
                persist=True,
                api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                run_id=run_id,
            )
            print(f"[INFO] Benchmark {run_id} completed: {summary['passed']}/{summary['total']} passed")
        except Exception as e:
            print(f"[ERROR] Benchmark {run_id} failed: {e}")
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE benchmark_runs 
                    SET status = 'failed', finished_at = ?
                    WHERE run_id = ?
                    """,
                    (datetime.now().isoformat(timespec="milliseconds"), run_id)
                )
    
    thread = threading.Thread(target=run_benchmark_task)
    thread.start()
    
    return api_response(
        {"run_id": run_id, "status": "running"},
        message="跑批任务已启动"
    )


@app.get("/api/benchmark/runs/{run_id}")
async def get_benchmark_status(run_id: str) -> dict:
    """获取跑批状态"""
    from backend.database import get_conn
    
    with get_conn() as conn:
        run = conn.execute(
            """
            SELECT run_id, started_at, finished_at, total, passed, pass_rate,
                   avg_duration_ms, status
            FROM benchmark_runs
            WHERE run_id = ?
            """,
            (run_id,)
        ).fetchone()
        
        if not run:
            raise HTTPException(status_code=404, detail="跑批记录不存在")
        
        run_dict = dict(run)
        
        # 如果还未完成，计算进度
        if run_dict["status"] == "running":
            # 查询已完成的题目数
            count = conn.execute(
                "SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?",
                (run_id,)
            ).fetchone()[0]
            total = run_dict["total"] or 100
            return api_response({
                "run_id": run_dict["run_id"],
                "status": "running",
                "progress": round(count / total * 100, 2) if total > 0 else 0,
                "total": total,
                "completed": count,
                "failed": 0,
                "passed": 0
            })
        
        return api_response({
            "run_id": run_dict["run_id"],
            "status": run_dict["status"],
            "progress": 100 if run_dict["status"] == "completed" else 0,
            "total": run_dict["total"],
            "passed": run_dict["passed"],
            "failed": run_dict["total"] - run_dict["passed"],
            "pass_rate": run_dict["pass_rate"],
            "avg_duration": run_dict["avg_duration_ms"],
            "started_at": run_dict["started_at"],
            "finished_at": run_dict["finished_at"]
        })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8000")),
    )

