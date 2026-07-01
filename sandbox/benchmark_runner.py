from __future__ import annotations

import json
import os
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv

from ai_coding_agent_bailian import AgentConfig, agent_result_to_dict, solve_problem
from backend.database import get_conn, save_benchmark_run
from .evaluator import run_auto_tests

load_dotenv()


BENCHMARK_MODES = [
    {"name": "Offline_Fallback", "offline": True, "label": "离线兜底 + Agent"},
    {"name": "Online_Bailian", "offline": False, "label": "百炼 API + RAG Agent"},
]


def _project_root() -> Path:
    return Path(__file__).parent.parent


def _benchmark_data_path(data_path: Optional[Path | str] = None) -> Path:
    base_path = _project_root()
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


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _p95(values: Iterable[int]) -> int:
    ordered = sorted(int(value or 0) for value in values)
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def _first_failure(eval_result: Dict[str, Any]) -> str:
    for detail in eval_result.get("details", []):
        if detail.get("passed"):
            continue
        error = str(detail.get("error") or "").strip()
        if error:
            return error
        actual = detail.get("actual", "")
        expected = detail.get("expected", "")
        return f"expected={expected}, actual={actual}"
    return ""


def _failure_category(error_text: str, *, is_passed: bool, runnable: bool, task_success: bool) -> str:
    text = (error_text or "").lower()
    if is_passed:
        return ""
    if not task_success:
        if "api" in text or "dashscope" in text or "401" in text or "429" in text:
            return "API 调用失败"
        return "任务执行失败"
    if not runnable:
        if "timeout" in text:
            return "超时"
        if "syntax" in text:
            return "代码语法错误"
        return "运行时错误"
    return "测试未通过"


def _run_single_mode(
    questions: List[Dict[str, Any]],
    *,
    mode: Dict[str, Any],
    api_key: str | None,
    run_id: str,
    persist: bool,
) -> Dict[str, Any]:
    mode_name = str(mode["name"])
    print(f"\n[Benchmark] 正在执行模式: [{mode_name}]")

    started_at = datetime.now().isoformat(timespec="milliseconds")
    stats = {
        "total": len(questions),
        "task_success": 0,
        "recognized": 0,
        "runnable": 0,
        "passed": 0,
        "repair_task_count": 0,
        "repair_success": 0,
        "repairs": 0,
        "rag_hits": 0,
        "timeouts": 0,
        "time_total": 0,
        "token_usage": "unknown",
        "estimated_cost": "unknown",
    }
    details: List[Dict[str, Any]] = []

    config = AgentConfig(
        api_key=api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY", ""),
        enable_offline_fallback=bool(mode["offline"]),
    )

    for idx, question in enumerate(questions):
        print(f"  > 跑测 [{idx + 1}/{len(questions)}]: {question['title']}...", end="", flush=True)
        step_start = time.time()
        task_success = False
        runnable = False
        is_passed = False
        error_log = ""
        repair_count = 0

        try:
            result = solve_problem(config, question["problem_text"])
            data = agent_result_to_dict(result)
            code = data.get("code", "")
            task_success = bool(code)
            if task_success:
                stats["task_success"] += 1
            if data.get("problem"):
                stats["recognized"] += 1
            if data.get("retrieved_templates"):
                stats["rag_hits"] += 1
            repair_count = len(data.get("repair_attempts", []))
            stats["repairs"] += repair_count
            if repair_count:
                stats["repair_task_count"] += 1

            eval_result = run_auto_tests(code, list(question.get("test_cases", [])))
            runnable = bool(eval_result.get("details")) and all(
                not str(item.get("error") or "").strip()
                for item in eval_result.get("details", [])
            )
            is_passed = bool(eval_result.get("is_final_passed", False))

            if runnable:
                stats["runnable"] += 1
            if is_passed:
                stats["passed"] += 1
                if repair_count:
                    stats["repair_success"] += 1
            error_log = _first_failure(eval_result)
            if "timeout" in error_log.lower():
                stats["timeouts"] += 1
        except Exception as exc:
            error_log = f"SystemCrash: {exc}"
            if "timeout" in error_log.lower():
                stats["timeouts"] += 1
            print(f" [ERROR] {exc}", end="")

        duration = int((time.time() - step_start) * 1000)
        stats["time_total"] += duration
        category = _failure_category(
            error_log,
            is_passed=is_passed,
            runnable=runnable,
            task_success=task_success,
        )

        details.append(
            {
                "id": f"{mode_name}:{question['task_id']}",
                "task_id": question["task_id"],
                "title": f"[{mode_name}] {question['title']}",
                "raw_title": question["title"],
                "difficulty": question.get("difficulty", ""),
                "category": question.get("category", ""),
                "passed": is_passed,
                "task_success": task_success,
                "runnable": runnable,
                "duration": duration,
                "repair_count": repair_count,
                "failure_category": category,
                "error": error_log,
            }
        )
        print(" [PASS]" if is_passed else " [FAIL]")

    total = stats["total"]
    summary = {
        "mode": mode_name,
        "mode_label": mode.get("label", mode_name),
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
        "status": "completed",
        "total": total,
        "passed": stats["passed"],
        "pass_rate": _rate(stats["passed"], total),
        "avg_duration": stats["time_total"] // total if total else 0,
        "p95_duration": _p95(item["duration"] for item in details),
        "metrics": {
            **stats,
            "task_success_rate": _rate(stats["task_success"], total),
            "code_run_rate": _rate(stats["runnable"], total),
            "test_pass_rate": _rate(stats["passed"], total),
            "repair_success_rate": _rate(stats["repair_success"], stats["repair_task_count"]),
            "avg_repair_rounds": round(stats["repairs"] / total, 2) if total else 0.0,
        },
        "details": details,
    }

    if persist:
        save_benchmark_run(summary, details)
    return summary


