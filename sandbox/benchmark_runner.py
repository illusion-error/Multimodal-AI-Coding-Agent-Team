from __future__ import annotations
import json, os, uuid, time, sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# 核心依赖导入
from .evaluator import run_auto_tests
from ai_coding_agent_bailian import AgentConfig, agent_result_to_dict, solve_problem
from backend.database import get_conn, save_benchmark_run

load_dotenv()

BENCHMARK_MODES = [
    {"name": "Offline_Fallback", "offline": True},
    {"name": "Online_Bailian", "offline": False},
]


def _benchmark_data_path(data_path: Optional[Path | str] = None) -> Path:
    base_path = Path(__file__).parent.parent
    if data_path:
        path = Path(data_path)
        return path if path.is_absolute() else base_path / path
    return base_path / "benchmark_data.json"


def load_benchmark_questions(data_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    json_path = _benchmark_data_path(data_path)
    if not json_path.exists():
        return []
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def benchmark_planned_total(data_path: Optional[Path | str] = None) -> int:
    return len(load_benchmark_questions(data_path)) * len(BENCHMARK_MODES)


def _ensure_running_run(run_id: str, *, total: int, started_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO benchmark_runs
                (run_id, started_at, finished_at, total, passed, pass_rate,
                 avg_duration_ms, status)
            VALUES (?, ?, ?, ?, 0, 0.0, 0.0, 'running')
            """,
            (run_id, started_at, started_at, total),
        )
        conn.execute(
            """
            UPDATE benchmark_runs
            SET total = ?, passed = 0, pass_rate = 0.0,
                avg_duration_ms = 0.0, status = 'running',
                finished_at = ?
            WHERE run_id = ?
            """,
            (total, started_at, run_id),
        )
        conn.execute("DELETE FROM benchmark_results WHERE run_id = ?", (run_id,))


def run_benchmark(*, persist: bool = True, api_key: str | None = None, **kwargs) -> Dict[str, Any]:
    print("[Benchmark] 启动多维度量化对比跑批引擎...")
    
    # 路径对齐
    base_path = Path(__file__).parent.parent
    json_path = _benchmark_data_path(kwargs.get("data_path"))
    if not json_path.exists():
        print(f"[Benchmark] 找不到题库文件: {json_path}")
        return {}

    questions = load_benchmark_questions(json_path)

    external_run_id = str(kwargs.get("run_id") or "").strip()
    planned_total = len(questions) * len(BENCHMARK_MODES)
    aggregate_started_at = datetime.now().isoformat(timespec="milliseconds")
    if persist and external_run_id:
        _ensure_running_run(
            external_run_id,
            total=planned_total,
            started_at=aggregate_started_at,
        )

    all_mode_summaries = []
    aggregate_details = []
    run_group_id = external_run_id or str(uuid.uuid4())[:8]

    for mode in BENCHMARK_MODES:
        mode_name = mode['name'] # 修复未定义错误
        print(f"\n[Benchmark] 正在执行模式: [{mode_name}]")
        
        # 初始化统计指标
        started_at = datetime.now().isoformat(timespec="milliseconds")
        stats = {
            "total": len(questions), "recognized": 0, "runnable": 0, 
            "passed": 0, "repairs": 0, "rag_hits": 0, "timeouts": 0, "time_total": 0
        }
        details = []

        config = AgentConfig(
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY", ""), 
            enable_offline_fallback=mode['offline']
        )

        for idx, q in enumerate(questions):
            print(f"  > 跑测 [{idx+1}/{len(questions)}]: {q['title']}...", end="", flush=True)
            step_start = time.time()
            is_passed = False
            error_log = ""

            try:
                # 1. 调用 Agent
                res = solve_problem(config, q['problem_text'])
                data = agent_result_to_dict(res)
                
                # 2. 统计
                if data.get("problem"): stats["recognized"] += 1
                if data.get("retrieved_templates"): stats["rag_hits"] += 1
                stats["repairs"] += len(data.get("repair_attempts", []))
                
                # 3. 运行评测
                eval_res = run_auto_tests(data['code'], q['test_cases'])
                is_passed = eval_res.get("is_final_passed", False)
                
                if is_passed: stats["passed"] += 1
                if eval_res.get("passed", 0) > 0: stats["runnable"] += 1
                error_log = "; ".join([str(d.get("error","")) for d in eval_res['details'] if d.get("error")])

            except Exception as e:
                error_log = f"SystemCrash: {str(e)}"
                print(f" [ERROR] {e}")

            duration = int((time.time() - step_start) * 1000)
            stats["time_total"] += duration

            # 记录详情。外部 API 跑批使用同一个 run_id，因此 task_id
            # 加上模式前缀，避免前端表格无法区分两组对比数据。
            detail = {
                "id": f"{mode_name}:{q['task_id']}" if external_run_id else q["task_id"],
                "title": f"[{mode_name}] {q['title']}" if external_run_id else q["title"],
                "difficulty": q.get("difficulty", ""),
                "category": q.get("category", ""),
                "passed": is_passed,
                "duration": duration,
                "error": error_log,
            }
            details.append(detail)
            aggregate_details.append(detail)

            # 4. 每题实时落库 (解决问题 6 & NOT NULL 报错)
            if persist:
                try:
                    result_run_id = external_run_id or f"{run_group_id}_{mode_name}"
                    with get_conn() as conn:
                        if not external_run_id:
                            conn.execute("PRAGMA foreign_keys = OFF;")
                        conn.execute('''INSERT INTO benchmark_results
                                     (run_id, task_id, title, difficulty, category,
                                      passed, duration_ms, error)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                                     (
                                         result_run_id,
                                         detail["id"],
                                         detail["title"],
                                         detail["difficulty"],
                                         detail["category"],
                                         is_passed,
                                         duration,
                                         error_log,
                                     ))
                        conn.commit()
                except: pass
            
            print(" [PASS]" if is_passed else " [FAIL]")

        # 5. 构建该模式的汇总结果
        avg_dur = stats["time_total"] // stats["total"] if stats["total"] > 0 else 0
        summary = {
            "mode": mode_name,
            "run_id": f"{run_group_id}_{mode_name}",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "status": "completed",
            "total": stats["total"],
            "passed": stats["passed"],
            "pass_rate": round((stats["passed"]/stats["total"])*100, 2) if stats["total"] > 0 else 0,
            "avg_duration": avg_dur,
            "metrics": stats
        }
        
        # 直接调用 runner 时仍保留原有每个模式独立落库行为；API
        # 跑批则在最后统一写回外部传入的 run_id，保证前端轮询一致。
        if persist and not external_run_id:
            try: save_benchmark_run(summary, details)
            except: pass
            
        all_mode_summaries.append(summary)

    if external_run_id:
        total = sum(summary["total"] for summary in all_mode_summaries)
        passed = sum(summary["passed"] for summary in all_mode_summaries)
        total_time = sum(summary["metrics"]["time_total"] for summary in all_mode_summaries)
        aggregate_summary = {
            "mode": "All",
            "run_id": external_run_id,
            "started_at": aggregate_started_at,
            "finished_at": datetime.now().isoformat(timespec="milliseconds"),
            "status": "completed",
            "total": total,
            "passed": passed,
            "pass_rate": round((passed / total) * 100, 2) if total > 0 else 0,
            "avg_duration": total_time // total if total > 0 else 0,
            "metrics": {
                "total": total,
                "recognized": sum(summary["metrics"]["recognized"] for summary in all_mode_summaries),
                "runnable": sum(summary["metrics"]["runnable"] for summary in all_mode_summaries),
                "passed": passed,
                "repairs": sum(summary["metrics"]["repairs"] for summary in all_mode_summaries),
                "rag_hits": sum(summary["metrics"]["rag_hits"] for summary in all_mode_summaries),
                "timeouts": sum(summary["metrics"]["timeouts"] for summary in all_mode_summaries),
                "time_total": total_time,
            },
        }
        if persist:
            save_benchmark_run(aggregate_summary, aggregate_details)

    # 6. 导出最终对比报告
    generate_comparison_md(all_mode_summaries, base_path)
    
    if external_run_id:
        return aggregate_summary

    # 返回 Online 模式给 pytest 校验
    return all_mode_summaries[1] 

def generate_comparison_md(summaries, base_path):
    docs_dir = base_path / "docs"
    docs_dir.mkdir(exist_ok=True)
    path = docs_dir / "benchmark_comparison.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 🚀 Benchmark 全量维度对比报告\n\n")
        f.write("| 模式 | 识别率 | 运行率 | **通过率** | 修复次数 | 平均耗时 |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for s in summaries:
            m = s['metrics']
            f.write(f"| {s['mode']} | {m['recognized']/m['total']:.1%} | {m['runnable']/m['total']:.1%} | **{s['pass_rate']}%** | {m['repairs']} | {s['avg_duration']}ms |\n")
    print(f"\n[Benchmark] 任务完成，报告已生成: {path}")

if __name__ == "__main__":
    run_benchmark()
