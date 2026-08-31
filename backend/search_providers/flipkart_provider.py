"""Flipkart product search via RapidAPI.

Uses the datavio Flipkart API on RapidAPI. Free tier available.
Requires RAPIDAPI_KEY environment variable.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

from .base import BaseProvider, SearchResult

HOST = "flipkart-data-api.p.rapidapi.com"
ENDPOINT = f"https://{HOST}"


class FlipkartProvider(BaseProvider):
    """Search Flipkart products via RapidAPI."""

    @property
    def name(self) -> str:
        return "Flipkart"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        api_key = os.getenv("RAPIDAPI_KEY", "")
        if not api_key:
            return []

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": HOST,
        }

        # The datavio Flipkart API uses /search endpoint
        params = {"query": query, "page": "1"}

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{ENDPOINT}/search",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        products = data.get("data", data.get("products", []))
        if isinstance(products, dict):
            products = products.get("products", [])

        for item in products[:max_results]:
            price = _extract_price(item)
            if price <= 0:
                continue

            results.append(
                SearchResult(
                    title=item.get("title", item.get("name", "")),
                    price=price,
                    currency="INR",
                    source="Flipkart",
                    url=item.get("url", item.get("product_url", "")),
                    rating=_parse_float(item.get("rating", item.get("average_rating"))),
                    thumbnail=item.get("image", item.get("thumbnail", "")),
                    delivery=item.get("delivery", ""),
                )
            )

        results.sort(key=lambda r: r.price)
        return results


def _extract_price(item: dict) -> float:
    """Extract price from various Flipkart API response formats."""
    for key in ("price", "selling_price", "final_price", "mrp"):
        val = item.get(key)
        if val is not None:
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                cleaned = val.replace(",", "").replace("₹", "").strip()
                try:
                    return float(cleaned)
                except ValueError:
                    continue
    return 0.0


def _parse_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
