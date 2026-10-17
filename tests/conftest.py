import os
import sys
import tempfile
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent
TEST_DB = Path(tempfile.mkdtemp(prefix="mocmien_")) / "test.db"
os.environ["DB_PATH"] = str(TEST_DB)
os.environ["MOCK_NOW"] = "2026-10-16T08:00:00+07:00"
os.environ.pop("API_KEY", None)
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(API_DIR / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from init_db import init_db  # noqa: E402


@pytest.fixture()
def client():
    init_db(TEST_DB)
    return TestClient(app)
