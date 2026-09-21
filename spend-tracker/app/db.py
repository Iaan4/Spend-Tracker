"""SQLite access layer.

Design notes:
- Money is stored as INTEGER cents (never floats) so sums are exact.
- Dates are stored as ISO-8601 TEXT (YYYY-MM-DD). ISO strings sort
  lexicographically in date order, so range queries and indexes just work.
- All SQL uses bound parameters (no string-built values -> no injection).
"""
from __future__ import annotations

import sqlite3
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL CHECK (length(category) BETWEEN 1 AND 50),
    note         TEXT    NOT NULL DEFAULT '',
    spent_on     TEXT    NOT NULL CHECK (spent_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_expenses_spent_on ON expenses (spent_on);
CREATE INDEX IF NOT EXISTS idx_expenses_category_spent_on ON expenses (category, spent_on);
"""


def connect(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may run a dependency and the endpoint on
    # different worker threads. Each request still gets its own connection, so
    # a connection is never used concurrently.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_connection(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- queries

def insert_expense(
    conn: sqlite3.Connection, amount_cents: int, category: str, note: str, spent_on: str
) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO expenses (amount_cents, category, note, spent_on) VALUES (?, ?, ?, ?)",
        (amount_cents, category, note, spent_on),
    )
    conn.commit()
    return conn.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()


def _filters(category: str | None, start: str | None, end: str | None) -> tuple[str, list]:
    clauses, params = [], []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if start:
        clauses.append("spent_on >= ?")
        params.append(start)
    if end:
        clauses.append("spent_on <= ?")  # inclusive end date
        params.append(end)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_expenses(
    conn: sqlite3.Connection,
    category: str | None,
    start: str | None,
    end: str | None,
    limit: int,
    offset: int,
) -> tuple[list[sqlite3.Row], int]:
    where, params = _filters(category, start, end)
    total = conn.execute(f"SELECT COUNT(*) FROM expenses{where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM expenses{where} ORDER BY spent_on DESC, id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return rows, total


def totals_by_category(conn: sqlite3.Connection, start: str, end_exclusive: str) -> dict[str, int]:
    """Sum of cents per category for start <= date < end_exclusive."""
    rows = conn.execute(
        "SELECT category, SUM(amount_cents) AS total FROM expenses "
        "WHERE spent_on >= ? AND spent_on < ? GROUP BY category",
        (start, end_exclusive),
    ).fetchall()
    return {r["category"]: r["total"] for r in rows}


def all_time_total(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM expenses").fetchone()[0]


def delete_expense(conn: sqlite3.Connection, expense_id: int) -> bool:
    """Delete one expense. Returns False if no row had that id."""
    cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()
    return cur.rowcount > 0
