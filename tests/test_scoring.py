from recommender.scoring import MovieScorer


def test_movie_scorer_returns_ranked_scores():
    movies = [
        {"id": 1, "title": "A", "imdb_rating": 8.5, "audience_score": 85, "vote_count": 10000, "genres": ["Thriller"]},
        {"id": 2, "title": "B", "imdb_rating": 7.6, "audience_score": 70, "vote_count": 400000, "genres": ["Romance"]},
    ]
    scored = MovieScorer(movies).compute_scores()
    assert len(scored) == 2
    assert "computed_score" in scored[0]
    assert all(0 <= m["computed_score"] <= 1.5 for m in scored)
