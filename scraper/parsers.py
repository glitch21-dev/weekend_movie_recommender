# scraper/parsers.py
import re
from bs4 import BeautifulSoup

def parse_imdb_search_result(item):
    """Parse one movie item from IMDb search results."""
    title_elem = item.find('h3', class_='ipc-title__text')
    if not title_elem:
        return None
    title_text = title_elem.text.strip()
    # Title usually like "1. The Shawshank Redemption"
    title = re.sub(r'^\d+\.\s*', '', title_text)

    # Year
    year_span = item.find('span', class_='sc-479faa3c-8 bNrEFi dli-title-metadata-item')
    year = None
    if year_span:
        year_match = re.search(r'\b(19|20)\d{2}\b', year_span.text)
        if year_match:
            year = int(year_match.group())

    # Rating
    rating_elem = item.find('span', class_='ipc-rating-star--imdb')
    imdb_rating = None
    if rating_elem:
        rating_text = rating_elem.text.strip()
        rating_match = re.search(r'(\d+\.\d+)', rating_text)
        if rating_match:
            imdb_rating = float(rating_match.group(1))

    # Vote count (not always in search results; may need to fetch detail page)
    vote_count = 0

    # Genres not available in search list; we'll fetch from detail page

    # Get detail page URL
    link_elem = item.find('a', class_='ipc-title-link-wrapper')
    detail_url = None
    if link_elem and link_elem.get('href'):
        detail_url = "https://www.imdb.com" + link_elem['href'].split('?')[0]

    return {
        'title': title,
        'year': year,
        'imdb_rating': imdb_rating,
        'vote_count': vote_count,
        'detail_url': detail_url
    }

def parse_imdb_detail(html):
    """Parse IMDb movie detail page for genres and vote count."""
    soup = BeautifulSoup(html, 'html.parser')

    # Genres
    genres = []
    genre_section = soup.find('div', {'data-testid': 'genres'})
    if genre_section:
        genre_links = genre_section.find_all('a', class_='ipc-chip--on-baseAlt')
        genres = [a.text.strip() for a in genre_links]

    # Vote count
    vote_elem = soup.find('div', class_='sc-7ab21ed2-3 dPVcnq')
    vote_count = 0
    if vote_elem:
        vote_text = vote_elem.text
        vote_match = re.search(r'([\d,]+)', vote_text)
        if vote_match:
            vote_count = int(vote_match.group(1).replace(',', ''))

    # Audience score from Rotten Tomatoes (if linked)
    rt_audience_score = None
    rt_link = soup.find('a', href=re.compile(r'rottentomatoes\.com'))
    if rt_link:
        # Could fetch RT page separately, but for simplicity we'll skip or use a separate scraper
        pass

    return {
        'genres': genres,
        'vote_count': vote_count,
        'audience_score': rt_audience_score
    }