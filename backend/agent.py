"""
OpenRouter (OpenAI-compatible) tool-calling orchestration.

The agent loop:
  1. User sends a message
  2. Message + tool schemas are sent to the model via OpenRouter
  3. Model may return tool_calls → we execute them, audit-log each
  4. Tool results are sent back as "tool" role messages
  5. Repeat until the model gives a final text response

Every state-changing action goes through validated tool functions — the LLM
never fabricates amounts, order IDs, or product prices.

Uses a free-model fallback chain: tries models in order until one succeeds.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session as DBSession

from backend import tools as T
from backend.audit import log_action
from backend.models import Message, Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Free model fallback chain (all $0 cost on OpenRouter with tool support)
# ---------------------------------------------------------------------------

FREE_MODEL_CHAIN: list[str] = [
    "thinkingmachines/inkling:free",          # 41B active params, 1M context
    "dots-studio/dots-3-note-preview:free",   # 16B active, 512K context
    "nvidia/nemotron-3.5-lightning:free",     # 30B MoE (3B active), 1M context
]

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling schema format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": (
                "Search the product catalog by keyword and/or category. "
                "Use this when the customer asks about specific products, wants to browse, "
                "or mentions a product type (e.g. 'earbuds', 'phone case')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword (e.g. 'wireless earbuds', 'phone case')",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category (e.g. 'electronics', 'clothing'). Leave empty to search all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_catalog",
            "description": "Return the full list of available products. Use when the customer wants to see everything.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": (
                "Add a product to the customer's shopping cart by product ID. "
                "Validates stock availability and spending limits. "
                "Use search_catalog first to get product IDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "The product ID from the catalog",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Number of units to add (default 1)",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a product from the shopping cart entirely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "The product ID to remove",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cart",
            "description": "Show the current cart contents, item count, and total price.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_coupon",
            "description": (
                "Apply a discount coupon code. Validates the coupon and applies the discount. "
                "Maximum discount is capped at 25%."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The coupon code (e.g. 'SAVE10', 'FLAT20')",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_razorpay_order",
            "description": (
                "Create a Razorpay test-mode order from the current cart. "
                "This initiates the checkout process. For orders above ₹500, "
                "this will return a confirmation prompt — the user must confirm "
                "before the order is created."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_order",
            "description": (
                "Confirm and execute a previously-previewed order (for high-value orders "
                "that required confirmation). Call this only after the user explicitly says "
                "yes/confirm to the order preview."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_payment",
            "description": (
                "Generate a Razorpay payment link for a confirmed order. "
                "Returns a shareable URL the customer can click to pay."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_db_id": {
                        "type": "integer",
                        "description": "The internal order database ID (from create_razorpay_order result)",
                    },
                },
                "required": ["order_db_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recommendations",
            "description": (
                "Get upsell/cross-sell recommendations based on the current cart contents. "
                "Use this when the customer asks for suggestions or after adding items."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a friendly, helpful shopping assistant for an online store.

Your job is to help customers:
1. Browse and discover products (use search_catalog or view_catalog)
2. Add items to their cart (use add_to_cart)
3. Remove items if they change their mind (use remove_from_cart)
4. View their cart and totals (use get_cart)
5. Apply discount coupons if they have one (use apply_coupon)
6. Get product recommendations (use get_recommendations)
7. Complete checkout via Razorpay (use create_razorpay_order)

IMPORTANT RULES:
- NEVER make up product IDs, prices, or order IDs. Always use tool results.
- When a customer asks to add something, first search the catalog to get the product ID.
- For orders above ₹500, the create_razorpay_order tool will return a confirmation prompt. Ask the customer to confirm before calling confirm_order.
- Always show the cart total after adding/removing items.
- Be conversational and helpful. Suggest relevant products when appropriate.
- If a customer wants to check out, make sure their cart isn't empty first.
- If the customer provides a coupon code, use apply_coupon to validate and apply it.

When calling tools, explain what you're doing naturally in your response.
After receiving tool results, summarize them clearly for the customer.
"""


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class CheckoutAgent:
    """OpenRouter-powered conversational checkout agent with free-model fallback."""

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("OPENROUTER_MODEL", "")
        self.model_chain = [self.model] if self.model else list(FREE_MODEL_CHAIN)
        self._client: OpenAI | None = None
        self.max_tool_rounds = 10  # safety limit

    @property
    def client(self) -> OpenAI:
        """Lazy-init the OpenAI client so the app boots without a key set."""
        if self._client is None:
            api_key = os.getenv("OPENROUTER_API_KEY", "")
            if not api_key:
                raise RuntimeError(
                    "OPENROUTER_API_KEY must be set in .env. "
                    "Get one at https://openrouter.ai/keys"
                )
            self._client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
        return self._client

    def chat(
        self,
        db: DBSession,
        session_id: str,
        user_message: str,
    ) -> dict:
        """Process one user message and return the agent's reply.

        Returns:
            {
                "reply": "text response",
                "tool_actions": [...],  # list of {tool, args, result, audit_id}
                "cart": [...],          # current cart state
                "awaiting_confirmation": bool,
            }
        """
        # Get or create DB session
        db_session = T.get_or_create_session(db, session_id)

        # Load conversation history
        history = self._load_history(db, db_session.id)

        # Add the new user message
        history.append({"role": "user", "content": user_message})

        # Store the user message
        db.add(Message(session_id=db_session.id, role="user", content=user_message))
        db.commit()

        # Agent loop: keep calling tools until the model gives a final text response
        tool_actions = []
        awaiting_confirmation = False

        for round_num in range(self.max_tool_rounds):
            response = None
            last_error = None
            for model_name in self.model_chain:
                try:
                    response = self.client.chat.completions.create(
                        model=model_name,
                        max_tokens=2048,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            *history,
                        ],
                        tools=TOOL_DEFINITIONS,
                        tool_choice="auto",
                    )
                    logger.info("Using model: %s", model_name)
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning("Model %s failed: %s — trying next", model_name, exc)
                    continue

            if response is None:
                logger.error("All models in chain failed: %s", last_error)
                return {
                    "reply": "I'm having trouble connecting to the AI service. Please try again in a moment.",
                    "tool_actions": [],
                    "cart": T.get_cart(db, db_session.id).get("items", []),
                    "awaiting_confirmation": False,
                }

            choice = response.choices[0]
            message = choice.message

            # Check if the model wants to use tools
            if message.tool_calls:
                # Add assistant message with tool calls to history
                assistant_msg = {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
                history.append(assistant_msg)

                # Execute each tool call
                for tc in message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    result = self._execute_tool(db, db_session.id, tool_name, args)

                    # Audit log
                    audit_entry = log_action(
                        db,
                        session_id=db_session.id,
                        action=tool_name,
                        tool_name=tool_name,
                        arguments=args,
                        result=result,
                        status="blocked" if result.get("blocked") else "success",
                        guardrail=result.get("guardrail"),
                    )

                    tool_actions.append({
                        "tool": tool_name,
                        "args": args,
                        "result": result,
                        "audit_id": audit_entry.id,
                    })

                    if result.get("requires_confirmation"):
                        awaiting_confirmation = True

                    # Store tool call + result as messages
                    db.add(Message(
                        session_id=db_session.id,
                        role="tool_use",
                        content=json.dumps({"tool": tool_name, "args": args}),
                        tool_name=tool_name,
                        tool_call_id=tc.id,
                    ))
                    db.add(Message(
                        session_id=db_session.id,
                        role="tool_result",
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tc.id,
                    ))
                    db.commit()

                    # Add tool result to history for the model
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })

            elif message.content:
                # Model gave a final text response
                reply_text = message.content

                # Store assistant reply
                db.add(Message(session_id=db_session.id, role="assistant", content=reply_text))
                db.commit()

                # Get current cart
                cart = T.get_cart(db, db_session.id)

                return {
                    "reply": reply_text,
                    "tool_actions": tool_actions,
                    "cart": cart.get("items", []),
                    "awaiting_confirmation": awaiting_confirmation,
                }

            else:
                # No tool_calls and no content — shouldn't happen, but break
                logger.warning("Model returned empty response")
                break

        # Safety: if we exhausted tool rounds, return what we have
        return {
            "reply": "I'm having trouble finishing that request. Could you try rephrasing?",
            "tool_actions": tool_actions,
            "cart": T.get_cart(db, db_session.id).get("items", []),
            "awaiting_confirmation": awaiting_confirmation,
        }

    def _execute_tool(self, db: DBSession, session_db_id: int, tool_name: str, args: dict) -> dict:
        """Dispatch a tool call to the appropriate function."""
        try:
            if tool_name == "search_catalog":
                return T.search_catalog(db, session_db_id, **args)
            elif tool_name == "view_catalog":
                return T.view_catalog(db, session_db_id)
            elif tool_name == "add_to_cart":
                return T.add_to_cart(db, session_db_id, **args)
            elif tool_name == "remove_from_cart":
                return T.remove_from_cart(db, session_db_id, **args)
            elif tool_name == "get_cart":
                return T.get_cart(db, session_db_id)
            elif tool_name == "apply_coupon":
                return T.apply_coupon(db, session_db_id, **args)
            elif tool_name == "create_razorpay_order":
                return T.create_razorpay_order(db, session_db_id)
            elif tool_name == "confirm_order":
                return T.confirm_order(db, session_db_id)
            elif tool_name == "initiate_payment":
                return T.initiate_payment(db, session_db_id, **args)
            elif tool_name == "get_recommendations":
                return T.get_recommendations(db, session_db_id)
            else:
                return {"error": f"Unknown tool: {tool_name}", "blocked": True}
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return {"error": f"Tool execution failed: {exc}", "blocked": True}

    def _load_history(self, db: DBSession, session_db_id: int, limit: int = 40) -> list[dict]:
        """Load recent conversation history in OpenAI message format."""
        messages = (
            db.query(Message)
            .filter(Message.session_id == session_db_id)
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        messages.reverse()

        history = []
        for msg in messages:
            if msg.role == "user":
                history.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                history.append({"role": "assistant", "content": msg.content})
            # Skip tool_use/tool_result stored messages — model rebuilds from context

        return history
