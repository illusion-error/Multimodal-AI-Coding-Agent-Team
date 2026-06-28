from __future__ import annotations
import json, os, uuid, time, sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv

# 核心依赖导入
from .evaluator import run_auto_tests
from ai_coding_agent_bailian import AgentConfig, agent_result_to_dict, solve_problem
from backend.database import get_conn, save_benchmark_run

load_dotenv()

def run_benchmark(*, persist: bool = True, api_key: str | None = None, **kwargs) -> Dict[str, Any]:
    print("🚀 启动第二阶段：多维度量化对比跑批引擎...")
    
    # 路径对齐
    base_path = Path(__file__).parent.parent
    json_path = base_path / "benchmark_data.json"
    if not json_path.exists():
        print(f"❌ 找不到题库文件: {json_path}")
        return {}

    with open(json_path, 'r', encoding='utf-8') as f:
        questions = json.load(f)

    # 满足目标 8: 自动跑两组配置进行对比
    modes = [
        {"name": "Offline_Fallback", "offline": True},
        {"name": "Online_Bailian", "offline": False}
    ]
    
    all_mode_summaries = []
    run_group_id = str(uuid.uuid4())[:8]

    for mode in modes:
        mode_name = mode['name'] # 修复未定义错误
        print(f"\n📊 正在执行模式: [{mode_name}]")
        
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
                print(f" ❌ {e}")

            duration = int((time.time() - step_start) * 1000)
            stats["time_total"] += duration

            # 记录详情
            details.append({"id": q['task_id'], "title": q['title'], "passed": is_passed, "duration": duration, "error": error_log})

            # 4. 每题实时落库 (解决问题 6 & NOT NULL 报错)
            if persist:
                try:
                    with get_conn() as conn:
                        conn.execute("PRAGMA foreign_keys = OFF;")
                        conn.execute('''INSERT INTO benchmark_results (run_id, task_id, title, passed, duration_ms, error) 
                                     VALUES (?, ?, ?, ?, ?, ?)''', 
                                     (f"{run_group_id}_{mode_name}", q['task_id'], q['title'], is_passed, duration, error_log))
                        conn.commit()
                except: pass
            
            print(" ✅" if is_passed else " ❌")

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
        
        # 存入大表
        if persist:
            try: save_benchmark_run(summary, details)
            except: pass
            
        all_mode_summaries.append(summary)

    # 6. 导出最终对比报告
    generate_comparison_md(all_mode_summaries, base_path)
    
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
    print(f"\n✅ 任务完成！报告已生成: {path}")

if __name__ == "__main__":
    run_benchmark()