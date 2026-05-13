# scheduler/scheduler.py
import datetime
from utils.logger import get_logger
from utils.helpers import ensure_timezone
import config

logger = get_logger(__name__)

class Scheduler:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_next_weekend_dates(self):
        """Return next Saturday and Sunday dates."""
        today = datetime.date.today()
        # Find next Saturday (weekday 5)
        days_ahead = 5 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        saturday = today + datetime.timedelta(days=days_ahead)
        sunday = saturday + datetime.timedelta(days=1)
        return saturday, sunday

    def schedule_movies(self, movie_ids, saturday_date=None, sunday_date=None):
        """
        Assign movies to weekend slots.
        First movie -> Saturday evening, second (if available) -> Sunday evening.
        """
        if saturday_date is None or sunday_date is None:
            saturday_date, sunday_date = self.get_next_weekend_dates()

        saturday_datetime = datetime.datetime.combine(
            saturday_date,
            datetime.datetime.strptime(config.SCHEDULE_TIME_SATURDAY, "%H:%M").time()
        )
        saturday_datetime = ensure_timezone(saturday_datetime)
        sunday_datetime = datetime.datetime.combine(
            sunday_date,
            datetime.datetime.strptime(config.SCHEDULE_TIME_SUNDAY, "%H:%M").time()
        )
        sunday_datetime = ensure_timezone(sunday_datetime)

        scheduled = []
        if len(movie_ids) >= 1:
            self.db.add_to_watchlist(movie_ids[0], saturday_datetime)
            scheduled.append((movie_ids[0], saturday_datetime))
            logger.info(f"Scheduled movie {movie_ids[0]} for {saturday_datetime}")

        if len(movie_ids) >= 2:
            # Check if movie already scheduled on that day (unlikely)
            query = (
                "SELECT * FROM watchlist WHERE movie_id=? AND scheduled_date=?"
                if self.db.backend == "sqlite"
                else "SELECT * FROM watchlist WHERE movie_id=%s AND scheduled_date=%s"
            )
            existing = self.db.execute_query(
                query,
                (movie_ids[1], sunday_datetime), fetch=True
            )
            if not existing:
                self.db.add_to_watchlist(movie_ids[1], sunday_datetime)
                scheduled.append((movie_ids[1], sunday_datetime))
                logger.info(f"Scheduled movie {movie_ids[1]} for {sunday_datetime}")

        return scheduled

    def auto_schedule_top_recommendations(self, recommender, top_n=2):
        """Automatically get top recommendations and schedule them."""
        top_movies = recommender.generate_recommendations(top_n)
        if not top_movies:
            logger.warning("No recommendations to schedule.")
            return []

        movie_ids = [m['id'] for m in top_movies]
        return self.schedule_movies(movie_ids)