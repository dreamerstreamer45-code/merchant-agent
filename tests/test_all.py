"""Tests for search providers and tools."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.search_providers.base import SearchResult


# ---------------------------------------------------------------------------
# SearchResult model tests
# ---------------------------------------------------------------------------

class TestSearchResult:
    def test_price_display_inr(self):
        r = SearchResult(title="Test", price=1299, currency="INR", source="Amazon")
        assert r.price_display == "\u20b91,299"

    def test_price_display_usd(self):
        r = SearchResult(title="Test", price=29.99, currency="USD", source="Amazon")
        assert r.price_display == "USD 29.99"

    def test_price_display_large_inr(self):
        r = SearchResult(title="Test", price=65999, currency="INR", source="Flipkart")
        assert r.price_display == "\u20b965,999"

    def test_optional_fields_default_none(self):
        r = SearchResult(title="Test", price=100)
        assert r.rating is None
        assert r.thumbnail is None
        assert r.delivery is None
        assert r.url == ""
        assert r.source == ""


# ---------------------------------------------------------------------------
# DuckDuckGo provider tests
# ---------------------------------------------------------------------------

class TestDuckDuckGoProvider:
    @pytest.mark.asyncio
    async def test_search_returns_list(self):
        from backend.search_providers.duckduckgo_provider import DuckDuckGoProvider
        p = DuckDuckGoProvider()
        assert p.name == "DuckDuckGo"
        results = await p.search("test query", max_results=3)
        assert isinstance(results, list)

    def test_price_extraction_inr(self):
        from backend.search_providers.duckduckgo_provider import _extract_price
        assert _extract_price("Price: Rs. 1,299") == 1299.0
        assert _extract_price("Buy for ₹999") == 999.0
        assert _extract_price("INR 5,499") == 5499.0

    def test_price_extraction_usd(self):
        from backend.search_providers.duckduckgo_provider import _extract_price
        assert _extract_price("$29.99") == 29.99
        assert _extract_price("USD 99") == 99.0

    def test_price_extraction_no_price(self):
        from backend.search_providers.duckduckgo_provider import _extract_price
        assert _extract_price("No price here") == 0.0
        assert _extract_price("") == 0.0

    def test_detect_source(self):
        from backend.search_providers.duckduckgo_provider import _detect_source
        assert _detect_source("https://amazon.in/dp/B001", "", "") == "Amazon"
        assert _detect_source("https://flipkart.com/product", "", "") == "Flipkart"
        assert _detect_source("https://myntra.com/shirt", "", "") == "Myntra"

    def test_clean_html(self):
        from backend.search_providers.duckduckgo_provider import _clean
        assert _clean("<b>Hello</b> &amp; World") == "Hello & World"
        assert _clean("  Multiple   spaces  ") == "Multiple spaces"

    def test_rating_extraction(self):
        from backend.search_providers.duckduckgo_provider import _extract_rating
        assert _extract_rating("4.5 out of 5 stars") == 4.5
        assert _extract_rating("Rating: 3 stars") == 3.0
        assert _extract_rating("No rating here") is None


# ---------------------------------------------------------------------------
# Aggregator tests
# ---------------------------------------------------------------------------

class TestAggregator:
    @pytest.mark.asyncio
    async def test_search_all_returns_list(self):
        from backend.search_providers import search_all_products
        results = await search_all_products("test", max_results=3)
        assert isinstance(results, list)

    def test_provider_status(self):
        from backend.search_providers import get_provider_status
        status = get_provider_status()
        assert "DuckDuckGo" in status
        assert status["DuckDuckGo"] == "always available"

    @pytest.mark.asyncio
    async def test_deduplication(self):
        from backend.search_providers.aggregator import _deduplicate
        from backend.search_providers.base import SearchResult
        results = [
            SearchResult(title="iPhone 15 128GB", price=65999, source="Amazon", url="http://a1"),
            SearchResult(title="iPhone 15 128GB", price=64999, source="Amazon", url="http://a2"),
            SearchResult(title="iPhone 15 128GB", price=66999, source="Flipkart", url="http://f1"),
        ]
        deduped = _deduplicate(results)
        # Same source + same title = 1 result (cheapest kept)
        # Different source = separate result
        assert len(deduped) == 2
        amazon_results = [r for r in deduped if r.source == "Amazon"]
        assert amazon_results[0].price == 64999  # cheapest kept


# ---------------------------------------------------------------------------
# Tools tests (sync functions)
# ---------------------------------------------------------------------------

class TestTools:
    def test_search_catalog_empty_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base, init_db
        from backend.tools import search_catalog

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = search_catalog(db, 1, query="anything")
        assert result["count"] == 0
        assert result["results"] == []
        db.close()

    def test_view_catalog_empty(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import view_catalog

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = view_catalog(db, 1)
        assert result["count"] == 0
        db.close()

    def test_get_cart_empty(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import get_cart

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = get_cart(db, 1)
        assert result["item_count"] == 0
        assert result["total_paise"] == 0
        db.close()

    def test_add_to_cart_invalid_quantity(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import add_to_cart

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = add_to_cart(db, 1, product_id=1, quantity=0)
        assert result["blocked"] is True
        db.close()

    def test_add_to_cart_product_not_found(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import add_to_cart

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = add_to_cart(db, 1, product_id=99999, quantity=1)
        assert result["blocked"] is True
        assert "not found" in result["error"].lower()
        db.close()

    def test_apply_coupon_invalid(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import apply_coupon

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = apply_coupon(db, 1, "INVALID")
        assert result["blocked"] is True
        db.close()

    def test_add_online_product_to_cart(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import add_online_product_to_cart

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = add_online_product_to_cart(
            db, 1,
            title="iPhone 15 128GB",
            price=65999.0,
            source="Amazon",
            url="https://amazon.in/dp/B0000",
        )
        assert "product_id" in result
        assert result["source"] == "Amazon"
        assert result["line_total_paise"] == 6599900
        db.close()

    def test_add_online_product_invalid_price(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import Base
        from backend.tools import add_online_product_to_cart

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = add_online_product_to_cart(db, 1, title="Test", price=0)
        assert result["blocked"] is True
        db.close()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.models import Base, init_db
        from backend.seed import seed_database
        from sqlalchemy.orm import sessionmaker

        # Init test DB directly (lifespan doesn't run in TestClient)
        test_engine = init_db("sqlite:///./test_api.db")
        SessionLocal = sessionmaker(bind=test_engine)
        with SessionLocal() as db:
            seed_database(db)

        with TestClient(app) as c:
            yield c

        try:
            import os
            os.remove("test_api.db")
        except PermissionError:
            pass

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_products(self, client):
        response = client.get("/api/products")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        assert len(data["products"]) > 0

    def test_frontend_serves(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "MerchantAgent" in response.text

    def test_audit_empty_session(self, client):
        response = client.get("/api/audit/nonexistent-session")
        assert response.status_code == 200
        data = response.json()
        assert data["entries"] == []
