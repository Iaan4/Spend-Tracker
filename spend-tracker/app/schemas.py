"""Request/response models. Validation lives here so the routes stay thin."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CATEGORY_LEN = 50
MAX_NOTE_LEN = 500


class ExpenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # typos like "ammount" fail loudly

    # Decimal (not float) so 0.1 + 0.2 style errors can't creep in; max 2 dp.
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category: str
    note: str = ""
    date: dt.date | None = None  # defaults to today

    @field_validator("category")
    @classmethod
    def _clean_category(cls, v: str) -> str:
        # Normalise so "Food", " food " and "FOOD" are one category.
        v = " ".join(v.split()).lower()
        if not v:
            raise ValueError("category must not be blank")
        if len(v) > MAX_CATEGORY_LEN:
            raise ValueError(f"category must be at most {MAX_CATEGORY_LEN} characters")
        return v

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str) -> str:
        v = v.strip()
        if len(v) > MAX_NOTE_LEN:
            raise ValueError(f"note must be at most {MAX_NOTE_LEN} characters")
        return v

    @field_validator("date")
    @classmethod
    def _sane_date(cls, v: dt.date | None) -> dt.date | None:
        if v is None:
            return v
        # +1 day of slack so users ahead of UTC can log "today".
        if v > dt.date.today() + dt.timedelta(days=1):
            raise ValueError("date must not be in the future")
        if v.year < 2000:
            raise ValueError("date must be on or after 2000-01-01")
        return v


class ExpenseOut(BaseModel):
    id: int
    amount: float
    category: str
    note: str
    date: dt.date
    created_at: str


class ExpenseList(BaseModel):
    items: list[ExpenseOut]
    total: int
    limit: int
    offset: int
