import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    # api_key="" explicitly disables auth for the general tests.
    return TestClient(create_app(db_path=db_path, api_key=""))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("SPEND_DB", raising=False)


def add(client, amount, category="food", date="2025-09-01", note="", **kw):
    r = client.post("/expenses", json={"amount": amount, "category": category, "date": date, "note": note})
    assert r.status_code == 201, r.text
    return r.json()
