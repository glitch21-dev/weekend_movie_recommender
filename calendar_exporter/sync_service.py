import hashlib
from datetime import datetime
from typing import Optional

import config
from database.db_manager import DBManager
from calendar_exporter.google_calendar import (
    GoogleCalendarError,
    GoogleCalendarExporter,
    GoogleCalendarRevokedError,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def _payload_hash(summary: str, start_datetime: datetime, description: str, location: str) -> str:
    """Stable hash used for idempotency/deduping in Google Calendar."""
    # Ensure stable representation; datetime is expected to be timezone-aware or naive local wall time.
    if start_datetime.tzinfo is not None:
        start_str = start_datetime.isoformat()
    else:
        start_str = start_datetime.isoformat()
    raw = "|".join([summary, start_str, description or "", location or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sync_watchlist_item(
    db: DBManager,
    exporter: GoogleCalendarExporter,
    watchlist_id: int,
    *,
    location_override: str = "",
    reminder_minutes: int = 30,
    interactive_auth: bool = True,
) -> dict:
    """
    Sync exactly one watchlist item to Google Calendar.

    Returns a dict with keys: status, last_error, event_id, action.
    """
    if not db.try_acquire_sync_lock(watchlist_id):
        item = db.get_watchlist_item(watchlist_id) or {}
        return {"status": item.get("google_sync_status"), "last_error": item.get("google_last_error"), "action": "syncing"}

    item = db.get_watchlist_item(watchlist_id)
    if not item:
        db.set_calendar_sync_result_with_meta(
            watchlist_id=watchlist_id,
            event_id=None,
            payload_hash=None,
            last_sync_at=None,
            status="failed",
            error=f"Watchlist item not found: {watchlist_id}",
        )
        return {"status": "failed", "last_error": "Watchlist item not found", "action": "missing"}

    if item.get("watched"):
        # Watched items are not resynced.
        return {"status": "synced", "last_error": None, "action": "skipped_watched"}

    summary = f"Watch: {item['title']} ({item.get('year')})"
    description = f"IMDb: {item.get('imdb_rating')} | Genres: {item.get('genres')}"
    location = location_override or ""
    start_datetime = item["scheduled_date"]

    payload_hash = _payload_hash(summary, start_datetime, description, location)
    prev_event_id = item.get("google_event_id")

    last_sync_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    try:
        result = exporter.upsert_event_with_dedupe(
            summary=summary,
            start_datetime=start_datetime,
            description=description,
            location=location,
            payload_hash=payload_hash,
            existing_event_id=prev_event_id,
            reminder_minutes=reminder_minutes,
            interactive_auth=interactive_auth,
        )
        event = result["event"]
        action = result.get("action", "updated")

        if action in ("inserted", "updated"):
            status = "synced"
        elif action == "duplicate_skipped":
            status = "duplicate_skipped"
        else:
            status = "synced"

        db.set_calendar_sync_result_with_meta(
            watchlist_id=watchlist_id,
            event_id=event.get("id"),
            payload_hash=payload_hash,
            last_sync_at=last_sync_at,
            status=status,
            error=None,
        )
        return {"status": status, "last_error": None, "event_id": event.get("id"), "action": action}
    except GoogleCalendarRevokedError as exc:
        db.set_calendar_sync_result_with_meta(
            watchlist_id=watchlist_id,
            event_id=item.get("google_event_id"),
            payload_hash=payload_hash,
            last_sync_at=last_sync_at,
            status="revoked",
            error=str(exc),
        )
        return {"status": "revoked", "last_error": str(exc), "event_id": item.get("google_event_id"), "action": "revoked"}
    except GoogleCalendarError as exc:
        db.set_calendar_sync_result_with_meta(
            watchlist_id=watchlist_id,
            event_id=item.get("google_event_id"),
            payload_hash=payload_hash,
            last_sync_at=last_sync_at,
            status="failed",
            error=str(exc),
        )
        return {"status": "failed", "last_error": str(exc), "event_id": item.get("google_event_id"), "action": "error"}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected sync error")
        db.set_calendar_sync_result_with_meta(
            watchlist_id=watchlist_id,
            event_id=item.get("google_event_id"),
            payload_hash=payload_hash,
            last_sync_at=last_sync_at,
            status="failed",
            error=str(exc),
        )
        return {"status": "failed", "last_error": str(exc), "event_id": item.get("google_event_id"), "action": "unexpected"}


def bulk_sync_unsynced(
    db: DBManager,
    exporter: GoogleCalendarExporter,
    *,
    location_override: str = "",
    reminder_minutes: int = 30,
    interactive_auth: bool = True,
):
    """Sync all watchlist items that are not marked synced."""
    items = db.get_watchlist(watched_only=False)
    candidates = []
    for it in items:
        if it.get("watched"):
            continue
        status = it.get("google_sync_status") or "pending"
        if status in ("pending", "failed", "duplicate_skipped"):
            candidates.append(it["id"])

    results = []
    for wid in candidates:
        results.append(
            sync_watchlist_item(
                db,
                exporter,
                wid,
                location_override=location_override,
                reminder_minutes=reminder_minutes,
                interactive_auth=interactive_auth,
            )
        )
    return results

