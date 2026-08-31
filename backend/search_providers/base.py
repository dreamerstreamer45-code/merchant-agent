"""Base classes and data models for product search providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchResult:
    """A single product result from any search provider."""

    title: str
    price: float
    currency: str = "INR"
    source: str = ""
    url: str = ""
    rating: Optional[float] = None
    thumbnail: Optional[str] = None
    delivery: Optional[str] = None

    @property
    def price_display(self) -> str:
        if self.currency == "INR":
            return f"\u20b9{self.price:,.0f}"
        return f"{self.currency} {self.price:,.2f}"


class BaseProvider(ABC):
    """Abstract base for all search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'Google Shopping')."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search for products and return normalized results."""

    async def safe_search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search with error handling — returns empty list on failure."""
        try:
            return await self.search(query, max_results)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Provider %s failed: %s", self.name, exc)
            return []
