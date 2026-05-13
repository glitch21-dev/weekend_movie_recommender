ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(255);
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_sync_status VARCHAR(32) DEFAULT 'pending';
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_last_error TEXT;
