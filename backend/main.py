import uuid
import os
import sqlite3
import json
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel  # 新增：用于定义请求模型
# 确保文件已移动至 backend 文件夹下，否则请调整此引用路径
from ai_coding_agent_bailian import solve_problem, AgentConfig

load_dotenv()
app = FastAPI()

# 新增：定义请求的数据结构
class TaskRequest(BaseModel):
    problem_text: str

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 数据库初始化 ---
def init_db():
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks 
                 (task_id TEXT PRIMARY KEY, status TEXT, data TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- 工具函数 ---
def parse_execution_report(report_str):
    """将字符串转换为前端要求的 JSON 对象格式"""
    return {
        "exit_code": 0,
        "stdout": report_str,
        "stderr": "",
        "raw": report_str
    }

# --- 接口实现 ---
@app.get("/api/health")
async def health_check():
    return {"code": 0, "message": "success", "data": {"status": "ok"}}

@app.post("/api/tasks/text")
async def process_text(task: TaskRequest):  # 修改：直接使用 TaskRequest 模型
    problem_text = task.problem_text
    task_id = str(uuid.uuid4())
    
    # 状态初始化
    conn = sqlite3.connect('tasks.db')
    conn.execute("INSERT INTO tasks VALUES (?, ?, ?)", (task_id, "running", json.dumps({"status": "running"})))
    conn.commit()
    conn.close()
    
    try:
        config = AgentConfig(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            enable_local_execution=True,
            enable_offline_fallback=True,
        )
        result = solve_problem(config=config, text_problem=problem_text)
        
        task_data = {
            "task_id": task_id,
            "status": "completed",
            "problem": result.problem,
            "solution_markdown": result.solution_markdown,
            "code": result.code,
            "execution_report": parse_execution_report(str(result.execution_report))
        }
        
        conn = sqlite3.connect('tasks.db')
        conn.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)", (task_id, "completed", json.dumps(task_data)))
        conn.commit()
        conn.close()
        
    except Exception as e:
        conn = sqlite3.connect('tasks.db')
        conn.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)", (task_id, "failed", json.dumps({"message": str(e)})))
        conn.commit()
        conn.close()
        return {"code": 1, "message": str(e), "data": None}
    
    return {"code": 0, "message": "success", "data": {"task_id": task_id, "status": "completed"}}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    conn = sqlite3.connect('tasks.db')
    row = conn.execute("SELECT data FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return {"code": 1, "message": "Task not found", "data": None}
    return {"code": 0, "message": "success", "data": json.loads(row[0])}

@app.get("/api/tasks")
async def get_tasks():
    conn = sqlite3.connect('tasks.db')
    rows = conn.execute("SELECT data FROM tasks").fetchall()
    conn.close()
    # 过滤掉非 task_id 结构的数据
    data = [json.loads(row[0]) for row in rows if "task_id" in json.loads(row[0])]
    return {"code": 0, "message": "success", "data": data}

@app.get("/api/tasks/{task_id}/report")
async def download_report(task_id: str):
    conn = sqlite3.connect('tasks.db')
    row = conn.execute("SELECT data FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return Response(content="Task not found", status_code=404)
    task = json.loads(row[0])
    return Response(content=task.get("solution_markdown", ""), media_type="text/markdown")