# config.py
"""Configuration settings for the movie recommendation system."""
import json
import os

from dotenv import load_dotenv

load_dotenv()


def _env(key, default=None):
    value = os.getenv(key)
    return default if value is None else value


def _env_int(key, default):
    try:
        return int(_env(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key, default):
    try:
        return float(_env(key, default))
    except (TypeError, ValueError):
        return default


def _env_json_list(key, default):
    raw = _env(key)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else default
    except json.JSONDecodeError:
        return default


# ------------------ User Preferences ------------------
PREFERRED_GENRES = _env_json_list("PREFERRED_GENRES", ["Thriller", "Psychological", "Drama", "Horror"])
AVOID_GENRES = _env_json_list("AVOID_GENRES", ["Romance", "Musical"])
MIN_RATING = _env_float("MIN_RATING", 7.5)
YEAR_RANGE = (_env_int("YEAR_START", 1990), _env_int("YEAR_END", 2026))
PREFERRED_PACING = _env("PREFERRED_PACING", "slow-burn")
HIDDEN_GEM_THRESHOLD = _env_int("HIDDEN_GEM_THRESHOLD", 50000)
HIDDEN_GEM_BONUS_FACTOR = _env_float("HIDDEN_GEM_BONUS_FACTOR", 0.1)
LIKED_MOVIES = _env_json_list("LIKED_MOVIES", ["Nightcrawler", "Prisoners", "The Machinist"])

# ------------------ Scoring Weights ------------------
WEIGHT_IMDB = _env_float("WEIGHT_IMDB", 0.4)
WEIGHT_AUDIENCE = _env_float("WEIGHT_AUDIENCE", 0.3)
WEIGHT_GENRE = _env_float("WEIGHT_GENRE", 0.2)
WEIGHT_HIDDEN_GEM = _env_float("WEIGHT_HIDDEN_GEM", 0.1)

# ------------------ Scraper Settings ------------------
SCRAPE_SOURCE = _env("SCRAPE_SOURCE", "imdb")
MAX_PAGES = _env_int("MAX_PAGES", 5)
REQUEST_DELAY = _env_float("REQUEST_DELAY", 2)
USER_AGENT = _env("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

# ------------------ Database Settings ------------------
DB_BACKEND = _env("DB_BACKEND", "mysql").lower()  # mysql | sqlite
DB_HOST = _env("DB_HOST", "localhost")
DB_PORT = _env_int("DB_PORT", 3306)
DB_USER = _env("DB_USER", "movie_user")
DB_PASSWORD = _env("DB_PASSWORD", "")
DB_NAME = _env("DB_NAME", "movie_recommender")
SQLITE_PATH = _env("SQLITE_PATH", "movie_recommender.db")

# ------------------ Application Settings ------------------
TOP_N_RECOMMENDATIONS = _env_int("TOP_N_RECOMMENDATIONS", 10)
SCHEDULE_TIME_SATURDAY = _env("SCHEDULE_TIME_SATURDAY", "20:00")
SCHEDULE_TIME_SUNDAY = _env("SCHEDULE_TIME_SUNDAY", "20:00")
ICS_OUTPUT_FILE = _env("ICS_OUTPUT_FILE", "movie_schedule.ics")
APP_TIMEZONE = _env("APP_TIMEZONE", "")  # Empty means local system timezone
GUI_THEME = _env("GUI_THEME", "dark")

# ------------------ Google Calendar Settings ------------------
GOOGLE_CREDENTIALS_FILE = _env("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = _env("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_CALENDAR_ID = _env("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_SCOPES = _env_json_list("GOOGLE_SCOPES", ["https://www.googleapis.com/auth/calendar.events"])
GOOGLE_EVENT_DURATION_MINUTES = _env_int("GOOGLE_EVENT_DURATION_MINUTES", 150)