# calendar_exporter/google_calendar.py
import os
from datetime import datetime, timedelta

import config
from utils.helpers import ensure_timezone, get_local_timezone_name
from utils.logger import get_logger

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover - optional for non-google users
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None
    HttpError = Exception

logger = get_logger(__name__)


class GoogleCalendarError(Exception):
    """Raised when calendar authentication or sync fails."""


class GoogleCalendarRevokedError(GoogleCalendarError):
    """Raised when OAuth refresh token is revoked/invalid (requires re-auth)."""


class GoogleCalendarExporter:
    def __init__(self):
        self.service = None
        self.credentials = None

    def is_configured(self):
        return os.path.exists(config.GOOGLE_CREDENTIALS_FILE)

    def authenticate(self, interactive=True):
        if not InstalledAppFlow or not build:
            raise GoogleCalendarError(
                "Google API libraries missing. Install dependencies from requirements.txt."
            )

        if not self.is_configured():
            raise GoogleCalendarError(
                f"Missing OAuth credentials file: {config.GOOGLE_CREDENTIALS_FILE}"
            )

        creds = None
        if os.path.exists(config.GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_FILE, config.GOOGLE_SCOPES)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                msg = str(exc)
                logger.warning(f"Token refresh failed: {msg}")
                if "invalid_grant" in msg or "revoked" in msg.lower():
                    raise GoogleCalendarRevokedError("OAuth token revoked or invalid. Please reauthenticate.") from exc
                creds = None

        if not creds or not creds.valid:
            if not interactive:
                raise GoogleCalendarError("User authentication required.")
            flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_CREDENTIALS_FILE, config.GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(config.GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

        self.credentials = creds
        self.service = build("calendar", "v3", credentials=creds)
        return self.service

    def _require_service(self, interactive_auth: bool):
        if not self.service:
            self.authenticate(interactive=interactive_auth)

    @staticmethod
    def _is_revoked_http_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "invalid_grant" in msg or "revoked" in msg or "unauthorized_client" in msg

    def find_existing_event(self, *, summary: str, start_datetime, end_datetime, payload_hash: str):
        """
        Query Google Calendar for potential duplicates around the start time window.

        Returns a dict: {found_event: event_or_none, action_hint: "payload_hash_match"|"duplicate_candidates"|"no_match"}.
        """
        self._require_service(interactive_auth=True)

        # Narrow time window for dedupe: +/- 2 minutes around the scheduled start.
        start_dt = ensure_timezone(start_datetime)
        end_dt = ensure_timezone(end_datetime)
        time_min = (start_dt - timedelta(minutes=2)).isoformat()
        time_max = (end_dt + timedelta(minutes=2)).isoformat()

        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId=config.GOOGLE_CALENDAR_ID,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=10,
                )
                .execute()
            )
        except HttpError as exc:
            if self._is_revoked_http_error(exc):
                raise GoogleCalendarRevokedError("OAuth token revoked or invalid.") from exc
            raise GoogleCalendarError(str(exc)) from exc

        items = events_result.get("items", []) or []
        candidates = []
        for ev in items:
            if (ev.get("summary") or "") != summary:
                continue
            ev_start = ev.get("start", {}).get("dateTime")
            if not ev_start:
                continue
            try:
                ev_start_dt = ev_start
                # If payloadHash is present, it is the strongest match.
                priv = (ev.get("extendedProperties") or {}).get("private") or {}
                ev_hash = priv.get("payloadHash")
                ev_start_parsed = None
                try:
                    ev_start_parsed = ensure_timezone(datetime.fromisoformat(ev_start_dt))
                except Exception:
                    ev_start_parsed = None

                # Compare within minute precision.
                if ev_start_parsed and abs((ev_start_parsed - start_dt).total_seconds()) <= 60:
                    candidates.append(ev)
                elif ev_start_dt and ev_start_dt.startswith(start_dt.isoformat()[:19]):
                    candidates.append(ev)
            except Exception:
                continue

        if not candidates:
            return {"found_event": None, "action_hint": "no_match"}

        payload_hash_matches = []
        for ev in candidates:
            priv = (ev.get("extendedProperties") or {}).get("private") or {}
            if priv.get("payloadHash") == payload_hash:
                payload_hash_matches.append(ev)

        if len(payload_hash_matches) >= 1:
            # Exact payload match means the event already corresponds to our watchlist payload.
            return {"found_event": payload_hash_matches[0], "action_hint": "payload_hash_match"}

        # No payload-hash match, but if there is exactly one candidate at the same time/title,
        # we treat it as the same logical event and update it (e.g. user changed location/description).
        if len(candidates) == 1:
            return {"found_event": candidates[0], "action_hint": "single_candidate_time_match"}

        # Multiple candidates but no payload hash match => likely duplicates already exist.
        # We'll skip inserting a new event.
        return {"found_event": candidates[0], "action_hint": "duplicate_candidates"}

    def _build_event_body(self, *, summary: str, start_datetime, description: str, location: str, reminder_minutes: int, payload_hash: str):
        start_dt = ensure_timezone(start_datetime)
        end_dt = start_dt + timedelta(minutes=config.GOOGLE_EVENT_DURATION_MINUTES)
        timezone_name = get_local_timezone_name()

        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone_name},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": reminder_minutes}],
            },
            "extendedProperties": {"private": {"payloadHash": payload_hash}},
        }
        return body

    def upsert_event_with_dedupe(
        self,
        *,
        summary: str,
        start_datetime,
        description: str = "",
        location: str = "",
        payload_hash: str,
        existing_event_id: str = None,
        reminder_minutes: int = 30,
        interactive_auth: bool = True,
    ):
        """
        Create or update a Google Calendar event with deduplication.

        Returns: {event: dict, action: "inserted"|"updated"|"duplicate_skipped"}
        """
        self._require_service(interactive_auth=interactive_auth)

        body = self._build_event_body(
            summary=summary,
            start_datetime=start_datetime,
            description=description,
            location=location,
            reminder_minutes=reminder_minutes,
            payload_hash=payload_hash,
        )

        # If we already know the event id, update directly.
        if existing_event_id:
            try:
                event = (
                    self.service.events()
                    .update(
                        calendarId=config.GOOGLE_CALENDAR_ID,
                        eventId=existing_event_id,
                        body=body,
                    )
                    .execute()
                )
                return {"event": event, "action": "updated"}
            except HttpError as exc:
                if self._is_revoked_http_error(exc):
                    raise GoogleCalendarRevokedError("OAuth token revoked or invalid.") from exc
                raise GoogleCalendarError(str(exc)) from exc

        # Otherwise, query Google to avoid duplicate inserts.
        start_dt = ensure_timezone(start_datetime)
        end_dt = start_dt + timedelta(minutes=config.GOOGLE_EVENT_DURATION_MINUTES)
        existing = self.find_existing_event(
            summary=summary,
            start_datetime=start_dt,
            end_datetime=end_dt,
            payload_hash=payload_hash,
        )
        found_event = existing.get("found_event")
        hint = existing.get("action_hint")

        if not found_event:
            try:
                event = (
                    self.service.events()
                    .insert(calendarId=config.GOOGLE_CALENDAR_ID, body=body)
                    .execute()
                )
                return {"event": event, "action": "inserted"}
            except HttpError as exc:
                if self._is_revoked_http_error(exc):
                    raise GoogleCalendarRevokedError("OAuth token revoked or invalid.") from exc
                raise GoogleCalendarError(str(exc)) from exc

        # If payload hash matches (or we only had a single time/title candidate),
        # update instead of inserting a duplicate.
        if hint in ("payload_hash_match", "single_candidate_time_match") and found_event.get("id"):
            try:
                event = (
                    self.service.events()
                    .update(
                        calendarId=config.GOOGLE_CALENDAR_ID,
                        eventId=found_event["id"],
                        body=body,
                    )
                    .execute()
                )
                return {"event": event, "action": "updated"}
            except HttpError as exc:
                if self._is_revoked_http_error(exc):
                    raise GoogleCalendarRevokedError("OAuth token revoked or invalid.") from exc
                raise GoogleCalendarError(str(exc)) from exc

        return {"event": found_event, "action": "duplicate_skipped"}

    def delete_event(self, event_id: str):
        """Delete an event by id (idempotent: 404 treated as success)."""
        self._require_service(interactive_auth=True)
        try:
            self.service.events().delete(calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        except HttpError as exc:
            msg = str(exc).lower()
            if "404" in msg or "notFound".lower() in msg:
                return
            if self._is_revoked_http_error(exc):
                raise GoogleCalendarRevokedError("OAuth token revoked or invalid.") from exc
            raise GoogleCalendarError(str(exc)) from exc

    def reauthenticate(self):
        """Clear stored token and run interactive OAuth flow again."""
        try:
            if os.path.exists(config.GOOGLE_TOKEN_FILE):
                os.remove(config.GOOGLE_TOKEN_FILE)
        except Exception:
            # Token deletion failure should not hard-crash the app.
            pass
        self.service = None
        self.credentials = None
        return self.authenticate(interactive=True)

    def create_or_update_event(
        self,
        summary,
        start_datetime,
        description="",
        location="",
        existing_event_id=None,
        reminder_minutes=30,
    ):
        try:
            # Backwards compatible wrapper: if callers don't pass a payload hash,
            # we fall back to a naive hash on the fields.
            payload_hash = (summary + "|" + str(start_datetime) + "|" + (description or "") + "|" + (location or "")).encode("utf-8")
            import hashlib

            payload_hash = hashlib.sha256(payload_hash).hexdigest()
            res = self.upsert_event_with_dedupe(
                summary=summary,
                start_datetime=start_datetime,
                description=description,
                location=location,
                payload_hash=payload_hash,
                existing_event_id=existing_event_id,
                reminder_minutes=reminder_minutes,
                interactive_auth=True,
            )
            return res["event"]
        except HttpError as exc:
            if self._is_revoked_http_error(exc):
                raise GoogleCalendarRevokedError("OAuth token revoked or invalid.") from exc
            raise GoogleCalendarError(str(exc)) from exc