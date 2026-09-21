import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import add


# ------------------------------------------------------------- create

def test_create_expense_happy_path(client):
    r = client.post("/expenses", json={"amount": "12.50", "category": "Food", "note": " lunch ", "date": "2025-09-01"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1
    assert body["amount"] == 12.5
    assert body["category"] == "food"      # normalised to lower case
    assert body["note"] == "lunch"          # trimmed
    assert body["date"] == "2025-09-01"


def test_date_defaults_to_today(client):
    r = client.post("/expenses", json={"amount": 5, "category": "misc"})
    assert r.status_code == 201
    assert r.json()["date"] == dt.date.today().isoformat()


def test_category_whitespace_and_case_are_normalised(client):
    add(client, 1, category="  Eating   OUT ")
    assert client.get("/expenses?category=eating out").json()["total"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"amount": 0, "category": "food"},                        # zero
        {"amount": -5, "category": "food"},                       # negative
        {"amount": "12.345", "category": "food"},                 # >2 decimal places
        {"amount": "abc", "category": "food"},                    # not a number
        {"amount": "NaN", "category": "food"},                    # NaN
        {"amount": 10_000_000_000_000, "category": "food"},       # absurdly large
        {"category": "food"},                                     # missing amount
        {"amount": 5},                                            # missing category
        {"amount": 5, "category": "   "},                         # blank category
        {"amount": 5, "category": "x" * 51},                      # category too long
        {"amount": 5, "category": "food", "note": "n" * 501},     # note too long
        {"amount": 5, "category": "food", "date": "2025-13-45"},  # impossible date
        {"amount": 5, "category": "food", "date": "yesterday"},   # not ISO
        {"amount": 5, "category": "food", "date": "1999-12-31"},  # too old
        {"amount": 5, "category": "food", "ammount": 3},          # unknown field
    ],
)
def test_invalid_payloads_are_rejected_with_422(client, payload):
    r = client.post("/expenses", json=payload)
    assert r.status_code == 422, r.text
    assert "detail" in r.json()
    assert client.get("/expenses").json()["total"] == 0  # nothing was stored


def test_future_date_rejected(client):
    far = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    assert client.post("/expenses", json={"amount": 5, "category": "x", "date": far}).status_code == 422


def test_malformed_json_returns_422(client):
    r = client.post("/expenses", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_sql_injection_attempt_is_stored_as_plain_text(client):
    evil = "x'); DROP TABLE expenses;--"
    add(client, 3, category="food", note=evil)
    body = client.get("/expenses").json()
    assert body["items"][0]["note"] == evil  # table still exists, value intact


def test_decimal_amounts_are_exact(client):
    for _ in range(10):
        add(client, "0.10")
    s = client.get("/summary?month=2025-09").json()
    assert s["total_spend"] == 1.0  # float math would give 0.9999999999999999


# --------------------------------------------------------------- list

def test_list_filters_by_category_and_inclusive_date_range(client):
    add(client, 10, "food", "2025-08-31")
    add(client, 20, "food", "2025-09-01")
    add(client, 30, "food", "2025-09-30")
    add(client, 40, "food", "2025-10-01")
    add(client, 50, "rent", "2025-09-15")

    r = client.get("/expenses", params={"category": "FOOD", "start_date": "2025-09-01", "end_date": "2025-09-30"})
    amounts = [i["amount"] for i in r.json()["items"]]
    assert amounts == [30, 20]  # boundaries inclusive, newest first, rent excluded
    assert r.json()["total"] == 2


def test_list_pagination(client):
    for i in range(5):
        add(client, i + 1, date=f"2025-09-0{i + 1}")
    page = client.get("/expenses", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert [i["amount"] for i in page["items"]] == [3, 2]


def test_list_rejects_reversed_range(client):
    r = client.get("/expenses", params={"start_date": "2025-09-30", "end_date": "2025-09-01"})
    assert r.status_code == 422


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1000}, {"offset": -1}, {"start_date": "nope"}])
def test_list_rejects_bad_query_params(client, params):
    assert client.get("/expenses", params=params).status_code == 422


def test_list_empty_returns_empty_list(client):
    assert client.get("/expenses").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


# ----------------------------------------------------------- persistence & auth

def test_data_persists_in_real_database_across_app_instances(db_path):
    c1 = TestClient(create_app(db_path=db_path, api_key=""))
    add(c1, 42, "food")
    c2 = TestClient(create_app(db_path=db_path, api_key=""))  # brand-new app, same file
    assert c2.get("/expenses").json()["items"][0]["amount"] == 42


def test_auth_required_when_api_key_configured(db_path):
    c = TestClient(create_app(db_path=db_path, api_key="secret"))
    assert c.get("/expenses").status_code == 401
    assert c.get("/summary").status_code == 401
    assert c.post("/expenses", json={"amount": 1, "category": "x"}).status_code == 401
    assert c.get("/expenses", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/expenses", headers={"X-API-Key": "secret"}).status_code == 200
    assert c.get("/health").status_code == 200  # health check stays open


# ------------------------------------------------------------- delete

def test_delete_removes_only_that_expense_and_updates_summary(client):
    keep = add(client, 10, "food", "2025-09-01")
    gone = add(client, 90, "food", "2025-09-02")
    assert client.get("/summary?month=2025-09").json()["total_spend"] == 100

    r = client.delete(f"/expenses/{gone['id']}")
    assert r.status_code == 204 and r.content == b""

    items = client.get("/expenses").json()["items"]
    assert [i["id"] for i in items] == [keep["id"]]
    assert client.get("/summary?month=2025-09").json()["total_spend"] == 10


def test_delete_missing_expense_returns_404(client):
    r = client.delete("/expenses/999")
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


def test_delete_twice_second_call_is_404(client):
    e = add(client, 5)
    assert client.delete(f"/expenses/{e['id']}").status_code == 204
    assert client.delete(f"/expenses/{e['id']}").status_code == 404


@pytest.mark.parametrize("bad_id", ["abc", "0", "-3", "1.5", str(10**30)])
def test_delete_rejects_invalid_ids_with_422(client, bad_id):
    assert client.delete(f"/expenses/{bad_id}").status_code == 422


def test_delete_requires_api_key_when_configured(db_path):
    c = TestClient(create_app(db_path=db_path, api_key="secret"))
    created = c.post("/expenses", json={"amount": 1, "category": "x", "date": "2025-09-01"},
                     headers={"X-API-Key": "secret"}).json()
    assert c.delete(f"/expenses/{created['id']}").status_code == 401
    assert c.get("/expenses", headers={"X-API-Key": "secret"}).json()["total"] == 1  # still there
    assert c.delete(f"/expenses/{created['id']}", headers={"X-API-Key": "secret"}).status_code == 204
