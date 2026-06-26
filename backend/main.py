from __future__ import annotations

import io
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
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
    print("AI Coding Agent API started")
    print(f"Agent module loaded: {AGENT_AVAILABLE}")
    print(f"Database path: {os.getenv('DATABASE_PATH', 'backend/data/tasks.db')}")
    yield


app = FastAPI(title="AI Coding Agent API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    try:
        result = solve_problem(
            config=build_agent_config(api_key_override),
            text_problem=problem_text,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
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

        replace_task_artifacts(
            task_id,
            steps=data.get("agent_steps", []),
            tests=data.get("test_cases", []),
            repairs=data.get("repair_attempts", []),
        )
        update_task(task_id, final_status, data)
    except Exception as exc:
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
    task_id = str(uuid.uuid4())
    initial_data: Dict[str, Any] = {
        "task_id": task_id,
        "status": "running",
        "problem": problem_text,
        "input_type": input_type,
        "notes": "任务已创建，正在执行多 Agent 工作流。",
    }
    if extra_data:
        initial_data.update(extra_data)
    create_task(
        task_id,
        "running",
        initial_data,
        input_type=input_type,
        problem=problem_text,
    )
    background_tasks.add_task(
        run_agent_task,
        task_id,
        problem_text,
        image_bytes=image_bytes,
        image_mime=image_mime,
        api_key_override=api_key_override,
    )
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
    x_dashscope_api_key: str = Header("", alias="X-DashScope-API-Key"),
) -> dict:
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
    image: UploadFile = File(...),
    supplement: str = Form(""),
    x_dashscope_api_key: str = Header("", alias="X-DashScope-API-Key"),
) -> dict:
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


@app.get("/api/metrics/summary")
async def get_metrics_summary() -> dict:
    return api_response(calc_metrics())


@app.get("/api/benchmark/results")
async def get_benchmark_results() -> dict:
    return api_response(get_latest_benchmark_results())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8000")),
    )
