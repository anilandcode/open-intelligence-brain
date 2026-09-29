import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DB = Path("test-brain.db")
# Honour an externally supplied database so the whole suite can run against
# PostgreSQL in CI. Previously this was hardcoded to SQLite, which meant a
# "full suite on Postgres" job quietly re-ran SQLite and reported green — the
# same green-skip failure mode the parity job exists to prevent.
os.environ.setdefault("BRAIN_DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ["BRAIN_OWNER_TOKEN"] = "test-token"
os.environ["BRAIN_SEED_DEMO"] = "false"

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
