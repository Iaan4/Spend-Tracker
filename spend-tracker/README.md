# Spend Tracker

A small expense-logging service: a Python REST API (FastAPI + SQLite) and a
one-page UI to add expenses and view a monthly summary.

<img width="1327" height="925" alt="tracker" src="https://github.com/user-attachments/assets/7a9ba233-f51f-4ba9-bc38-52e0d3398333" />


## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:create_app --factory --reload          # http://localhost:8000
```

- UI: <http://localhost:8000/>
- Interactive API docs (auto-generated): <http://localhost:8000/docs>
- Tests: `pytest -q`

Configuration is via environment variables:

| Variable   | Default    | Meaning                                                     |
|------------|------------|-------------------------------------------------------------|
| `SPEND_DB` | `spend.db` | Path of the SQLite file (created on startup)                |
| `API_KEY`  | *(unset)*  | If set, every API call needs an `X-API-Key: <value>` header |

## API

| Method & path    | Description |
|------------------|-------------|
| `POST /expenses` | Body: `{"amount": "12.50", "category": "food", "note": "lunch", "date": "2026-09-01"}`. `note` and `date` are optional (date defaults to today). Returns `201` + the stored expense. |
| `GET /expenses`  | Query: `category`, `start_date`, `end_date` (both inclusive), `limit` (1-200, default 50), `offset`. Newest first. Returns `{items, total, limit, offset}`. |
| `DELETE /expenses/{id}` | Remove one expense. `204` on success, `404` if it doesn't exist, `422` for an invalid id. |
| `GET /summary`   | Query: `month=YYYY-MM` (default: current month). See below. |
| `GET /health`    | Liveness probe (never requires a key). |

`/summary` response (abridged):

```jsonc
{
  "month": "2026-09",
  "total_spend": 130.5,            // spend in the selected month
  "all_time_total": 230.5,         // every expense ever
  "by_category": [{"category": "food", "total": 130.5, "share_pct": 100.0}],
  "previous_month": "2026-08",
  "previous_month_total": 100.0,
  "month_over_month": {"absolute_change": 30.5, "percent_change": 30.5},
  "category_changes": [{"category": "food", "previous": 100.0, "current": 130.5, "percent_change": 30.5, "flagged": true}],
  "insights": ["food is up 30.5% vs 2026-08 (100.00 -> 130.50)"]
}
```

Errors: `401` bad/missing key, `422` validation failure (the body lists each bad
field), `404` unknown route.

## Key design decisions

- **Money is stored as integer cents.** Floats can't represent 0.10 exactly (ten
  10-cent expenses sum to 0.9999...). Input is parsed as `Decimal`, limited to 2
  decimal places, and converted to cents at the edge; there is a test for this.
  Responses expose amounts as JSON numbers rounded to 2 dp for convenience.
- **SQLite with a real schema**: `CHECK` constraints back up the API validation
  (positive amount, category length, ISO date shape) and there are indexes on
  `spent_on` and `(category, spent_on)` for the filter queries. Dates are stored
  as ISO `YYYY-MM-DD` text, which sorts correctly and works with range queries.
  All SQL is parameterised.
- **Layering**: `main.py` (HTTP/auth) -> `services.py` (pure logic: month math,
  % change, insight rule) -> `db.py` (SQL). The logic that matters is testable
  without HTTP.
- **App factory** (`create_app(db_path, api_key)`) so each test gets its own DB
  file and there are no import-time side effects (hence `uvicorn --factory`).
- **Validation rules** (Pydantic): amount > 0 with <= 2 dp; category trimmed,
  lower-cased and 1-50 chars (so "Food" and "food " are one category); note <=
  500 chars; date must be a valid ISO date, not before 2000 and not in the
  future (1 day of slack for timezones); unknown fields are rejected.
- **"Total spend" ambiguity**: the brief doesn't say whether it means all-time or
  per-month, so `/summary` returns both (`total_spend` for the month, plus
  `all_time_total`).
- **Month-over-month when last month is 0**: the percentage is `null`, not
  infinity or an error. A brand-new category is therefore not flagged.
- **Insight (bonus)**: a category is flagged when it rose *more than* 20% vs the
  previous month. Done in integer arithmetic so exactly +20% is not flagged and
  float rounding can't change the answer.
- **Auth (bonus)**: optional API key via `X-API-Key`, compared with
  `secrets.compare_digest`. Off when `API_KEY` is unset so local dev is easy.
- **UI** is a single static HTML file (no build step). It writes user text with
  `textContent`, so a note like `<script>` can't inject markup.

## Deploying

A `Dockerfile` is included. On Render/Railway/Fly: create a web service from the
repo, set `API_KEY` to a long random string, and **attach a persistent
disk/volume mounted at `/data`** (the image sets `SPEND_DB=/data/spend.db`).
Without a volume, SQLite data is wiped on every redeploy on most free tiers.

## What I would do later
- **Timezones**: "today" and month boundaries use the server date; I'd store the user's timezone.
- **Currency** column and a fixed category list (or a categories table) instead of free text; keyset pagination instead of OFFSET.
- Rate limiting, structured logging, pytest, browser-level UI tests.
- Make the insight threshold configurable and compare against a rolling average so one unusual month doesn't dominate.
-Enabling rename option
