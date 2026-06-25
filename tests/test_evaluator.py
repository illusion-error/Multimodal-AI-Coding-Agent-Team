from sandbox.evaluator import run_auto_tests


def test_evaluator_reports_real_passes_and_failures():
    report = run_auto_tests(
        "def solution(a, b):\n    return a + b",
        [
            {"args": [1, 2], "expected": 3},
            {"args": [-1, 5], "expected": 4},
        ],
    )
    assert report["passed"] == 2
    assert report["pass_rate"] == 100

    failed = run_auto_tests(
        "def solution(value):\n    return value",
        [{"args": [1], "expected": 2}],
    )
    assert failed["failed"] == 1
    assert failed["details"][0]["actual"] == "1"
