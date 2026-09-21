import pytest

from app import services
from tests.conftest import add


# ------------------------------------------------- pure unit tests (no DB)

@pytest.mark.parametrize(
    "prev,cur,expected",
    [(100, 150, 50.0), (200, 100, -50.0), (100, 100, 0.0), (300, 400, 33.3), (0, 500, None), (0, 0, None)],
)
def test_pct_change(prev, cur, expected):
    assert services.pct_change(prev, cur) == expected


def test_threshold_is_strictly_greater_than_20_percent():
    assert services.exceeds_threshold(10_000, 12_001) is True
    assert services.exceeds_threshold(10_000, 12_000) is False  # exactly +20% is NOT flagged
    assert services.exceeds_threshold(10_000, 9_000) is False   # decrease
    assert services.exceeds_threshold(0, 5_000) is False        # no baseline -> cannot compute %


def test_month_arithmetic_across_year_boundary():
    import datetime as dt
    assert services.previous_month(dt.date(2026, 1, 1)) == dt.date(2025, 12, 1)
    assert services.next_month(dt.date(2025, 12, 1)) == dt.date(2026, 1, 1)
    assert services.previous_month(dt.date(2026, 9, 1)) == dt.date(2026, 8, 1)


@pytest.mark.parametrize("bad", ["2025-13", "2025-00", "26-09", "2025-9", "september", "2025-09-01", ""])
def test_parse_month_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        services.parse_month(bad)


# -------------------------------------------------- /summary via the API

def test_summary_empty_database(client):
    s = client.get("/summary?month=2025-09").json()
    assert s["total_spend"] == 0
    assert s["all_time_total"] == 0
    assert s["by_category"] == []
    assert s["month_over_month"] == {"absolute_change": 0, "percent_change": None}
    assert s["insights"] == []


def test_summary_totals_by_category_and_mom(client):
    add(client, 100, "food", "2025-08-10")
    add(client, 50, "rent", "2025-08-01")
    add(client, 130, "food", "2025-09-05")
    add(client, 20, "food", "2025-09-20")
    add(client, 50, "rent", "2025-09-01")

    s = client.get("/summary?month=2025-09").json()
    assert s["total_spend"] == 200
    assert s["all_time_total"] == 350
    assert s["previous_month"] == "2025-08"
    assert s["previous_month_total"] == 150
    assert s["month_over_month"] == {"absolute_change": 50, "percent_change": 33.3}
    assert s["by_category"] == [
        {"category": "food", "total": 150, "share_pct": 75.0},
        {"category": "rent", "total": 50, "share_pct": 25.0},
    ]


def test_summary_month_boundaries_do_not_leak(client):
    add(client, 10, "food", "2025-08-31")
    add(client, 20, "food", "2025-09-01")
    add(client, 40, "food", "2025-09-30")
    add(client, 80, "food", "2025-10-01")
    s = client.get("/summary?month=2025-09").json()
    assert s["total_spend"] == 60
    assert s["previous_month_total"] == 10


def test_mom_when_previous_month_is_empty_is_null_not_error(client):
    add(client, 100, "food", "2025-09-05")
    s = client.get("/summary?month=2025-09").json()
    assert s["month_over_month"]["percent_change"] is None
    assert s["month_over_month"]["absolute_change"] == 100
    assert s["insights"] == []  # a brand-new category is not flagged as "+inf%"


def test_january_compares_against_previous_decembers(client):
    add(client, 100, "food", "2024-12-15")
    add(client, 150, "food", "2025-01-15")
    s = client.get("/summary?month=2025-01").json()
    assert s["previous_month"] == "2024-12"
    assert s["month_over_month"]["percent_change"] == 50.0


def test_insight_flags_only_categories_up_more_than_20_percent(client):
    add(client, 100, "food", "2025-08-10")       # -> 125 = +25%  (flag)
    add(client, 125, "food", "2025-09-10")
    add(client, 100, "fun", "2025-08-10")        # -> 120 = +20%  (exactly: no flag)
    add(client, 120, "fun", "2025-09-10")
    add(client, 100, "rent", "2025-08-10")       # -> 90  = -10%  (no flag)
    add(client, 90, "rent", "2025-09-10")

    s = client.get("/summary?month=2025-09").json()
    flagged = [c["category"] for c in s["category_changes"] if c["flagged"]]
    assert flagged == ["food"]
    assert len(s["insights"]) == 1 and "food" in s["insights"][0] and "25.0%" in s["insights"][0]


def test_category_dropped_to_zero_shows_minus_100(client):
    add(client, 80, "gym", "2025-08-10")
    add(client, 10, "food", "2025-09-10")
    s = client.get("/summary?month=2025-09").json()
    gym = next(c for c in s["category_changes"] if c["category"] == "gym")
    assert gym["percent_change"] == -100.0 and gym["flagged"] is False


@pytest.mark.parametrize("bad", ["2025-13", "abc", "2025-9", "2025-09-01"])
def test_summary_rejects_bad_month(client, bad):
    assert client.get("/summary", params={"month": bad}).status_code == 422


def test_summary_defaults_to_current_month(client):
    import datetime as dt
    assert client.get("/summary").json()["month"] == dt.date.today().strftime("%Y-%m")
