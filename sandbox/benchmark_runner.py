from __future__ import annotations
import json, os, uuid, time, sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Any

# 确保导入路径正确
from .evaluator import run_auto_tests
from ai_coding_agent_bailian import AgentConfig, agent_result_to_dict, solve_problem
from backend.database import get_conn, save_benchmark_run

load_dotenv()

def run_benchmark_mode(mode_name: str, use_offline: bool, questions: List[Dict]):
    run_id = f"{str(uuid.uuid4())[:8]}_{mode_name}"
    started_at = datetime.now().isoformat(timespec="milliseconds")
    stats = {"recognized": 0, "runnable": 0, "passed": 0, "repairs": 0, "rag_hits": 0, "time": 0, "total": len(questions)}
    details = [] # === 核心修复：初始化 details 列表 ===
    
    print(f"\n🚀 启动评测模式: [{mode_name}]")

    # 1. 数据库预初始化（自动兼容 B 成员可能缺失的字段）
    try:
        with get_conn() as conn:
            conn.execute("PRAGMA foreign_keys = OFF;")
            cols = ["finished_at", "status", "total", "passed", "pass_rate", "avg_duration"]
            for col in cols:
                try:
                    conn.execute(f"SELECT {col} FROM benchmark_runs LIMIT 1")
                except:
                    default_val = "0.0" if "rate" in col or "dur" in col else "''"
                    conn.execute(f"ALTER TABLE benchmark_runs ADD COLUMN {col} DEFAULT {default_val}")
            
            conn.execute('''INSERT OR REPLACE INTO benchmark_runs 
                         (run_id, started_at, finished_at, status, total, passed, pass_rate, avg_duration) 
                         VALUES (?, ?, '', 'running', ?, 0, 0.0, 0.0)''',
                         (run_id, started_at, len(questions)))
            conn.commit()
    except Exception as e:
        print(f" (DB预热提示: {e})")

    config = AgentConfig(api_key=os.getenv("DASHSCOPE_API_KEY", ""), enable_local_execution=True, enable_offline_fallback=use_offline)

    # 2. 核心循环：开始跑 30 道题
    for idx, q in enumerate(questions):
        print(f"  > 跑测 [{idx+1}/{len(questions)}]: {q['title']}...", end="", flush=True)
        start = time.time()
        error_msg = ""
        is_passed = False # === 核心修复：定义 is_passed ===
        
        try:
            # 执行 Agent 逻辑
            res = solve_problem(config, q['problem_text'])
            data = agent_result_to_dict(res)
            
            if data.get("problem"): stats["recognized"] += 1
            if data.get("retrieved_templates"): stats["rag_hits"] += 1
            stats["repairs"] += len(data.get("repair_attempts", []))
            
            # 执行自动化评测
            eval_res = run_auto_tests(data['code'], q['test_cases'])
            is_passed = eval_res.get("is_final_passed", False)
            
            if is_passed: stats["passed"] += 1
            if eval_res['passed'] > 0: stats["runnable"] += 1
            error_msg = "; ".join([str(d.get("error","")) for d in eval_res['details'] if d.get("error")])
            
        except Exception as e:
            error_msg = str(e)
            print(f" ❌ 崩溃: {e}")

        duration = int((time.time() - start) * 1000)
        stats["time"] += duration
        
        # 记录每题详情
        details.append({"id": q['task_id'], "title": q['title'], "passed": is_passed, "duration": duration, "error": error_msg})

        # 3. 每题实时落库（解决问题 6）
        try:
            with get_conn() as conn:
                conn.execute("PRAGMA foreign_keys = OFF;")
                conn.execute('''INSERT INTO benchmark_results (run_id, task_id, title, passed, duration_ms, error) 
                             VALUES (?, ?, ?, ?, ?, ?)''', 
                             (run_id, q['task_id'], q['title'], is_passed, duration, error_msg))
                conn.commit()
        except: pass
            
        print(" ✅" if is_passed else " ❌")

    # 3. 计算汇总结果
    finished_at = datetime.now().isoformat()
    pass_rate = round(stats["passed"] / len(questions) * 100, 2)
    avg_dur = round(stats["time"] / len(questions), 2)
    
    summary = {
        "run_id": run_id, "mode": mode_name, "started_at": started_at, "finished_at": finished_at,
        "total": len(questions), "passed": stats["passed"], "pass_rate": pass_rate, 
        "avg_duration": avg_dur, "metrics": stats
    }
    
    # 4. 最后更新大表结果
    try:
        save_benchmark_run(summary, details)
    except: pass
    return summary

def generate_comparison_md(summaries):
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    path = docs_dir / "benchmark_comparison.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 🚀 Benchmark 多维对比报告\n\n")
        f.write("| 模式 | 识别率 | 代码运行率 | **通过率** | 修复次数 | 平均耗时 |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for s in summaries:
            m = s['metrics']
            t = m['total']
            f.write(f"| {s['mode']} | {m['recognized']/t:.1%} | {m['runnable']/t:.1%} | **{m['passed']/t:.1%}** | {m['repairs']} | {m['time']//t}ms |\n")
    print(f"\n✅ 对比报告已生成: {path}")

def main():
    if not os.path.exists('benchmark_data.json'):
        print("❌ 找不到题库文件 benchmark_data.json")
        return
    with open('benchmark_data.json', 'r', encoding='utf-8') as f:
        questions = json.load(f)
    
    report_off = run_benchmark_mode("Offline_Fallback", True, questions)
    report_on = run_benchmark_mode("Online_Bailian", False, questions)
    generate_comparison_md([report_off, report_on])

if __name__ == "__main__":
    main()