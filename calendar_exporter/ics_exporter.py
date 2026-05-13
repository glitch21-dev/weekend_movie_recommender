# calendar_exporter/ics_exporter.py
from ics import Calendar, Event
from datetime import timedelta
import config
from utils.logger import get_logger
from utils.helpers import ensure_timezone

logger = get_logger(__name__)

class ICSExporter:
    def __init__(self, db_manager):
        self.db = db_manager

    def generate_ics(self, output_file=None):
        """Generate .ics file for all scheduled unwatched movies."""
        output_file = output_file or config.ICS_OUTPUT_FILE
        watchlist = self.db.get_watchlist(watched_only=False)

        cal = Calendar()
        for item in watchlist:
            if item['watched']:
                continue
            event = Event()
            event.name = f"🎬 {item['title']} ({item['year']})"
            event.begin = ensure_timezone(item['scheduled_date'])
            event.duration = timedelta(minutes=config.GOOGLE_EVENT_DURATION_MINUTES)
            description = f"IMDb: {item['imdb_rating']} | Genres: {item['genres']}"
            event.description = description
            cal.events.add(event)

        with open(output_file, 'w') as f:
            f.write(cal.serialize())
        logger.info(f"ICS file exported to {output_file}")
        return output_file