def _aggregate_run(run_id: str, summaries: List[Dict[str, Any]], started_at: str) -> Dict[str, Any]:
    details = [detail for summary in summaries for detail in summary.get("details", [])]
    total = sum(summary.get("total", 0) for summary in summaries)
    passed = sum(summary.get("passed", 0) for summary in summaries)
    total_time = sum(summary.get("metrics", {}).get("time_total", 0) for summary in summaries)
    task_success = sum(summary.get("metrics", {}).get("task_success", 0) for summary in summaries)
    runnable = sum(summary.get("metrics", {}).get("runnable", 0) for summary in summaries)
    repairs = sum(summary.get("metrics", {}).get("repairs", 0) for summary in summaries)
    repair_task_count = sum(summary.get("metrics", {}).get("repair_task_count", 0) for summary in summaries)
    repair_success = sum(summary.get("metrics", {}).get("repair_success", 0) for summary in summaries)

    return {
        "mode": "All",
        "mode_label": "全部模式",
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
        "status": "completed",
        "total": total,
        "passed": passed,
        "pass_rate": _rate(passed, total),
        "avg_duration": total_time // total if total else 0,
        "p95_duration": _p95(item["duration"] for item in details),
        "metrics": {
            "total": total,
            "task_success": task_success,
            "recognized": sum(summary.get("metrics", {}).get("recognized", 0) for summary in summaries),
            "runnable": runnable,
            "passed": passed,
            "repairs": repairs,
            "repair_task_count": repair_task_count,
            "repair_success": repair_success,
            "rag_hits": sum(summary.get("metrics", {}).get("rag_hits", 0) for summary in summaries),
            "timeouts": sum(summary.get("metrics", {}).get("timeouts", 0) for summary in summaries),
            "time_total": total_time,
            "task_success_rate": _rate(task_success, total),
            "code_run_rate": _rate(runnable, total),
            "test_pass_rate": _rate(passed, total),
            "repair_success_rate": _rate(repair_success, repair_task_count),
            "avg_repair_rounds": round(repairs / total, 2) if total else 0.0,
            "token_usage": "unknown",
            "estimated_cost": "unknown",
        },
        "details": details,
    }


def run_benchmark_all_modes(
    *,
    persist: bool = True,
    api_key: str | None = None,
    data_path: Optional[Path | str] = None,
    run_id: str | None = None,
) -> List[Dict[str, Any]]:
    print("[Benchmark] 启动多维度量化对比跑批引擎...")
    base_path = _project_root()
    json_path = _benchmark_data_path(data_path)
    questions = load_benchmark_questions(json_path)
    if not questions:
        raise FileNotFoundError(f"Benchmark 题库不存在或为空: {json_path}")

    run_group_id = str(run_id or uuid.uuid4())[:36]
    aggregate_started_at = datetime.now().isoformat(timespec="milliseconds")
    if persist and run_id:
        _ensure_running_run(
            run_group_id,
            total=len(questions) * len(BENCHMARK_MODES),
            started_at=aggregate_started_at,
        )

    summaries: List[Dict[str, Any]] = []
    for mode in BENCHMARK_MODES:
        result_run_id = run_group_id if run_id else f"{run_group_id}_{mode['name']}"
        summaries.append(
            _run_single_mode(
                questions,
                mode=mode,
                api_key=api_key,
                run_id=result_run_id,
                persist=persist and not bool(run_id),
            )
        )

    generate_comparison_md(summaries, base_path)
    if persist and run_id:
        aggregate = _aggregate_run(run_group_id, summaries, aggregate_started_at)
        save_benchmark_run(aggregate, aggregate["details"])
    return summaries


