"""Pure business logic (no HTTP, mostly no DB) so it is trivially unit-testable."""
from __future__ import annotations

import datetime as dt
import re
import sqlite3

from . import db

# A category is flagged when its spend rises by MORE than this vs last month.
INSIGHT_THRESHOLD_PCT = 25

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def cents_to_amount(cents: int) -> float:
    return round(cents / 100, 2)


def parse_month(month: str) -> dt.date:
    """'2026-09' -> date(2026, 9, 1). Raises ValueError on bad input."""
    if not _MONTH_RE.match(month):
        raise ValueError("month must look like YYYY-MM, e.g. 2026-09")
    return dt.date(int(month[:4]), int(month[5:7]), 1)


def month_key(first_of_month: dt.date) -> str:
    return first_of_month.strftime("%Y-%m")


def next_month(first: dt.date) -> dt.date:
    return dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def previous_month(first: dt.date) -> dt.date:
    return dt.date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def pct_change(previous: int, current: int) -> float | None:
    """Percent change, rounded to 1 dp. None when previous is 0 (undefined)."""
    if previous == 0:
        return None
    return round((current - previous) * 100 / previous, 1)


def exceeds_threshold(previous: int, current: int, threshold_pct: int = INSIGHT_THRESHOLD_PCT) -> bool:
    """True if current is MORE than threshold% above previous.

    Integer arithmetic on purpose: exactly +20% must not be flagged, and float
    rounding must not push it over the line.
    """
    return previous > 0 and current * 100 > previous * (100 + threshold_pct)


def category_changes(current: dict[str, int], previous: dict[str, int]) -> list[dict]:
    changes = []
    for cat in sorted(set(current) | set(previous)):
        cur, prev = current.get(cat, 0), previous.get(cat, 0)
        changes.append(
            {
                "category": cat,
                "previous": cents_to_amount(prev),
                "current": cents_to_amount(cur),
                "percent_change": pct_change(prev, cur),
                "flagged": exceeds_threshold(prev, cur),
            }
        )
    return changes


def build_summary(conn: sqlite3.Connection, month: dt.date) -> dict:
    prev = previous_month(month)
    cur_totals = db.totals_by_category(conn, month.isoformat(), next_month(month).isoformat())
    prev_totals = db.totals_by_category(conn, prev.isoformat(), month.isoformat())

    cur_total, prev_total = sum(cur_totals.values()), sum(prev_totals.values())
    changes = category_changes(cur_totals, prev_totals)

    by_category = [
        {
            "category": cat,
            "total": cents_to_amount(cents),
            "share_pct": round(cents * 100 / cur_total, 1),
        }
        for cat, cents in sorted(cur_totals.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    insights = [
        f"{c['category']} is up {c['percent_change']}% vs {month_key(prev)} "
        f"({c['previous']:.2f} -> {c['current']:.2f})"
        for c in changes
        if c["flagged"]
    ]
    return {
        "month": month_key(month),
        "total_spend": cents_to_amount(cur_total),
        "all_time_total": cents_to_amount(db.all_time_total(conn)),
        "by_category": by_category,
        "previous_month": month_key(prev),
        "previous_month_total": cents_to_amount(prev_total),
        "month_over_month": {
            "absolute_change": cents_to_amount(cur_total - prev_total),
            "percent_change": pct_change(prev_total, cur_total),
        },
        "category_changes": changes,
        "insights": insights,
    }
