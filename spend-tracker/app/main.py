"""HTTP layer: routing, auth, and error handling. Business logic is in services.py."""
from __future__ import annotations

import datetime as dt
import os
import secrets
import sqlite3
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi import Path as PathParam  # aliased: pathlib.Path is already imported
from fastapi.responses import FileResponse

from . import db, services
from .schemas import ExpenseCreate, ExpenseList, ExpenseOut

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _to_out(row: sqlite3.Row) -> ExpenseOut:
    return ExpenseOut(
        id=row["id"],
        amount=services.cents_to_amount(row["amount_cents"]),
        category=row["category"],
        note=row["note"],
        date=row["spent_on"],
        created_at=row["created_at"],
    )


def create_app(db_path: str | None = None, api_key: str | None = None) -> FastAPI:
    """App factory: lets tests build an isolated app with its own DB file/key."""
    db_path = db_path or os.getenv("SPEND_DB", "spend.db")
    # Explicit arg wins (even ""), else env var. Empty string == auth disabled.
    api_key = (api_key if api_key is not None else os.getenv("API_KEY")) or None
    db.init_db(db_path)

    app = FastAPI(title="Spend Tracker", version="1.0.0")

    def get_conn():
        yield from db.get_connection(db_path)

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        # Auth is opt-in: enabled only when API_KEY is configured.
        if api_key is None:
            return
        if not x_api_key or not secrets.compare_digest(x_api_key, api_key):
            raise HTTPException(status_code=401, detail="Missing or invalid API key (X-API-Key header)")

    auth = [Depends(require_api_key)]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/expenses", response_model=ExpenseOut, status_code=201, dependencies=auth)
    def create_expense(payload: ExpenseCreate, conn: sqlite3.Connection = Depends(get_conn)):
        cents = int((payload.amount * Decimal(100)).to_integral_value())
        spent_on = (payload.date or dt.date.today()).isoformat()
        row = db.insert_expense(conn, cents, payload.category, payload.note, spent_on)
        return _to_out(row)

    @app.get("/expenses", response_model=ExpenseList, dependencies=auth)
    def list_expenses(
        category: str | None = Query(default=None, max_length=50),
        start_date: dt.date | None = Query(default=None, description="Inclusive, YYYY-MM-DD"),
        end_date: dt.date | None = Query(default=None, description="Inclusive, YYYY-MM-DD"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        if start_date and end_date and start_date > end_date:
            raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
        cat = " ".join(category.split()).lower() if category else None
        rows, total = db.list_expenses(
            conn,
            cat,
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
            limit,
            offset,
        )
        return ExpenseList(items=[_to_out(r) for r in rows], total=total, limit=limit, offset=offset)

    @app.delete("/expenses/{expense_id}", status_code=204, dependencies=auth)
    def delete_expense(
        # le=2**63-1 keeps the id inside SQLite's INTEGER range (else -> 500 overflow).
        expense_id: int = PathParam(ge=1, le=2**63 - 1),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        if not db.delete_expense(conn, expense_id):
            raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")

    @app.get("/summary", dependencies=auth)
    def summary(
        month: str | None = Query(default=None, description="YYYY-MM; defaults to current month"),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        try:
            first = services.parse_month(month) if month else dt.date.today().replace(day=1)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return services.build_summary(conn, first)

    return app

