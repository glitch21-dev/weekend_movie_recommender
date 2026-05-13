ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_event_payload_hash VARCHAR(64);
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_last_sync_at VARCHAR(64);
