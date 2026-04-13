"""
Web scraper for InfinitePay pages.
Fetches page content, strips HTML boilerplate, and returns clean text with metadata.
"""

import json
import os
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from app.config import INFINITEPAY_URLS, SCRAPED_CACHE_PATH

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

REQUEST_TIMEOUT = 15  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retries


def _fetch_url(url: str) -> Optional[str]:
    """Fetches raw HTML from a URL with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    return None


def _extract_text(html: str, url: str) -> tuple[str, str]:
    """
    Parses HTML and returns (title, clean_text).
    Removes navigation, footer, scripts, and styles.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract page title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    # Remove noisy tags
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()

    # Try to find main content area first, then fall back to body
    content_area = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id="content")
        or soup.find(class_="content")
        or soup.find("body")
    )

    if content_area is None:
        return title, ""

    # Get text and normalise whitespace
    raw_text = content_area.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    clean_text = "\n".join(lines)

    return title, clean_text


def scrape_url(url: str) -> Optional[dict]:
    """
    Scrapes a single URL and returns a document dict or None on failure.

    Returns:
        {"url": str, "title": str, "content": str}
    """
    logger.info("Scraping: %s", url)
    html = _fetch_url(url)
    if not html:
        logger.error("Failed to fetch: %s", url)
        return None

    title, content = _extract_text(html, url)
    if len(content) < 100:
        logger.warning("Very little content extracted from %s (%d chars)", url, len(content))

    return {"url": url, "title": title, "content": content}


def scrape_all_urls(urls: list[str] | None = None, use_cache: bool = True) -> list[dict]:
    """
    Scrapes all InfinitePay URLs and returns a list of document dicts.
    Optionally caches results to disk to speed up re-runs.

    Args:
        urls:      List of URLs to scrape (defaults to INFINITEPAY_URLS).
        use_cache: If True, load from disk cache if available.

    Returns:
        List of {"url", "title", "content"} dicts.
    """
    if urls is None:
        urls = INFINITEPAY_URLS

    cache_file = os.path.join(SCRAPED_CACHE_PATH, "scraped_documents.json")

    if use_cache and os.path.exists(cache_file):
        logger.info("Loading scraped documents from cache: %s", cache_file)
        with open(cache_file, "r", encoding="utf-8") as f:
            documents = json.load(f)
        logger.info("Loaded %d documents from cache.", len(documents))
        return documents

    documents = []
    for url in urls:
        doc = scrape_url(url)
        if doc:
            documents.append(doc)
        time.sleep(0.5)  # be polite to the server

    logger.info("Scraped %d/%d URLs successfully.", len(documents), len(urls))

    # Persist cache
    os.makedirs(SCRAPED_CACHE_PATH, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(documents, f, ensure_ascii=False, indent=2)
    logger.info("Cache saved to: %s", cache_file)

    return documents
