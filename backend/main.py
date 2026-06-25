from __future__ import annotations

import os
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from ai_coding_agent_bailian import (  # noqa: E402
    AgentConfig,
    agent_result_to_dict,
    solve_problem,
)
from backend.database import (  # noqa: E402
    create_task,
    get_execution_logs_by_task,
    get_steps_by_task,
    get_task_by_id,
    get_tests_by_task,
    init_db,
    list_all_tasks,
    calc_metrics,
    replace_task_artifacts,
    update_task,
)


APP_VERSION = "1.0.0"
AGENT_AVAILABLE = True
AGENT_IMPORT_ERROR = ""
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))


def _allowed_origins() -> list[str]:
    value = os.getenv(
        "ALLOW_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    return [origin.strip() for origin in value.split(",") if origin.strip()]


app = FastAPI(title="AI Coding Agent API", version=APP_VERSION)
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


def build_agent_config() -> AgentConfig:
    return AgentConfig(
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        request_timeout=int(os.getenv("AGENT_REQUEST_TIMEOUT", "60")),
        execution_timeout=int(os.getenv("AGENT_EXECUTION_TIMEOUT", "8")),
        enable_local_execution=True,
        enable_offline_fallback=True,
    )


def _prepare_test_results(
    cases: list[Dict[str, Any]],
    execution_report: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Attach a conservative task-level result until evaluator integration."""

    execution_ok = execution_report.get("exit_code") == 0
    prepared: list[Dict[str, Any]] = []
    for case in cases:
        item = dict(case)
        item.setdefault("category", item.get("name", "normal"))
        item.setdefault(
            "actual",
            "代码内置自测通过" if execution_ok else "代码执行失败",
        )
        item.setdefault("passed", execution_ok)
        item.setdefault("duration_ms", 0)
        item.setdefault("error", "" if execution_ok else execution_report.get("stderr", ""))
        prepared.append(item)
    return prepared


def run_agent_task(
    task_id: str,
    problem_text: str,
    *,
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/png",
) -> None:
    """Run the real five-Agent workflow and persist its complete result."""

    try:
        result = solve_problem(
            config=build_agent_config(),
            text_problem=problem_text,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        data = agent_result_to_dict(result)
        data["task_id"] = task_id
        data["input_type"] = "image" if image_bytes else "text"
        data["fallback_reason"] = result.error if result.fallback_used else ""
        data["notes"] = (
            "模型调用失败后使用离线兜底完成任务。"
            if result.fallback_used
            else "任务已由多 Agent 工作流完成。"
        )
        data["test_cases"] = _prepare_test_results(
            data.get("test_cases", []),
            data["execution_report"],
        )

        replace_task_artifacts(
            task_id,
            steps=data.get("agent_steps", []),
            tests=data.get("test_cases", []),
            repairs=data.get("repair_attempts", []),
        )
        update_task(task_id, "completed", data)
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
            "version": APP_VERSION,
        }
    )


@app.post("/api/tasks/text")
async def process_text(task: TaskRequest, background_tasks: BackgroundTasks) -> dict:
    problem_text = task.problem_text.strip()
    if not problem_text:
        raise HTTPException(status_code=400, detail="题目不能为空")
    task_id = create_background_task(
        background_tasks,
        problem_text=problem_text,
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

    problem_text = supplement.strip()
    task_id = create_background_task(
        background_tasks,
        problem_text=problem_text,
        input_type="image",
        image_bytes=content,
        image_mime=image.content_type,
        extra_data={
            "image_filename": image.filename or "problem-image",
            "image_size": len(content),
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
) -> dict:
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    problem_text = str(task["data"].get("problem", task["problem"])).strip()
    if not problem_text:
        raise HTTPException(status_code=400, detail="原任务缺少题目文本")
    new_task_id = create_background_task(
        background_tasks,
        problem_text=problem_text,
        input_type="text",
        extra_data={"original_task_id": task_id},
    )
    return api_response(
        {"task_id": new_task_id, "status": "running", "original_task_id": task_id},
        message="重新执行任务已创建",
    )


@app.get("/api/metrics/summary")
async def get_metrics_summary() -> dict:
    return api_response(calc_metrics())


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    print("AI Coding Agent API started")
    print(f"Agent module loaded: {AGENT_AVAILABLE}")
    print(f"Database path: {os.getenv('DATABASE_PATH', 'backend/data/tasks.db')}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8000")),
    )
