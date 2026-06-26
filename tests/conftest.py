from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DIR = tempfile.TemporaryDirectory(
    prefix="coding_agent_tests_",
    ignore_cleanup_errors=True,
)
TEST_DB = Path(TEST_DIR.name) / "tasks.db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DATABASE_PATH"] = str(TEST_DB)
os.environ["DASHSCOPE_API_KEY"] = ""
os.environ["PYTHONIOENCODING"] = "utf-8"

from backend.database import get_conn, init_db  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM benchmark_results")
        conn.execute("DELETE FROM benchmark_runs")
        conn.execute("DELETE FROM tasks")
    yield


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    TEST_DIR.cleanup()