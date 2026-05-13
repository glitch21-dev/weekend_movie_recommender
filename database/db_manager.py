# database/db_manager.py
import json
import sqlite3
from datetime import datetime
from typing import Optional

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except Exception:  # pragma: no cover - optional dependency in sqlite mode
    mysql = None
    MySQLError = Exception

import config
from utils.logger import get_logger

logger = get_logger(__name__)

class DBManager:
    def __init__(self):
        self.connection = None
        self.backend = config.DB_BACKEND
        self._connect()
        self.initialize_schema()

    def _connect(self):
        if self.backend == "sqlite":
            self.connection = sqlite3.connect(config.SQLITE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
            self.connection.row_factory = sqlite3.Row
            logger.info("Connected to SQLite database")
            return

        try:
            if mysql is None:
                raise RuntimeError("mysql-connector-python is not installed. Use DB_BACKEND=sqlite or install dependencies.")
            self.connection = mysql.connector.connect(
                host=config.DB_HOST,
                port=config.DB_PORT,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                database=config.DB_NAME
            )
            if self.connection.is_connected():
                logger.info("Connected to MySQL database")
        except MySQLError as e:
            logger.error(f"Error connecting to MySQL: {e}")
            raise

    def ensure_connection(self):
        """Reconnect if connection lost."""
        if self.backend == "sqlite":
            if not self.connection:
                self._connect()
            return
        if not self.connection or not self.connection.is_connected():
            self._connect()

    def execute_query(self, query, params=None, fetch=False):
        self.ensure_connection()
        params = params or ()

        if self.backend == "sqlite":
            cursor = self.connection.cursor()
            try:
                cursor.execute(query, params)
                if fetch:
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
                self.connection.commit()
                return cursor.lastrowid
            except sqlite3.Error as e:
                logger.error(f"SQLite query error: {e}")
                self.connection.rollback()
                raise
            finally:
                cursor.close()

        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            if fetch:
                result = cursor.fetchall()
                return result
            else:
                self.connection.commit()
                return cursor.lastrowid
        except MySQLError as e:
            logger.error(f"Query error: {e}")
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def execute_write(self, query: str, params: Optional[tuple] = None) -> int:
        """Execute a write statement and return affected row count."""
        self.ensure_connection()
        params = params or ()

        if self.backend == "sqlite":
            cursor = self.connection.cursor()
            try:
                cursor.execute(query, params)
                self.connection.commit()
                return cursor.rowcount
            except sqlite3.Error as e:
                logger.error(f"SQLite write query error: {e}")
                self.connection.rollback()
                raise
            finally:
                cursor.close()

        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            self.connection.commit()
            return cursor.rowcount
        except MySQLError as e:
            logger.error(f"MySQL write query error: {e}")
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def initialize_schema(self):
        if self.backend == "sqlite":
            self.execute_query(
                """
                CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    year INTEGER,
                    genres TEXT,
                    imdb_rating REAL,
                    audience_score REAL,
                    vote_count INTEGER,
                    popularity_score REAL,
                    computed_score REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(title, year)
                )
                """
            )
            self.execute_query(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    movie_id INTEGER NOT NULL,
                    scheduled_date TEXT NOT NULL,
                    watched INTEGER DEFAULT 0,
                    google_event_id TEXT,
                    google_event_payload_hash TEXT,
                    google_last_sync_at TEXT,
                    google_sync_status TEXT DEFAULT 'pending',
                    google_last_error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(movie_id, scheduled_date),
                    FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
                )
                """
            )
            return

        # MySQL migration-safe adds
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                movie_id INT NOT NULL,
                scheduled_date DATETIME NOT NULL,
                watched TINYINT(1) DEFAULT 0,
                google_event_id VARCHAR(255),
                google_event_payload_hash VARCHAR(64),
                google_last_sync_at VARCHAR(64),
                google_sync_status VARCHAR(32) DEFAULT 'pending',
                google_last_error TEXT,
                created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_movie_schedule (movie_id, scheduled_date),
                CONSTRAINT watchlist_ibfk_1 FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            )
            """
        )
        self.execute_query("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(255)")
        self.execute_query("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_event_payload_hash VARCHAR(64)")
        self.execute_query("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_last_sync_at VARCHAR(64)")
        self.execute_query("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_sync_status VARCHAR(32) DEFAULT 'pending'")
        self.execute_query("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS google_last_error TEXT")

    # ------------------ Movies CRUD ------------------
    def insert_movie(self, movie_data):
        """Insert a new movie. Returns ID."""
        genres_str = json.dumps(movie_data['genres']) if isinstance(movie_data['genres'], list) else movie_data['genres']
        params_common = (
            movie_data['title'],
            movie_data['year'],
            genres_str,
            movie_data['imdb_rating'],
            movie_data.get('audience_score', 0),
            movie_data.get('vote_count', 0),
            movie_data.get('popularity_score', 0),
            movie_data.get('computed_score', 0)
        )

        if self.backend == "sqlite":
            query = """
                INSERT INTO movies (title, year, genres, imdb_rating, audience_score, vote_count, popularity_score, computed_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(title, year) DO UPDATE SET
                    imdb_rating=excluded.imdb_rating,
                    audience_score=excluded.audience_score,
                    vote_count=excluded.vote_count,
                    popularity_score=excluded.popularity_score,
                    computed_score=excluded.computed_score
            """
            self.execute_query(query, params_common)
            result = self.execute_query("SELECT id FROM movies WHERE title=? AND year=?", (movie_data['title'], movie_data['year']), fetch=True)
            return result[0]['id'] if result else None

        query = """
            INSERT INTO movies
            (title, year, genres, imdb_rating, audience_score, vote_count,
             popularity_score, computed_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                imdb_rating = VALUES(imdb_rating),
                audience_score = VALUES(audience_score),
                vote_count = VALUES(vote_count),
                popularity_score = VALUES(popularity_score),
                computed_score = VALUES(computed_score)
        """
        self.execute_query(query, params_common)
        # Fetch id if it was an insert
        result = self.execute_query("SELECT id FROM movies WHERE title=%s AND year=%s",
                                    (movie_data['title'], movie_data['year']), fetch=True)
        return result[0]['id'] if result else None

    def get_all_movies(self):
        query = "SELECT * FROM movies"
        return self.execute_query(query, fetch=True)

    def get_movie_by_id(self, movie_id):
        query = "SELECT * FROM movies WHERE id = ?" if self.backend == "sqlite" else "SELECT * FROM movies WHERE id = %s"
        result = self.execute_query(query, (movie_id,), fetch=True)
        return result[0] if result else None

    def update_computed_scores(self, movie_scores):
        """Batch update computed_score for given movie ids."""
        query = "UPDATE movies SET computed_score = ? WHERE id = ?" if self.backend == "sqlite" else "UPDATE movies SET computed_score = %s WHERE id = %s"
        for movie_id, score in movie_scores.items():
            self.execute_query(query, (score, movie_id))

    # ------------------ Watchlist CRUD ------------------
    def add_to_watchlist(self, movie_id, scheduled_date):
        # Store "local wall time" without tzinfo so MySQL DATETIME compatibility is preserved.
        if isinstance(scheduled_date, datetime) and scheduled_date.tzinfo is not None:
            scheduled_date = scheduled_date.replace(tzinfo=None)
        if self.backend == "sqlite":
            query = """
                INSERT INTO watchlist (movie_id, scheduled_date)
                VALUES (?, ?)
                ON CONFLICT(movie_id, scheduled_date) DO UPDATE SET
                    scheduled_date=excluded.scheduled_date
            """
        else:
            query = """
                INSERT INTO watchlist (movie_id, scheduled_date)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE scheduled_date = VALUES(scheduled_date)
            """
        self.execute_query(query, (movie_id, scheduled_date))

    def get_watchlist(self, watched_only=False):
        query = """
            SELECT w.*, m.title, m.year, m.imdb_rating, m.genres
            FROM watchlist w
            JOIN movies m ON w.movie_id = m.id
        """
        if watched_only:
            query += " WHERE w.watched = 1" if self.backend == "sqlite" else " WHERE w.watched = TRUE"
        rows = self.execute_query(query, fetch=True)
        for row in rows:
            dt = row.get("scheduled_date")
            if self.backend == "sqlite" and isinstance(dt, str):
                try:
                    row["scheduled_date"] = datetime.fromisoformat(dt)
                except ValueError:
                    pass
        return rows

    def mark_as_watched(self, movie_id, scheduled_date=None):
        if isinstance(scheduled_date, datetime) and scheduled_date.tzinfo is not None:
            scheduled_date = scheduled_date.replace(tzinfo=None)
        if scheduled_date:
            query = "UPDATE watchlist SET watched = 1 WHERE movie_id = ? AND scheduled_date = ?" if self.backend == "sqlite" else "UPDATE watchlist SET watched = TRUE WHERE movie_id = %s AND scheduled_date = %s"
            self.execute_query(query, (movie_id, scheduled_date))
        else:
            query = "UPDATE watchlist SET watched = 1 WHERE movie_id = ?" if self.backend == "sqlite" else "UPDATE watchlist SET watched = TRUE WHERE movie_id = %s"
            self.execute_query(query, (movie_id,))

    def set_calendar_sync_result(self, watchlist_id, event_id=None, status="synced", error=None):
        """Backwards-compatible wrapper for sync result updates."""
        self.set_calendar_sync_result_with_meta(
            watchlist_id=watchlist_id,
            event_id=event_id,
            payload_hash=None,
            last_sync_at=None,
            status=status,
            error=error,
        )

    def set_calendar_sync_result_with_meta(
        self,
        watchlist_id: int,
        event_id: Optional[str],
        payload_hash: Optional[str],
        last_sync_at: Optional[str],
        status: str,
        error: Optional[str],
    ) -> None:
        """Update all Google Calendar sync bookkeeping for one watchlist row."""
        if self.backend == "sqlite":
            query = """
                UPDATE watchlist
                SET google_event_id=?,
                    google_event_payload_hash=?,
                    google_last_sync_at=?,
                    google_sync_status=?,
                    google_last_error=?
                WHERE id=?
            """
        else:
            query = """
                UPDATE watchlist
                SET google_event_id=%s,
                    google_event_payload_hash=%s,
                    google_last_sync_at=%s,
                    google_sync_status=%s,
                    google_last_error=%s
                WHERE id=%s
            """
        self.execute_query(
            query,
            (
                event_id,
                payload_hash,
                last_sync_at,
                status,
                error,
                watchlist_id,
            ),
        )

    def try_acquire_sync_lock(self, watchlist_id: int) -> bool:
        """Best-effort row lock via status update (prevents rapid duplicate exports)."""
        if self.backend == "sqlite":
            query = """
                UPDATE watchlist
                SET google_sync_status='syncing',
                    google_last_error=NULL
                WHERE id=?
                  AND google_sync_status NOT IN ('synced','syncing')
            """
            affected = self.execute_write(query, (watchlist_id,))
            return affected > 0

        query = """
            UPDATE watchlist
            SET google_sync_status=%s,
                google_last_error=%s
            WHERE id=%s
              AND google_sync_status NOT IN ('synced','syncing')
        """
        affected = self.execute_write(query, ("syncing", None, watchlist_id))
        return affected > 0

    def clear_calendar_event_link(self, watchlist_id: int) -> None:
        """Remove the linked Google event and reset sync status to pending."""
        if self.backend == "sqlite":
            query = """
                UPDATE watchlist
                SET google_event_id=NULL,
                    google_event_payload_hash=NULL,
                    google_last_sync_at=NULL,
                    google_sync_status='pending',
                    google_last_error=NULL
                WHERE id=?
            """
        else:
            query = """
                UPDATE watchlist
                SET google_event_id=NULL,
                    google_event_payload_hash=NULL,
                    google_last_sync_at=NULL,
                    google_sync_status='pending',
                    google_last_error=NULL
                WHERE id=%s
            """
        self.execute_query(query, (watchlist_id,))

    def get_watchlist_id_by_movie_and_time(self, movie_id: int, scheduled_date: datetime) -> Optional[int]:
        if isinstance(scheduled_date, datetime) and scheduled_date.tzinfo is not None:
            scheduled_date = scheduled_date.replace(tzinfo=None)
        if self.backend == "sqlite":
            query = "SELECT id FROM watchlist WHERE movie_id=? AND scheduled_date=?"
        else:
            query = "SELECT id FROM watchlist WHERE movie_id=%s AND scheduled_date=%s"
        result = self.execute_query(query, (movie_id, scheduled_date), fetch=True)
        if not result:
            return None
        return result[0]["id"]

    def get_watchlist_item(self, watchlist_id):
        query = """
            SELECT w.*, m.title, m.year, m.imdb_rating, m.genres
            FROM watchlist w
            JOIN movies m ON w.movie_id = m.id
            WHERE w.id = ?
        """ if self.backend == "sqlite" else """
            SELECT w.*, m.title, m.year, m.imdb_rating, m.genres
            FROM watchlist w
            JOIN movies m ON w.movie_id = m.id
            WHERE w.id = %s
        """
        result = self.execute_query(query, (watchlist_id,), fetch=True)
        if not result:
            return None
        item = result[0]
        if self.backend == "sqlite":
            dt = item.get("scheduled_date")
            if isinstance(dt, str):
                try:
                    item["scheduled_date"] = datetime.fromisoformat(dt)
                except ValueError:
                    pass
        return item

    def close(self):
        if not self.connection:
            return
        if self.backend == "sqlite":
            self.connection.close()
            logger.info("SQLite connection closed")
            return
        if self.connection.is_connected():
            self.connection.close()
            logger.info("Database connection closed")