def run_benchmark(*, persist: bool = True, api_key: str | None = None, **kwargs) -> Dict[str, Any]:
    summaries = run_benchmark_all_modes(
        persist=persist,
        api_key=api_key,
        data_path=kwargs.get("data_path"),
        run_id=kwargs.get("run_id"),
    )
    if kwargs.get("run_id"):
        return _aggregate_run(
            str(kwargs.get("run_id")),
            summaries,
            summaries[0]["started_at"] if summaries else datetime.now().isoformat(timespec="milliseconds"),
        )
    return summaries[-1] if summaries else {}


def generate_comparison_md(summaries: List[Dict[str, Any]], base_path: Path) -> None:
    docs_dir = base_path / "docs"
    docs_dir.mkdir(exist_ok=True)
    path = docs_dir / "benchmark_comparison.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Benchmark 全量维度对比报告\n\n")
        f.write("> 说明：当前报告记录项目内置回归 Benchmark 的跑批结果，用于验证 Agent 工作流、代码执行器、自动评测器和报告生成链路；该结果不等同于未知题泛化能力。\n\n")
        f.write("| 模式 | 任务成功率 | 代码执行通过率 | 自动测试通过率 | 修复次数 | 平均耗时 | P95 耗时 |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for summary in summaries:
            metrics = summary.get("metrics", {})
            f.write(
                f"| {summary.get('mode', 'Unknown')} | "
                f"{metrics.get('task_success_rate', 0.0)}% | "
                f"{metrics.get('code_run_rate', 0.0)}% | "
                f"**{summary.get('pass_rate', 0.0)}%** | "
                f"{metrics.get('repairs', 0)} | "
                f"{summary.get('avg_duration', 0)}ms | "
                f"{summary.get('p95_duration', 0)}ms |\n"
            )
    print(f"\n[Benchmark] 基础对比报告已生成: {path}")


def _report_row(set_name: str, summary: Dict[str, Any], desc: str) -> str:
    metrics = summary.get("metrics", {})
    total = int(metrics.get("total") or summary.get("total") or 0)
    return (
        f"| {set_name} | {total} | {summary.get('mode_label') or summary.get('mode', '')} | "
        f"{metrics.get('task_success_rate', 0.0)}% | "
        f"{metrics.get('code_run_rate', 0.0)}% | "
        f"**{metrics.get('test_pass_rate', summary.get('pass_rate', 0.0))}%** | "
        f"{summary.get('avg_duration', 0)} ms | "
        f"{summary.get('p95_duration', 0)} ms | "
        f"{metrics.get('repair_success_rate', 0.0)}% | "
        f"{metrics.get('avg_repair_rounds', 0.0)} | "
        f"{metrics.get('token_usage', 'unknown')} | "
        f"{metrics.get('estimated_cost', 'unknown')} | "
        f"{desc} |\n"
    )


def generate_final_report_md(
    regression_summaries: List[Dict[str, Any]],
    unseen_summaries: List[Dict[str, Any]],
    base_path: Path,
) -> Path:
    docs_dir = base_path / "docs"
    docs_dir.mkdir(exist_ok=True)
    path = docs_dir / "真实性能测试报告.md"
    all_runs = [
        ("回归 Benchmark", summary, "验证系统稳定性和常见题型覆盖情况")
        for summary in regression_summaries
    ] + [
        ("未见题测试", summary, "验证未收录题目上的 Agent 泛化表现")
        for summary in unseen_summaries
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Agent 系统性能评测与真实性能报告\n\n")
        f.write("## 1. 测试目的\n\n")
        f.write(
            "本项目不训练本地分类模型，因此不使用 MobileNetV2 模型体积作为核心指标。"
            "系统采用任务成功率、代码执行通过率、自动测试通过率、平均响应时间、"
            "P95 响应时间、修复成功率、平均修复轮数、Token 消耗和估算成本衡量 Agent 工程系统性能。\n\n"
        )
        f.write("## 2. 测试环境\n\n")
        f.write("- Python 版本：3.10+\n")
        f.write("- 后端/前端：FastAPI / Vue3 + Vite\n")
        f.write("- 执行环境：本地受限执行器；项目也支持 Docker Compose 部署\n")
        f.write("- 回归测试模式：Offline_Fallback 与 Online_Bailian\n")
        f.write(f"- 百炼 API Key：{'已配置' if os.getenv('DASHSCOPE_API_KEY') else '未配置'}\n")
        f.write("- Token 与成本：当前离线直连评测未经过后端供应商计费统计，统一记录为 unknown，不伪造数值\n\n")
        if not os.getenv("DASHSCOPE_API_KEY"):
            f.write(
                "> 注意：本次运行环境未配置 DASHSCOPE_API_KEY，Online_Bailian 行表示线上模式入口在无 Key 情况下的降级表现；"
                "如需评估真实百炼模型泛化能力，应配置有效 API Key 后重新生成报告。\n\n"
            )
        f.write("## 3. 测试集说明\n\n")
        f.write("- 回归 Benchmark 测试集：30 道内置算法题，用于验证主链路稳定性。\n")
        f.write("- 未见题测试集：5 道不写入离线兜底模板的新题，用于观察未收录题目的处理情况。\n\n")
        f.write("## 4. 总体指标表\n\n")
        f.write("| 测试集 | 题目数量 | 模式 | 任务成功率 | 代码执行通过率 | 自动测试通过率 | 平均响应时间 | P95 响应时间 | 修复成功率 | 平均修复轮数 | Token 消耗 | 估算成本 | 说明 |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for set_name, summary, desc in all_runs:
            f.write(_report_row(set_name, summary, desc))

        f.write("\n## 5. 失败案例分析表\n\n")
        f.write("| 题目 | 失败阶段 | 失败现象 | 原因分类 | 是否触发修复 | 最终状态 | 后续优化方向 |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        failed_count = 0
        for _set_name, summary, _desc in all_runs:
            for detail in summary.get("details", []):
                if detail.get("passed"):
                    continue
                error = str(detail.get("error") or "输出与期望不一致").replace("\n", " ")[:120]
                f.write(
                    f"| {detail.get('title', detail.get('raw_title', 'Unknown'))} | "
                    f"自动测试 | {error} | "
                    f"{detail.get('failure_category') or '测试未通过'} | "
                    f"{'是' if int(detail.get('repair_count') or 0) > 0 else '否'} | "
                    f"failed | 补充未见题样本、优化 Prompt/RAG 检索或增加权威测试 |\n"
                )
                failed_count += 1
                if failed_count >= 8:
                    break
            if failed_count >= 8:
                break
        if failed_count == 0:
            f.write("| 无 | 无 | 当前测试集中未出现失败样例 | 无 | 否 | completed | 后续继续扩大未见题测试集 |\n")

        f.write("\n## 6. 结论\n\n")
        f.write(
            "回归 Benchmark 用于验证系统稳定性和常见算法题型覆盖情况；未见题测试用于补充观察未收录题目的处理表现。"
            "当前报告不把回归通过率包装成大模型准确率，也不伪造 Token 和成本数据。"
            "如果需要进一步评估模型泛化能力，应继续扩充未见题集，并使用有效百炼 API Key 运行对比实验。\n"
        )
    print(f"\n[Benchmark] 真实性能测试报告已生成: {path}")
    return path


def main() -> None:
    base_path = _project_root()
    benchmark_path = base_path / "benchmark_data.json"
    unseen_path = base_path / "unseen_data.json"
    if not benchmark_path.exists():
        raise FileNotFoundError(f"找不到回归题库文件: {benchmark_path}")
    if not unseen_path.exists():
        raise FileNotFoundError(
            f"找不到未见题测试集: {unseen_path}。请先提交 5-10 道 benchmark_data.json 之外的新题。"
        )

    print("\n" + "=" * 50 + "\n[1/2] 开始执行 30 题回归 Benchmark\n" + "=" * 50)
    regression_summaries = run_benchmark_all_modes(
        data_path=benchmark_path,
        persist=True,
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
    )

    print("\n" + "=" * 50 + "\n[2/2] 开始执行未见题测试集\n" + "=" * 50)
    unseen_summaries = run_benchmark_all_modes(
        data_path=unseen_path,
        persist=True,
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
    )

    # 未见题也会调用基础对比报告生成函数；这里重新写回回归 Benchmark 结果，
    # 避免 docs/benchmark_comparison.md 被最后一次未见题跑批覆盖。
    generate_comparison_md(regression_summaries, base_path)
    generate_final_report_md(regression_summaries, unseen_summaries, base_path)


if __name__ == "__main__":
    main()
