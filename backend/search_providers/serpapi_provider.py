"""Google Shopping search via SerpApi.

Aggregates prices from Amazon, Flipkart, Walmart, and other retailers
through Google Shopping. Requires a free SerpApi key (5,000 credits/month).
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote_plus

import httpx

from .base import BaseProvider, SearchResult

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


class SerpApiProvider(BaseProvider):
    """Search Google Shopping via SerpApi."""

    @property
    def name(self) -> str:
        return "Google Shopping"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        api_key = os.getenv("SERPAPI_KEY", "")
        if not api_key:
            return []

        params = {
            "engine": "google_shopping",
            "q": query,
            "api_key": api_key,
            "gl": "in",
            "hl": "en",
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(SERPAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("shopping_results", []):
            price = item.get("extracted_price")
            if not price or price <= 0:
                continue

            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    price=float(price),
                    currency="INR" if "\u20b9" in item.get("price", "") else "USD",
                    source=item.get("source", "Google Shopping"),
                    url=item.get("link", ""),
                    rating=item.get("rating"),
                    thumbnail=item.get("thumbnail"),
                    delivery=item.get("delivery"),
                )
            )

        results.sort(key=lambda r: r.price)
        return results[:max_results]


class SerpApiProductProvider(BaseProvider):
    """Search Google Product results via SerpApi for detailed info on a specific product."""

    @property
    def name(self) -> str:
        return "Google Product"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        api_key = os.getenv("SERPAPI_KEY", "")
        if not api_key:
            return []

        params = {
            "engine": "google_product",
            "q": query,
            "api_key": api_key,
            "gl": "in",
            "hl": "en",
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(SERPAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []

        # Parse online sellers
        for seller in data.get("online_sellers", []):
            price = seller.get("price", {}).get("raw_price")
            if not price or price <= 0:
                continue
            results.append(
                SearchResult(
                    title=data.get("title", query),
                    price=float(price),
                    currency="INR" if seller.get("price", {}).get("currency") == "INR" else "USD",
                    source=seller.get("name", ""),
                    url=seller.get("link", ""),
                    rating=seller.get("rating"),
                    delivery=seller.get("shipping", ""),
                )
            )

        results.sort(key=lambda r: r.price)
        return results[:max_results]
