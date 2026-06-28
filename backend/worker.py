import threading
import time
import uuid
import json
import base64
import sys  
from typing import Optional, Dict, Any

from backend.database import dequeue_task, complete_task, fail_task
from backend.main import run_agent_task


class AgentWorker:
    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.poll_interval = 2  # 秒
        self.queue_type = "agent"
    
    def start(self):
        """启动 worker 后台线程"""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"[Worker] {self.worker_id} started")
    
    def stop(self):
        """停止 worker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print(f"[Worker] {self.worker_id} stopped")
    
    def _run_loop(self):
        """主循环：不断拉取任务执行"""
        while self.running:
            task = dequeue_task(self.worker_id, self.queue_type)
            if task:
                self._execute_task(task)
            else:
                time.sleep(self.poll_interval)
    
    def _execute_task(self, task: Dict[str, Any]):
        """执行单个任务"""
        task_id = task["task_id"]
        payload = json.loads(task["payload"])
        
        print(f"[Worker] 执行任务: {task_id}")
        
        # ===== 新增：等待任务写入完成 =====
        for attempt in range(5):
            from backend.database import get_task_by_id
            task_info = get_task_by_id(task_id)
            if task_info:
                break
            print(f"[Worker] 等待任务 {task_id} 写入数据库 (尝试 {attempt+1}/5)")
            time.sleep(0.2)
        # ===== 新增结束 =====
        
        try:
            problem_text = payload.get("problem_text", "")
            image_b64 = payload.get("image_b64")
            image_mime = payload.get("image_mime", "image/png")
            api_key_override = payload.get("api_key_override", "")
            
            image_bytes = base64.b64decode(image_b64) if image_b64 else None
            
            run_agent_task(
                task_id=task_id,
                problem_text=problem_text,
                image_bytes=image_bytes,
                image_mime=image_mime,
                api_key_override=api_key_override,
            )
            
            complete_task(task_id, "completed")
            print(f"[Worker] 任务完成: {task_id}")
            
        except Exception as e:
            error_msg = str(e)
            print(f"[Worker] 任务失败: {task_id}, 错误: {error_msg}")
            fail_task(task_id, error_msg)


_worker: Optional[AgentWorker] = None

def start_worker():
    import os
    # 测试环境中不启动 Worker（由 BackgroundTasks 直接执行）
    if os.getenv("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        print("[Worker] 测试环境，跳过 Worker 启动")
        return None
    
    global _worker
    if _worker is None:
        _worker = AgentWorker()
        _worker.start()
    return _worker

def stop_worker():
    global _worker
    if _worker:
        _worker.stop()
        _worker = None