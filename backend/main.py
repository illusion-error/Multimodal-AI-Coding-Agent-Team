import sys
import os
import uuid
import json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入统一数据库工具
from database import (
    init_db, upsert_task, get_task_by_id, list_all_tasks,
    insert_step, get_steps_by_task, insert_test_case, get_tests_by_task,
    calc_metrics
)

# 尝试导入核心 Agent
AGENT_AVAILABLE = False

# --- FastAPI 应用初始化 ---
app = FastAPI(title="AI Coding Agent API", version="1.0.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# 初始化数据库
init_db()

# --- Pydantic 模型 ---
class TaskRequest(BaseModel):
    problem_text: str

# --- 后台任务逻辑 ---
def run_agent_task(task_id: str, problem_text: str):
    """真正的后台执行任务"""
    try:
        # 记录开始时间
        start_time = datetime.now()

        if AGENT_AVAILABLE:
            # 调用真实 Agent
            result = solve_problem(text_problem=problem_text)
            
            # 提取步骤（如果有）
            steps = result.get("agent_steps", [])
            for step in steps:
                insert_step(
                    task_id,
                    step.get("name", "未知步骤"),
                    step.get("input", ""),
                    step.get("output", ""),
                    step.get("status", "completed"),
                    step.get("duration", 0.0)
                )
            
            # 提取测试用例（如果有）
            tests = result.get("tests", [])
            for test in tests:
                insert_test_case(
                    task_id,
                    test.get("input", ""),
                    test.get("expected", ""),
                    test.get("actual", ""),
                    test.get("passed", False)
                )
            
            # 构建最终返回数据
            final_data = {
                "problem": result.get("problem", problem_text),
                "solution_markdown": result.get("solution_markdown", ""),
                "code": result.get("code", ""),
                "code_length": len(result.get("code", "")),
                "total_ms": (datetime.now() - start_time).total_seconds() * 1000,
                "api_call": result.get("api_call", True),
                "fallback_used": result.get("fallback_used", False),
                "fallback_reason": result.get("fallback_reason", ""),
                "notes": result.get("notes", ""),
                "execution_report": result.get("execution_report", {
                    "exit_code": 0,
                    "stdout": "",
                    "stderr": ""
                }),
                "rag_hits": result.get("rag_hits", []),
                "repair_rounds": result.get("repair_rounds", 0)
            }
        else:
            # 模拟模式（无 Agent 模块时）
            step_list = [
                ("题目识别Agent", problem_text, "成功解析题目文本", "completed", 0.6),
                ("解题规划Agent", "生成算法思路", "使用两数相加暴力解法", "completed", 0.8),
                ("测试生成Agent", "生成样例", "input:1,2 expect:3", "completed", 0.4),
                ("代码生成Agent", "编写Python代码", "def add(a,b):return a+b", "completed", 1.2),
                ("执行调试Agent", "运行测试", "无报错全部通过", "completed", 0.5)
            ]
            for name, inp, out, stat, dur in step_list:
                insert_step(task_id, name, inp, out, stat, dur)
            
            insert_test_case(task_id, "1,2", "3", "3", True)
            insert_test_case(task_id, "10,20", "30", "30", True)
            
            final_data = {
                "problem": problem_text,
                "solution_markdown": "# 解题代码\n```python\ndef add(a, b):\n    return a + b\n```",
                "code": "def add(a, b):\n    return a + b",
                "code_length": 35,
                "total_ms": (datetime.now() - start_time).total_seconds() * 1000,
                "api_call": False,
                "fallback_used": True,
                "fallback_reason": "未找到核心 Agent 模块，使用模拟输出",
                "notes": "当前为模拟运行，未调用真实模型",
                "execution_report": {
                    "exit_code": 0,
                    "stdout": "执行成功（模拟）",
                    "stderr": ""
                },
                "rag_hits": [],
                "repair_rounds": 0
            }
        
        # 更新任务状态为完成
        upsert_task(task_id, "completed", final_data)
        
    except Exception as e:
        print(f"❌ 任务执行失败: {e}")
        err_data = {
            "error": str(e),
            "problem": problem_text,
            "notes": f"执行异常: {str(e)}"
        }
        upsert_task(task_id, "failed", err_data)

# --- API 接口 ---

# 1. 健康检查
@app.get("/api/health")
async def health():
    return {
        "code": 0,
        "message": "success",
        "data": {
            "status": "ok",
            "timestamp": datetime.now().isoformat()
        }
    }

# 2. 文本任务提交
@app.post("/api/tasks/text")
async def process_text(task: TaskRequest, bt: BackgroundTasks):
    tid = str(uuid.uuid4())
    init_data = {
        "problem": task.problem_text,
        "notes": "任务已创建，正在处理中"
    }
    upsert_task(tid, "running", init_data)
    bt.add_task(run_agent_task, tid, task.problem_text)
    return {
        "code": 0,
        "message": "任务已创建",
        "data": {
            "task_id": tid,
            "status": "running"
        }
    }

# 3. 图片上传接口
@app.post("/api/tasks/image")
async def process_image(
    file: UploadFile = File(...),
    supplement: Optional[str] = "",
    bt: BackgroundTasks = BackgroundTasks()
):
    tid = str(uuid.uuid4())
    
    # 读取图片内容（暂时只记录文件名）
    content = await file.read()
    file_size = len(content)
    
    # 构造模拟题目
    mock_problem = f"【图片题目】文件名: {file.filename}，大小: {file_size}字节"
    if supplement:
        mock_problem += f"\n补充说明: {supplement}"
    
    init_data = {
        "problem": mock_problem,
        "image_filename": file.filename,
        "image_size": file_size,
        "notes": "图片已接收，正在解析中"
    }
    upsert_task(tid, "running", init_data)
    
    bt.add_task(run_agent_task, tid, mock_problem)
    
    return {
        "code": 0,
        "message": "图片接收成功，任务运行中",
        "data": {
            "task_id": tid,
            "status": "running",
            "filename": file.filename,
            "size": file_size
        }
    }

# 4. 获取全部任务列表
@app.get("/api/tasks")
async def get_tasks():
    rows = list_all_tasks()
    res_list = []
    for row in rows:
        tid, status, ctime = row
        res_list.append({
            "task_id": tid,
            "status": status,
            "created_at": ctime
        })
    return {
        "code": 0,
        "message": "success",
        "data": res_list
    }

# 5. 单任务详情
@app.get("/api/tasks/{tid}")
async def get_task(tid: str):
    task = get_task_by_id(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 从数据库返回的字典中读取字段
    status = task["status"]
    ctime = task["created_at"]
    data = task["data"]
    data["created_at"] = ctime
    data["status"] = status
    
    # 确保所有前端期望字段都存在
    default_fields = {
        "problem": "",
        "solution_markdown": "",
        "code": "",
        "code_length": 0,
        "total_ms": 0,
        "api_call": False,
        "fallback_used": False,
        "fallback_reason": "",
        "notes": "",
        "execution_report": {
            "exit_code": -1,
            "stdout": "",
            "stderr": ""
        },
        "rag_hits": [],
        "repair_rounds": 0
    }
    
    # 合并默认值，确保不缺失字段
    for key, default_value in default_fields.items():
        if key not in data:
            data[key] = default_value
    
    return {
        "code": 0,
        "message": "success",
        "data": data
    }

# 6. Markdown报告下载
@app.get("/api/tasks/{tid}/report")
async def get_report(tid: str):
    task = get_task_by_id(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    status = task["status"]
    data = task["data"]
    
    # 构造 Markdown 报告
    md = f"""# AI 代码生成报告

## 任务信息
- **任务ID**: `{tid}`
- **状态**: {status}
- **生成时间**: {data.get("created_at", datetime.now().isoformat())}

## 题目描述
{data.get("problem", "无题目描述")}

## 解题思路
{data.get("solution_markdown", "暂无解题思路")}

## 生成代码
```python
{data.get("code", "暂无代码")}
"""
    return {
        "code": 0,
        "message": "success",
        "data": md
    }

# 7. 获取任务步骤
@app.get("/api/tasks/{tid}/steps")
async def get_task_steps(tid: str):
    rows = get_steps_by_task(tid)
    if not rows:
        return {
            "code": 0,
            "message": "success",
            "data": []
        }
    
    step_list = []
    for row in rows:
        _, _, name, inp, out, status, duration = row
        step_list.append({
            "name": name,
            "input": inp,
            "output": out,
            "status": status,
            "duration": duration
        })
    
    return {
        "code": 0,
        "message": "success",
        "data": step_list
    }

# 8. 获取测试用例
@app.get("/api/tasks/{tid}/tests")
async def get_task_tests(tid: str):
    rows = get_tests_by_task(tid)
    if not rows:
        return {
            "code": 0,
            "message": "success",
            "data": []
        }
    
    test_list = []
    for row in rows:
        _, _, inp, expected, actual, passed = row
        test_list.append({
            "input": inp,
            "expected": expected,
            "actual": actual,
            "passed": bool(passed)
        })
    
    return {
        "code": 0,
        "message": "success",
        "data": test_list
    }

# 9. 重新执行任务
@app.post("/api/tasks/{tid}/rerun")
async def rerun_task(tid: str, bt: BackgroundTasks):
    task = get_task_by_id(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    data = task["data"]
    problem_text = data.get("problem", "")
    
    if not problem_text:
        raise HTTPException(status_code=400, detail="原任务无题目文本，无法重新执行")
    
    # 生成新任务ID...
    new_tid = str(uuid.uuid4())
    init_data = {
        "problem": problem_text,
        "notes": f"从任务 {tid} 重新执行",
        "original_task_id": tid
    }
    upsert_task(new_tid, "running", init_data)
    bt.add_task(run_agent_task, new_tid, problem_text)
    
    return {
        "code": 0,
        "message": "重新执行已启动",
        "data": {
            "task_id": new_tid,
            "status": "running"
        }
    }

# 10. 指标统计看板
@app.get("/api/metrics/summary")
async def get_metrics():
    stats = calc_metrics()
    
    # 确保所有指标字段存在
    default_stats = {
        "total_tasks": 0,
        "success_tasks": 0,
        "failed_tasks": 0,
        "success_rate": 0.0,
        "avg_response_time": 0.0,
        "test_pass_rate": 0.0,
        "code_run_rate": 0.0,
        "repair_rate": 0.0
    }
    
    for key, default_value in default_stats.items():
        if key not in stats:
            stats[key] = default_value
    
    return {
        "code": 0,
        "message": "success",
        "data": stats
    }

# --- 启动事件 ---
@app.on_event("startup")
async def startup_event():
    print("✅ AI Coding Agent API 启动完成")
    print(f"   Agent 模块: {'已加载' if AGENT_AVAILABLE else '未加载（模拟模式）'}")
    print("   数据库: 已初始化")
    print("   接口列表:")
    print("     GET  /api/health")
    print("     POST /api/tasks/text")
    print("     POST /api/tasks/image")
    print("     GET  /api/tasks")
    print("     GET  /api/tasks/{tid}")
    print("     GET  /api/tasks/{tid}/report")
    print("     GET  /api/tasks/{tid}/steps")
    print("     GET  /api/tasks/{tid}/tests")
    print("     POST /api/tasks/{tid}/rerun")
    print("     GET  /api/metrics/summary")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
