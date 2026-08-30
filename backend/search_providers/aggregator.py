"""Aggregator that queries all search providers concurrently and merges results."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .amazon_provider import AmazonProvider
from .base import SearchResult
from .duckduckgo_provider import DuckDuckGoProvider
from .flipkart_provider import FlipkartProvider
from .serpapi_provider import SerpApiProvider

logger = logging.getLogger(__name__)

# Initialize all providers
_providers = [
    SerpApiProvider(),
    FlipkartProvider(),
    AmazonProvider(),
    DuckDuckGoProvider(),
]


async def search_all_products(
    query: str,
    max_results: int = 8,
    providers: Optional[list[str]] = None,
) -> list[SearchResult]:
    """Search all providers concurrently, merge, deduplicate, and sort by price.

    Args:
        query: Product search query
        max_results: Maximum number of results to return
        providers: Optional list of provider names to use (None = all)

    Returns:
        Sorted list of SearchResult objects, cheapest first
    """
    active = _providers
    if providers:
        active = [p for p in _providers if p.name in providers]

    # Run all searches concurrently with individual error handling
    search_tasks = [p.safe_search(query, max_results=max_results) for p in active]

    try:
        all_results = await asyncio.gather(*search_tasks, return_exceptions=True)
    except Exception as exc:
        logger.error("Search aggregator failed: %s", exc)
        return []

    # Flatten results, skipping exceptions
    flat: list[SearchResult] = []
    for result in all_results:
        if isinstance(result, Exception):
            logger.warning("Provider returned exception: %s", result)
            continue
        if isinstance(result, list):
            flat.extend(result)

    # Filter out zero-price or empty-title results
    flat = [r for r in flat if r.price > 0 and r.title.strip()]

    # Deduplicate by similar title + same source
    deduped = _deduplicate(flat)

    # Sort by price ascending
    deduped.sort(key=lambda r: r.price)

    return deduped[:max_results]


def _deduplicate(results: list[SearchResult]) -> list[SearchResult]:
    """Remove duplicate products (same source, similar title).

    Keeps the lowest-priced entry when duplicates are found.
    """
    seen: dict[str, SearchResult] = {}

    for r in results:
        key = f"{r.source.lower()}:{_normalize_title(r.title)}"

        if key in seen:
            # Keep the cheaper one
            if r.price < seen[key].price:
                seen[key] = r
        else:
            seen[key] = r

    return list(seen.values())


def _normalize_title(title: str) -> str:
    """Normalize a product title for deduplication comparison.

    Removes common variations that don't change the product identity:
    - Extra whitespace
    - Common suffixes/prefixes
    - Case differences
    """
    import re

    t = title.lower().strip()
    # Remove common noise words
    t = re.sub(r"\b(buy|new|original|genuine|official|best|top|free delivery)\b", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Truncate to first 60 chars for comparison
    return t[:60]


def get_provider_status() -> dict[str, str]:
    """Return the configuration status of each provider."""
    import os

    status = {}
    for p in _providers:
        if p.name in ("Google Shopping",):
            status[p.name] = "configured" if os.getenv("SERPAPI_KEY") else "no API key"
        elif p.name in ("Flipkart", "Amazon"):
            status[p.name] = "configured" if os.getenv("RAPIDAPI_KEY") else "no API key"
        else:
            status[p.name] = "always available"
    return status
