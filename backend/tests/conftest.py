from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    test_db = tmp_path_factory.mktemp("market-db") / "test.sqlite3"
    original = database.DATABASE_PATH
    database.DATABASE_PATH = test_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        database.DATABASE_PATH = original


@pytest.fixture(scope="session")
def db_path(client):
    with database.connect() as db:
        row = db.execute("PRAGMA database_list").fetchone()
    return Path(row[2])
