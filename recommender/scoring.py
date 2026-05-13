# recommender/scoring.py
import config
from utils.helpers import normalize, compute_genre_match, compute_hidden_gem_bonus
from utils.logger import get_logger

logger = get_logger(__name__)

class MovieScorer:
    def __init__(self, movies_df=None):
        """Initialize with list of movie dicts."""
        self.movies = movies_df or []

    def compute_scores(self):
        """Compute final weighted score for all movies."""
        if not self.movies:
            return []

        # Find min/max for normalization
        imdb_vals = [m.get('imdb_rating', 0) or 0 for m in self.movies]
        audience_vals = [m.get('audience_score', 0) or 0 for m in self.movies]
        vote_counts = [m.get('vote_count', 0) or 0 for m in self.movies]

        min_imdb, max_imdb = min(imdb_vals), max(imdb_vals)
        min_aud, max_aud = min(audience_vals), max(audience_vals)
        min_votes, max_votes = min(vote_counts), max(vote_counts)

        scored_movies = []
        for movie in self.movies:
            # Normalize components
            norm_imdb = normalize(movie.get('imdb_rating', 0) or 0, min_imdb, max_imdb)
            norm_audience = normalize(movie.get('audience_score', 0) or 0, min_aud, max_aud)

            # Genre match
            genres = movie.get('genres', [])
            if isinstance(genres, str):
                import json
                try:
                    genres = json.loads(genres)
                except:
                    genres = []
            genre_match = compute_genre_match(genres, config.PREFERRED_GENRES)

            # Hidden gem bonus
            vote_count = movie.get('vote_count', 0) or 0
            imdb_rating = movie.get('imdb_rating', 0) or 0
            hidden_bonus = compute_hidden_gem_bonus(vote_count, imdb_rating)

           
            norm_popularity = normalize(vote_count, min_votes, max_votes)
           
            popularity_penalty = 1.0 - (norm_popularity * 0.1)  # reduce score by up to 10%

            # Final score
            score = (
                config.WEIGHT_IMDB * norm_imdb +
                config.WEIGHT_AUDIENCE * norm_audience +
                config.WEIGHT_GENRE * genre_match +
                config.WEIGHT_HIDDEN_GEM * hidden_bonus
            ) * popularity_penalty

            movie_copy = movie.copy()
            movie_copy['computed_score'] = round(score, 4)
            movie_copy['popularity_score'] = round(norm_popularity, 4)
            scored_movies.append(movie_copy)

        return scored_movies