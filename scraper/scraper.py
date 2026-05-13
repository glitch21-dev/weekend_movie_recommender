# scraper/scraper.py
import requests
from bs4 import BeautifulSoup
import time
import config
from utils.logger import get_logger
from utils.helpers import cache_result
from scraper.parsers import parse_imdb_search_result, parse_imdb_detail

logger = get_logger(__name__)

class IMDBScraper:
    BASE_URL = "https://www.imdb.com"
    SEARCH_URL = BASE_URL + "/search/title/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.USER_AGENT,
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def _get_soup(self, url, params=None):
        """Fetch URL and return BeautifulSoup object."""
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            time.sleep(config.REQUEST_DELAY)
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def search_movies(self, start_year=1990, end_year=2026, min_rating=7.5, pages=1):
        """Search IMDb for movies matching criteria."""
        movies = []
        params = {
            'title_type': 'feature',
            'release_date': f'{start_year}-01-01,{end_year}-12-31',
            'user_rating': f'{min_rating},',
            'sort': 'moviemeter,asc',  # popularity? or user_rating,desc
            'count': 50,
        }

        for page in range(1, pages+1):
            params['start'] = (page-1)*50 + 1
            logger.info(f"Scraping page {page} with params {params}")
            soup = self._get_soup(self.SEARCH_URL, params=params)
            if not soup:
                continue

            items = soup.find_all('li', class_='ipc-metadata-list-summary-item')
            logger.info(f"Found {len(items)} items on page {page}")
            for item in items:
                movie_data = parse_imdb_search_result(item)
                if movie_data and movie_data.get('detail_url'):
                    # Fetch detail page for more info
                    detail_html = self._get_soup(movie_data['detail_url'])
                    if detail_html:
                        detail_info = parse_imdb_detail(detail_html.text if hasattr(detail_html, 'text') else str(detail_html))
                        movie_data.update(detail_info)
                    movies.append(movie_data)
        return movies

    @cache_result("imdb_movies", ttl=86400)
    def scrape(self, pages=None):
        """Main scrape method with caching."""
        pages = pages or config.MAX_PAGES
        logger.info(f"Starting scrape for up to {pages} pages")
        return self.search_movies(
            start_year=config.YEAR_RANGE[0],
            end_year=config.YEAR_RANGE[1],
            min_rating=config.MIN_RATING,
            pages=pages
        )