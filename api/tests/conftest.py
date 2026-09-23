import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DB = Path("test-brain.db")
os.environ["BRAIN_DATABASE_URL"] = f"sqlite:///{TEST_DB}"
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
