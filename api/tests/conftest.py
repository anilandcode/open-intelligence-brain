import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Strip [::1] from NO_PROXY / no_proxy to work around httpx 0.28 IPv6 brackets parse bug
for _var in ("NO_PROXY", "no_proxy"):
    if _var in os.environ and "[::1]" in os.environ[_var]:
        os.environ[_var] = ",".join(p for p in os.environ[_var].split(",") if p != "[::1]")

import tempfile

if "BRAIN_DATABASE_URL" not in os.environ:
    _temp_db_dir = tempfile.mkdtemp(prefix="brain_test_")
    _test_db_path = Path(_temp_db_dir) / "test-brain.db"
    os.environ["BRAIN_DATABASE_URL"] = f"sqlite:///{_test_db_path}"

os.environ["BRAIN_OWNER_TOKEN"] = "test-token"
os.environ["BRAIN_SEED_DEMO"] = "false"
os.environ["BRAIN_RATE_LIMIT_ENABLED"] = "false"

from brain.database import Base, engine
from brain.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def headers():
    return {"X-Brain-Token": "test-token"}
