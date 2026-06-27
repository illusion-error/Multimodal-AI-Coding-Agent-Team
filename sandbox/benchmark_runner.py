from __future__ import annotations
import json, os, uuid, time, sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from .evaluator import run_auto_tests
from ai_coding_agent_bailian import AgentConfig, agent_result_to_dict, solve_problem
from backend.database import get_conn, save_benchmark_run
from typing import List, Dict, Any

load_dotenv()

def run_benchmark_mode(mode_name: str, use_offline: bool, questions: List[Dict]):
    run_id = f"{str(uuid.uuid4())[:8]}_{mode_name}"
    started_at = datetime.now().isoformat(timespec="milliseconds")
    stats = {"recognized": 0, "runnable": 0, "passed": 0, "repairs": 0, "rag_hits": 0, "time": 0, "total": len(questions)}
    
    print(f"\n🚀 启动评测模式: [{mode_name}]")

    # === 修改这一段，让它自动适应 B 成员的各种表结构 ===
    try:
        with get_conn() as conn:
            conn.execute("PRAGMA foreign_keys = OFF;")
            # 自动补齐缺失的列，不管 B 缺哪一列，咱们都给它加上
            cols = ["finished_at", "status", "total", "passed", "pass_rate", "avg_duration"]
            for col in cols:
                try:
                    conn.execute(f"SELECT {col} FROM benchmark_runs LIMIT 1")
                except:
                    # 动态增加缺失的列
                    default_val = "0.0" if "rate" in col or "dur" in col else "''"
                    conn.execute(f"ALTER TABLE benchmark_runs ADD COLUMN {col} DEFAULT {default_val}")
            
            conn.execute('''INSERT OR REPLACE INTO benchmark_runs 
                         (run_id, started_at, finished_at, status, total, passed, pass_rate, avg_duration) 
                         VALUES (?, ?, '', 'running', ?, 0, 0.0, 0.0)''',
                         (run_id, started_at, len(questions)))
            conn.commit()
    except Exception as e:
        pass # 已经尽力兼容了，如果还错就跳过，不影响主流程
            
        print(" ✅" if is_passed else " ❌")

    # 结束跑批，计算最终结果
    finished_at = datetime.now().isoformat()
    pass_rate = round(stats["passed"] / len(questions) * 100, 2)
    avg_dur = round(stats["time"] / len(questions), 2)
    
    summary = {
        "run_id": run_id, "mode": mode_name, "started_at": started_at, "finished_at": finished_at,
        "total": len(questions), "passed": stats["passed"], "pass_rate": pass_rate, 
        "avg_duration": avg_dur, "metrics": stats
    }
    
    # 最后更新大表，把 0 换成真实的分数
    try:
        save_benchmark_run(summary, details)
    except:
        pass
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
        print("❌ 找不到题库文件")
        return
    with open('benchmark_data.json', 'r', encoding='utf-8') as f:
        questions = json.load(f)
    
    report_off = run_benchmark_mode("Offline_Fallback", True, questions)
    report_on = run_benchmark_mode("Online_Bailian", False, questions)
    generate_comparison_md([report_off, report_on])

if __name__ == "__main__":
    main()