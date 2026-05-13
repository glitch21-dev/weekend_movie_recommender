# recommender/recommender.py
import config
from utils.logger import get_logger
from recommender.scoring import MovieScorer

logger = get_logger(__name__)

class Recommender:
    def __init__(self, db_manager):
        self.db = db_manager

    def filter_movies(self, movies):
        """Apply user preference filters."""
        filtered = []
        for movie in movies:
            # Year range
            year = movie.get('year')
            if year and (year < config.YEAR_RANGE[0] or year > config.YEAR_RANGE[1]):
                continue

            # Minimum rating
            imdb_rating = movie.get('imdb_rating') or 0
            if imdb_rating < config.MIN_RATING:
                continue

            # Exclude avoided genres (optional: if movie genres are mostly avoided)
            genres = movie.get('genres', [])
            if isinstance(genres, str):
                import json
                try:
                    genres = json.loads(genres)
                except:
                    genres = []
            genres_lower = [g.lower() for g in genres]
            avoided = [g for g in genres_lower if g in [a.lower() for a in config.AVOID_GENRES]]
            if len(avoided) > len(genres_lower)/2:
                continue

            filtered.append(movie)
        return filtered

    def generate_recommendations(self, top_n=None):
       
        top_n = top_n or config.TOP_N_RECOMMENDATIONS
        movies = self.db.get_all_movies()
        if not movies:
            logger.warning("No movies in database. Run scrape first.")
            return []

        # Filter
        filtered = self.filter_movies(movies)
        logger.info(f"After filtering: {len(filtered)} movies remain.")

       
        scorer = MovieScorer(filtered)
        scored = scorer.compute_scores()

        scored.sort(key=lambda x: x['computed_score'], reverse=True)

       
        score_updates = {m['id']: m['computed_score'] for m in scored}
        self.db.update_computed_scores(score_updates)

        return scored[:top_n]