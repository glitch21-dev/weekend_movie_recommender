from scheduler.scheduler import Scheduler


class DummyDB:
    backend = "sqlite"

    def __init__(self):
        self.calls = []

    def add_to_watchlist(self, movie_id, scheduled_date):
        self.calls.append((movie_id, scheduled_date))

    def execute_query(self, query, params=None, fetch=False):
        return []


def test_scheduler_creates_two_weekend_slots():
    db = DummyDB()
    scheduler = Scheduler(db)
    result = scheduler.schedule_movies([10, 11])
    assert len(result) == 2
    assert db.calls[0][0] == 10
    assert db.calls[1][0] == 11
    assert result[0][1].tzinfo is not None
