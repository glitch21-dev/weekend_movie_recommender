# app.py
import argparse
from database.db_manager import DBManager
from scraper.scraper import IMDBScraper
from recommender.recommender import Recommender
from scheduler.scheduler import Scheduler
from calendar_exporter.ics_exporter import ICSExporter
from calendar_exporter.google_calendar import GoogleCalendarExporter, GoogleCalendarError
from calendar_exporter.sync_service import sync_watchlist_item
from utils.logger import get_logger
import config
from gui_app import run_gui

logger = get_logger("main")

def scrape_command(args):
    scraper = IMDBScraper()
    movies = scraper.scrape(pages=args.pages)
    if not movies:
        logger.error("No movies scraped.")
        return

    db = DBManager()
    count = 0
    for movie in movies:
        # Skip incomplete data
        if not movie.get('title') or not movie.get('year'):
            continue
        # For audience_score, we don't have it yet; set to 0
        movie['audience_score'] = movie.get('audience_score') or 0
        movie['vote_count'] = movie.get('vote_count') or 0
        db.insert_movie(movie)
        count += 1
    db.close()
    logger.info(f"Scraped and inserted {count} movies.")

def recommend_command(args):
    db = DBManager()
    recommender = Recommender(db)
    top = recommender.generate_recommendations(top_n=args.top_n)
    db.close()

    if not top:
        print("No recommendations found.")
        return

    print("\n TOP RECOMMENDATIONS:\n")
    for i, movie in enumerate(top, 1):
        genres = movie['genres']
        if isinstance(genres, str):
            import json
            try:
                genres = json.loads(genres)
                genres = ', '.join(genres)
            except:
                pass
        print(f"{i}. {movie['title']} ({movie['year']})")
        print(f"   IMDb: {movie['imdb_rating']} | Score: {movie['computed_score']:.2f}")
        print(f"   Genres: {genres}\n")

def schedule_command(args):
    db = DBManager()
    recommender = Recommender(db)
    scheduler = Scheduler(db)

    if args.auto:
        scheduled = scheduler.auto_schedule_top_recommendations(recommender, top_n=2)
        if scheduled:
            print("Scheduled movies for next weekend:")
            for mid, dt in scheduled:
                movie = db.get_movie_by_id(mid)
                print(f"  {movie['title']} - {dt.strftime('%A %H:%M')}")
    else:
        # Manual schedule: expect movie ids as args
        if not args.movie_ids:
            print("Please provide movie IDs to schedule, or use --auto")
            return
        ids = [int(x) for x in args.movie_ids.split(',')]
        scheduled = scheduler.schedule_movies(ids)
        for mid, dt in scheduled:
            movie = db.get_movie_by_id(mid)
            print(f"Scheduled: {movie['title']} on {dt}")

    db.close()

def export_calendar_command(args):
    db = DBManager()
    exporter = ICSExporter(db)
    output = exporter.generate_ics(output_file=args.output)
    print(f"Calendar exported to {output}")
    db.close()


def export_google_command(args):
    db = DBManager()
    exporter = GoogleCalendarExporter()
    watchlist = db.get_watchlist(watched_only=False)
    if not watchlist:
        print("No watchlist items available.")
        db.close()
        return

    if args.watchlist_id:
        watchlist = [w for w in watchlist if w["id"] == args.watchlist_id]
        if not watchlist:
            print(f"No watchlist item found for id={args.watchlist_id}")
            db.close()
            return

    try:
        exporter.authenticate(interactive=not args.non_interactive)
    except GoogleCalendarError as exc:
        print(f"Google auth failed: {exc}")
        db.close()
        return

    synced = 0
    failed = 0
    revoked = 0
    duplicate_skipped = 0

    for item in watchlist:
        if item.get("watched"):
            continue
        res = sync_watchlist_item(
            db,
            exporter,
            item["id"],
            location_override=args.location or "",
            reminder_minutes=30,
            interactive_auth=not args.non_interactive,
        )
        status = res.get("status")
        if status == "synced":
            synced += 1
        elif status == "failed":
            failed += 1
        elif status == "revoked":
            revoked += 1
        elif status == "duplicate_skipped":
            duplicate_skipped += 1

    print(
        "Google Calendar sync complete. "
        f"synced={synced}, failed={failed}, revoked={revoked}, duplicate_skipped={duplicate_skipped}"
    )
    db.close()

def main():
    parser = argparse.ArgumentParser(description="Movie Recommendation & Scheduling System")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Scrape command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape movie data from IMDb")
    scrape_parser.add_argument("--pages", type=int, default=config.MAX_PAGES,
                               help="Number of search result pages to scrape")
    scrape_parser.set_defaults(func=scrape_command)

    # Recommend command
    rec_parser = subparsers.add_parser("recommend", help="Generate movie recommendations")
    rec_parser.add_argument("--top_n", type=int, default=config.TOP_N_RECOMMENDATIONS,
                            help="Number of recommendations to show")
    rec_parser.set_defaults(func=recommend_command)

    # Schedule command
    sched_parser = subparsers.add_parser("schedule", help="Schedule movies for weekend viewing")
    sched_parser.add_argument("--auto", action="store_true",
                              help="Automatically schedule top 2 recommendations")
    sched_parser.add_argument("--movie_ids", type=str,
                              help="Comma-separated list of movie IDs to schedule manually")
    sched_parser.set_defaults(func=schedule_command)

    # Export calendar command
    export_parser = subparsers.add_parser("export_calendar", help="Export schedule to ICS file")
    export_parser.add_argument("--output", type=str, default=config.ICS_OUTPUT_FILE,
                               help="Output ICS file path")
    export_parser.set_defaults(func=export_calendar_command)

    google_export_parser = subparsers.add_parser("export_google", help="Export watchlist to Google Calendar")
    google_export_parser.add_argument("--watchlist_id", type=int, help="Sync only one watchlist item")
    google_export_parser.add_argument("--location", type=str, help="Optional location/platform in event")
    google_export_parser.add_argument(
        "--non_interactive",
        action="store_true",
        help="Fail if authentication is required (no browser prompt)",
    )
    google_export_parser.set_defaults(func=export_google_command)

    gui_parser = subparsers.add_parser("gui", help="Launch the PyQt6 desktop app")
    gui_parser.set_defaults(func=lambda _args: run_gui())

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()