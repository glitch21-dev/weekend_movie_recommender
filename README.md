# Weekend Movie Recommender

Python desktop movie recommendation app with MySQL-first storage, optional SQLite fallback, watchlist scheduling, ICS export, and Google Calendar sync.

## Setup

1. Create virtual environment and install dependencies:
   - `python -m venv .venv`
   - `.venv\Scripts\activate`
   - `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill values.
3. Ensure database schema exists (`database/schema.sql`).

## Run

- CLI:
  - `python app.py scrape --pages 2`
  - `python app.py recommend --top_n 10`
  - `python app.py schedule --auto`
  - `python app.py export_calendar`
  - `python app.py export_google`
- GUI:
  - `python app.py gui`

## Google OAuth

1. In Google Cloud Console, create an OAuth Desktop App client.
2. Download credentials JSON and save as `credentials.json` (or set `GOOGLE_CREDENTIALS_FILE`).
3. Run GUI and click **Authenticate Google** (or run `python app.py export_google`).
4. On success, a token file (`token.json`) is created for refreshable sessions.

If credentials are missing, app shows a graceful error and does not fake authentication state.

## Timezone

- Default timezone is local system timezone on Windows.
- Set `APP_TIMEZONE` in `.env` to force a fixed timezone (example: `Europe/Berlin`).

## SQLite fallback (dev/test)

- Set `DB_BACKEND=sqlite` and optionally `SQLITE_PATH=movie_recommender.db`.
- Schema is auto-created at startup for SQLite mode.
