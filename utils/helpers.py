# utils/helpers.py
import json
import time
import os
import pickle
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo
import config
from utils.logger import get_logger
from zoneinfo import ZoneInfoNotFoundError

try:
    from tzlocal import get_localzone_name
except Exception:  # pragma: no cover
    get_localzone_name = None

logger = get_logger(__name__)

def normalize(value, min_val, max_val):
    """Normalize a value to 0-1 range."""
    if max_val == min_val:
        return 0.5
    return (value - min_val) / (max_val - min_val)

def compute_genre_match(movie_genres, preferred_genres):
    """Return percentage (0-1) of matching genres."""
    if not movie_genres:
        return 0.0
    # Convert to lowercase for comparison
    movie_genres_lower = [g.lower() for g in movie_genres]
    preferred_lower = [g.lower() for g in preferred_genres]
    matches = sum(1 for g in movie_genres_lower if g in preferred_lower)
    return matches / len(preferred_lower) if preferred_lower else 0.0

def compute_hidden_gem_bonus(vote_count, imdb_rating, threshold=config.HIDDEN_GEM_THRESHOLD):
    """Bonus for high-rated but low-popularity movies."""
    if vote_count < threshold and imdb_rating >= 7.0:
        # Scale bonus: 0 if vote_count near threshold, 1 if near 0
        return max(0, 1 - (vote_count / threshold))
    return 0.0


def get_local_timezone_name():
    """Resolve local timezone name with fallback to UTC."""
    if config.APP_TIMEZONE:
        return config.APP_TIMEZONE
    if get_localzone_name:
        try:
            return get_localzone_name()
        except Exception:
            pass
    try:
        return datetime.now().astimezone().tzinfo.key
    except AttributeError:
        # Some tzinfo implementations do not expose .key.
        return str(datetime.now().astimezone().tzinfo) or "UTC"


def ensure_timezone(dt_value, timezone_name=None):
    """Return timezone-aware datetime in configured timezone."""
    tz_name = timezone_name or get_local_timezone_name()
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=tz)
    return dt_value.astimezone(tz)

# Simple file-based cache to avoid re-scraping same page
CACHE_DIR = ".cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def cache_result(cache_key_prefix, ttl=86400):
    """Decorator to cache function results in a file."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create a unique cache key from function name and arguments
            key = f"{cache_key_prefix}_{func.__name__}_{args}_{kwargs}"
            cache_file = os.path.join(CACHE_DIR, f"{hash(key)}.pkl")
            if os.path.exists(cache_file):
                if time.time() - os.path.getmtime(cache_file) < ttl:
                    with open(cache_file, 'rb') as f:
                        logger.debug(f"Cache hit for {func.__name__}")
                        return pickle.load(f)
            result = func(*args, **kwargs)
            with open(cache_file, 'wb') as f:
                pickle.dump(result, f)
            return result
        return wrapper
    return decorator