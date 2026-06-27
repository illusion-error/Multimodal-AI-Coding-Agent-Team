from __future__ import annotations
import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from dotenv import load_dotenv

# 设置项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from ai_coding_agent_bailian import AgentConfig, agent_result_to_dict, solve_problem
from backend.database import save_benchmark_run
from sandbox.evaluator import run_auto_tests

def load_questions(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        questions = json.load(file)
    if not isinstance(questions, list) or not questions:
        raise ValueError("Benchmark 题库必须是非空数组")
    return questions

def run_benchmark(*, data_path: Path | None = None, persist: bool = True, api_key: str | None = None, run_id: str | None = None) -> Dict[str, Any]:
    from backend.database import get_conn
    questions = load_questions(data_path or PROJECT_ROOT / "benchmark_data.json")
    started_at = datetime.now().isoformat(timespec="milliseconds")
    run_id = run_id or str(uuid.uuid4())  
    details: List[Dict[str, Any]] = []

    config = AgentConfig(
        api_key=api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY", ""), 
        enable_local_execution=True, 
        enable_offline_fallback=False
    )

    for idx, question in enumerate(questions):
        task_id = str(question["task_id"])
        title = str(question.get("title", task_id))
        print(f"  > 正在请求大模型生成 [{title}] 的代码...", flush=True)
        try:
            result = solve_problem(config=config, text_problem=str(question["problem_text"]))
            agent_data = agent_result_to_dict(result)
            evaluation = run_auto_tests(agent_data["code"], list(question.get("test_cases", [])), task_id=f"benchmark:{task_id}")
            
            # 核心：使用隐藏用例判定标志
            passed = evaluation.get("is_final_passed", False)
            
            errors = [str(item["error"]) for item in evaluation["details"] if item.get("error")]
            duration_ms = int(agent_data.get("total_ms", 0) + evaluation["total_time_ms"])
            error = "; ".join(errors)
        except Exception as exc:
            passed = False
            duration_ms = 0
            error = f"{type(exc).__name__}: {exc}"

        details.append({
            "id": task_id, "title": title, 
            "difficulty": str(question.get("difficulty", "")), 
            "category": str(question.get("category", "")), 
            "passed": passed, "duration": duration_ms, "error": error
        })
        
        if persist and (idx + 1) % 2 == 0:
            with get_conn() as conn: pass

    # ======= 计算 P95 耗时、超时率等指标 =======
    passed_count = sum(1 for item in details if item["passed"])
    timeout_count = sum(1 for item in details if "timeout" in str(item.get("error", "")).lower())
    durations = sorted([int(item["duration"]) for item in details])
    total = len(details)
    
    if total > 0:
        p95_index = int(total * 0.95) - 1
        p95_duration = durations[max(0, p95_index)]
        avg_duration = sum(durations) / total
        timeout_rate = timeout_count / total * 100
        pass_rate = passed_count / total * 100
    else:
        p95_duration = avg_duration = timeout_rate = pass_rate = 0.0

    summary: Dict[str, Any] = {
        "run_id": run_id, "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
        "status": "completed", "total": total, "passed": passed_count,
        "pass_rate": round(pass_rate, 2), "timeout_rate": round(timeout_rate, 2),
        "avg_duration": round(avg_duration, 2), "p95_duration": p95_duration,
        "details": details,
    }
    
    if persist:
        save_benchmark_run(summary, details)
        
    # === 自动生成 Markdown 报告 ===
    docs_dir = PROJECT_ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    report_path = docs_dir / f"benchmark_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Benchmark 量化评测报告\n\n")
        f.write(f"- 评测题数：{total}\n")
        f.write(f"- 综合通过率：{pass_rate:.1f}%\n")
        f.write(f"- 超时率：{timeout_rate:.1f}%\n")
        f.write(f"- 平均耗时：{avg_duration:.1f} ms\n")
        f.write(f"- **P95 极端耗时**：{p95_duration} ms\n")
        
    return summary

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real Agent benchmark suite")
    parser.add_argument("--no-persist", action="store_true", help="Run without writing results to SQLite")
    args = parser.parse_args()
    summary = run_benchmark(persist=not args.no_persist)
    print("\n✅ Benchmark 运行完毕，报告已存入 docs 文件夹。")

if __name__ == "__main__":
    main()