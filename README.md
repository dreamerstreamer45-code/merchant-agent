# MerchantAgent — AI-Powered Price Comparison & Checkout

> A conversational shopping agent that searches across **Amazon, Flipkart, and Google Shopping** in real-time, compares prices, and processes payments via **Razorpay** — all through natural language chat.

## Live Demo

**[Try it live](https://your-app.up.railway.app)**

```
User: "Find cheapest iPhone 15"
Agent: [search_online_prices] → queries 4 sources concurrently
Agent: "Found 6 results! Cheapest is ₹54,900 on Smartprix"
User: "Add it to my cart"
Agent: [add_online_product_to_cart] → cart updated
User: "Checkout"
Agent: [create_razorpay_order] → payment link generated
```

## Architecture

```mermaid
flowchart TB
    User["👤 User (Browser)"]
    UI["🌐 Frontend\nChat + Price Cards + Cart"]
    API["⚡ FastAPI\nPOST /api/chat"]
    Agent["🤖 Checkout Agent\nOpenRouter Free LLMs"]
    Tools["🔧 Tool Functions\nsearch · cart · order"]
    Search["🔍 Price Comparison\nSerpApi + Flipkart + Amazon + DuckDuckGo"]
    Guard["🛡️ Guardrails\nspending limits · stock check"]
    Audit["📋 Audit Trail\nSQLite audit_log table"]
    Razorpay["💳 Razorpay Test API\nOrders + Payment Links"]
    DB[(SQLite\nproducts · cart · orders · audit)]

    User -->|"natural language"| UI
    UI -->|"POST /api/chat"| API
    API --> Agent
    Agent -->|"tool_use blocks"| Tools
    Tools --> Search
    Tools --> Guard
    Guard -->|"validated action"| DB
    Tools -->|"create_order"| Razorpay
    Tools -->|"log every action"| Audit
    Agent -->|"final text reply"| API
    API -->|"JSON response"| UI
    UI -->|"render reply + price cards"| User

    style Agent fill:#6c5ce7,color:#fff
    style Search fill:#00b894,color:#fff
    style Guard fill:#e17055,color:#fff
    style Razorpay fill:#072654,color:#fff
```

## Features

| Feature | Description |
|---------|-------------|
| **Multi-Platform Search** | Searches Amazon, Flipkart, Google Shopping simultaneously |
| **Price Comparison** | Results sorted by cheapest first with source badges |
| **Add to Cart** | Online products added to cart for Razorpay checkout |
| **Razorpay Payments** | Test-mode order creation + payment link generation |
| **Audit Trail** | Every tool call logged with explanation and status |
| **Guardrails** | Spending limits, stock checks, confirmation gates |
| **Free LLMs** | Uses OpenRouter free model fallback chain |
| **Async Search** | All providers queried concurrently with timeout handling |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy |
| LLM | OpenRouter (Inkling, Dots3, Nemotron) via OpenAI SDK |
| Payments | Razorpay Python SDK (test mode) |
| Database | SQLite |
| Search | SerpApi (Google Shopping), RapidAPI (Flipkart/Amazon), DuckDuckGo |
| Frontend | Vanilla HTML/CSS/JS + Three.js (3D animated logo) |
| Tests | pytest + pytest-asyncio (26 tests) |

## Project Structure

```
merchant-agent/
├── backend/
│   ├── main.py                  # FastAPI app, endpoints, lifespan
│   ├── agent.py                 # LLM tool-calling orchestration
│   ├── tools.py                 # 12 validated tool functions
│   ├── models.py                # SQLAlchemy ORM + Pydantic schemas
│   ├── audit.py                 # Audit trail logging
│   ├── razorpay_client.py       # Razorpay SDK wrapper
│   ├── seed.py                  # 60 demo products + 5 coupons
│   └── search_providers/        # Multi-platform price comparison
│       ├── base.py              # Abstract base + SearchResult model
│       ├── serpapi_provider.py  # Google Shopping via SerpApi
│       ├── flipkart_provider.py # Flipkart via RapidAPI
│       ├── amazon_provider.py   # Amazon via RapidAPI
│       ├── duckduckgo_provider.py # Free fallback (no API key)
│       └── aggregator.py        # Concurrent search + dedup + sort
├── frontend/
│   └── index.html               # Chat widget + price cards + cart
├── tests/
│   └── test_all.py              # 26 tests (models, tools, API, search)
├── Dockerfile                   # Railway deployment
├── railway.json                 # Railway config
├── requirements.txt
└── README.md
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/merchant-agent.git
cd merchant-agent
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest pytest-asyncio  # for tests
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env`:

```env
# OpenRouter (free LLMs)
OPENROUTER_API_KEY=sk-or-...

# Razorpay test mode
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...

# Price comparison (at least one recommended)
SERPAPI_KEY=...              # serpapi.com (5,000 free/mo, covers Amazon+Flipkart)
RAPIDAPI_KEY=...             # rapidapi.com (free tier for direct Flipkart/Amazon)
```

### 3. Run

```bash
python -m backend.main
# Open http://127.0.0.1:8000
```

### 4. Run tests

```bash
python -m pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Send message → agent reply + tool actions + cart |
| `GET` | `/api/products` | List local products |
| `GET` | `/api/audit/{session_id}` | Audit trail for a session |
| `GET` | `/api/orders/{session_id}` | Orders for a session |
| `POST` | `/webhook/razorpay` | Razorpay webhook receiver |
| `GET` | `/health` | Liveness check |
| `GET` | `/` | Frontend UI |
| `GET` | `/docs` | Auto-generated API docs |

## Deployment

### Railway (recommended)

1. Push to GitHub
2. Connect repo to [railway.app](https://railway.app)
3. Set environment variables in Railway dashboard
4. Railway auto-deploys via Dockerfile

### Docker

```bash
docker build -t merchant-agent .
docker run -p 8000:8000 --env-file .env merchant-agent
```

## Test Results

```
26 passed in 3.33s

tests/test_all.py::TestSearchResult::test_price_display_inr         PASSED
tests/test_all.py::TestSearchResult::test_price_display_usd         PASSED
tests/test_all.py::TestDuckDuckGoProvider::test_search_returns_list PASSED
tests/test_all.py::TestDuckDuckGoProvider::test_price_extraction    PASSED
tests/test_all.py::TestAggregator::test_deduplication               PASSED
tests/test_all.py::TestTools::test_add_online_product_to_cart       PASSED
tests/test_all.py::TestAPI::test_health                             PASSED
tests/test_all.py::TestAPI::test_products                           PASSED
tests/test_all.py::TestAPI::test_frontend_serves                    PASSED
... (26 total)
```

## License

MIT
