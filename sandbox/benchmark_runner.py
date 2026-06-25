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


def run_benchmark(
    *,
    data_path: Path | None = None,
    persist: bool = True,
    api_key: str | None = None,
) -> Dict[str, Any]:
    questions = load_questions(data_path or PROJECT_ROOT / "benchmark_data.json")
    started_at = datetime.now().isoformat(timespec="milliseconds")
    run_id = str(uuid.uuid4())
    details: List[Dict[str, Any]] = []

    config = AgentConfig(
        api_key=api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY", ""),
        enable_local_execution=True,
        enable_offline_fallback=True,
    )

    for question in questions:
        task_id = str(question["task_id"])
        title = str(question.get("title", task_id))
        try:
            result = solve_problem(
                config=config,
                text_problem=str(question["problem_text"]),
            )
            agent_data = agent_result_to_dict(result)
            evaluation = run_auto_tests(
                agent_data["code"],
                list(question.get("test_cases", [])),
                task_id=f"benchmark:{task_id}",
            )
            passed = evaluation["total"] > 0 and evaluation["failed"] == 0
            errors = [
                str(item["error"])
                for item in evaluation["details"]
                if item.get("error")
            ]
            duration_ms = int(
                agent_data.get("total_ms", 0) + evaluation["total_time_ms"]
            )
            error = "; ".join(errors)
        except Exception as exc:
            passed = False
            duration_ms = 0
            error = f"{type(exc).__name__}: {exc}"

        details.append(
            {
                "id": task_id,
                "title": title,
                "difficulty": str(question.get("difficulty", "")),
                "category": str(question.get("category", "")),
                "passed": passed,
                "duration": duration_ms,
                "error": error,
            }
        )

    passed_count = sum(1 for item in details if item["passed"])
    total_duration = sum(int(item["duration"]) for item in details)
    total = len(details)
    finished_at = datetime.now().isoformat(timespec="milliseconds")
    summary: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "completed",
        "total": total,
        "passed": passed_count,
        "pass_rate": round(passed_count / total * 100, 2) if total else 0.0,
        "avg_duration": round(total_duration / total, 2) if total else 0.0,
        "details": details,
    }
    if persist:
        save_benchmark_run(summary, details)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real Agent benchmark suite")
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run without writing results to SQLite",
    )
    args = parser.parse_args()
    summary = run_benchmark(persist=not args.no_persist)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
