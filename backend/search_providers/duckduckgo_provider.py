"""Fallback product search — uses DuckDuckGo HTML scraping.

DuckDuckGo's general search often includes product pages with prices
from retailers. This provider extracts what it can. Not as reliable
as SerpApi/RapidAPI providers, but requires no API key.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from .base import BaseProvider, SearchResult

logger = logging.getLogger(__name__)

DDG_HTML_URL = "https://html.duckduckgo.com/html/"


class DuckDuckGoProvider(BaseProvider):
    """Search products via DuckDuckGo HTML search (no API key needed)."""

    @property
    def name(self) -> str:
        return "DuckDuckGo"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results: list[SearchResult] = []

        # Try multiple query variations to maximize price hits
        queries = [
            f"{query} buy price INR",
            f"{query} price india online",
            f"{query} best price",
        ]

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for q in queries:
                    if len(results) >= max_results:
                        break
                    resp = await client.post(
                        DDG_HTML_URL,
                        data={"q": q, "kl": "in-en"},
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36"
                            )
                        },
                    )
                    resp.raise_for_status()
                    new_results = _parse_results(resp.text, max_results - len(results))
                    results.extend(new_results)

        except Exception as exc:
            logger.warning("DuckDuckGo search failed: %s", exc)

        results.sort(key=lambda r: r.price)
        return results[:max_results]


def _parse_results(html: str, max_results: int) -> list[SearchResult]:
    """Parse DuckDuckGo HTML results into SearchResult objects."""
    results: list[SearchResult] = []

    # Match result blocks: link + title + snippet
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    for match in pattern.finditer(html):
        if len(results) >= max_results:
            break

        url = _clean(match.group(1))
        title = _clean(match.group(2))
        snippet = _clean(match.group(3))

        if not title or not url or len(title) < 5:
            continue

        # Extract price from title or snippet
        price = _extract_price(title) or _extract_price(snippet)
        if price <= 0:
            continue  # Skip results without identifiable price

        source = _detect_source(url, title, snippet)

        results.append(
            SearchResult(
                title=title,
                price=price,
                currency="INR" if _has_rupee(title + snippet) else "USD",
                source=source,
                url=url,
                rating=_extract_rating(snippet),
            )
        )

    return results


def _clean(text: str) -> str:
    """Strip HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", text)
    for old, new in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#x27;", "'"), ("&nbsp;", " "),
        ("&#39;", "'"), ("&rsquo;", "'"), ("&ndash;", "-"),
    ]:
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def _extract_price(text: str) -> float:
    """Extract numeric price from common patterns."""
    # ₹1,299 / Rs. 1299 / Rs 1299 / INR 1299 / Rs.23,989
    m = re.search(r"(?:₹|Rs\.?\s*|INR\s*)([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Price at Rs 1299 / Price: Rs.1299 / Price ₹1299
    m = re.search(r"price\s*(?:at|:|is)?\s*(?:₹|Rs\.?\s*)?([\d,]+)", text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            if val > 10:
                return val
        except ValueError:
            pass

    # ₹23989 or ₹23,989 (no prefix needed if rupee symbol present)
    m = re.search(r"₹([\d,]+)", text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Rs. 23,989 (with space or period)
    m = re.search(r"Rs\.?\s+([\d,]+)", text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            if val > 10:
                return val
        except ValueError:
            pass

    # $29.99 / USD 29.99
    m = re.search(r"(?:\$|USD\s*)([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return 0.0


def _has_rupee(text: str) -> bool:
    return "\u20b9" in text or "Rs" in text or "INR" in text.upper()


def _extract_rating(text: str) -> Optional[float]:
    m = re.search(r"(\d(?:\.\d)?)\s*(?:out of\s*)?(?:5\s*)?stars?", text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1))
            return val if 0 < val <= 5 else None
        except ValueError:
            pass
    return None


def _detect_source(url: str, title: str, snippet: str) -> str:
    """Detect retailer from URL domain or title/snippet keywords."""
    combined = (url + " " + title + " " + snippet).lower()

    mapping = [
        ("amazon", "Amazon"),
        ("flipkart", "Flipkart"),
        ("myntra", "Myntra"),
        ("ajio", "AJIO"),
        ("croma", "Croma"),
        ("reliance", "Reliance"),
        ("tata", "Tata CLiQ"),
        ("snapdeal", "Snapdeal"),
        ("meesho", "Meesho"),
    ]

    for keyword, source_name in mapping:
        if keyword in combined:
            return source_name

    # Extract domain as fallback
    m = re.search(r"https?://(?:www\.)?([^.]+)", url)
    if m:
        return m.group(1).title()

    return "Online Store"
