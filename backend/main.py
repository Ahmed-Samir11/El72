"""
FastAPI application — tool endpoints called by the ElevenLabs Agent,
plus WebSocket for real-time frontend updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.models.product import Product
from backend.models.session import get_or_create_session, get_session
from backend.modules.cart.manager import CartManager
from backend.modules.checkout.simulator import CheckoutSimulator
from backend.modules.crawler.manager import CrawlManager
from backend.modules.ranking.engine import RankingEngine

logger = logging.getLogger(__name__)

# ── Global singletons ───────────────────────────────────────────────
crawl_manager: CrawlManager | None = None
ws_clients: dict[str, list[WebSocket]] = {}  # session_id -> connected sockets


@asynccontextmanager
async def lifespan(app: FastAPI):
    global crawl_manager
    crawl_manager = CrawlManager()
    yield
    await crawl_manager.close()


app = FastAPI(
    title="Agentic Commerce — Tool API",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
#  Helpers
# =====================================================================

async def _broadcast(session_id: str, event: str, data: dict):
    """Push a JSON event to all WebSocket clients for a session."""
    msg = json.dumps({"event": event, **data})
    for ws in ws_clients.get(session_id, []):
        try:
            await ws.send_text(msg)
        except Exception:
            pass


def _get_ranking_engine(session_id: str) -> RankingEngine:
    sess = get_or_create_session(session_id)
    return RankingEngine(cart_retailers=sess.cart.retailers)


# =====================================================================
#  WebSocket — real-time updates for the frontend
# =====================================================================

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    ws_clients.setdefault(session_id, []).append(websocket)
    try:
        while True:
            # Keep connection alive; client may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.get(session_id, []).remove(websocket)


# =====================================================================
#  /tools/search — search products across retailers
# =====================================================================

class SearchRequest(BaseModel):
    query: str
    category: str = ""
    session_id: str = ""
    stores: list[str] | None = None


class SearchResponse(BaseModel):
    session_id: str
    category: str
    products: list[dict]
    total_found: int


@app.post("/tools/search", response_model=SearchResponse)
async def tool_search(req: SearchRequest):
    sess = get_or_create_session(req.session_id or None)
    engine = _get_ranking_engine(sess.session_id)

    async def on_store_done(store: str, products: list[Product]):
        await _broadcast(
            sess.session_id,
            "products_found",
            {"store": store, "count": len(products), "category": req.category},
        )

    products = await crawl_manager.search(
        query=req.query,
        category=req.category,
        stores=req.stores,
        on_store_done=on_store_done,
    )

    # Rank
    ranked = engine.rank(products, sess.spec)
    sess.search_results[req.category or req.query] = ranked

    product_dicts = [p.model_dump() for p in ranked]

    await _broadcast(
        sess.session_id,
        "search_complete",
        {"category": req.category, "count": len(ranked)},
    )

    return SearchResponse(
        session_id=sess.session_id,
        category=req.category,
        products=product_dicts,
        total_found=len(ranked),
    )


# =====================================================================
#  /tools/cart/* — cart management
# =====================================================================

class AddToCartRequest(BaseModel):
    session_id: str
    product_id: str
    quantity: int = 1


@app.post("/tools/cart/add")
async def tool_cart_add(req: AddToCartRequest):
    sess = get_or_create_session(req.session_id)
    mgr = CartManager(sess.cart)

    product = mgr.find_product_in_results(req.product_id, sess.search_results)
    if not product:
        return {"error": f"Product {req.product_id} not found in search results"}

    mgr.add(product, req.quantity)
    summary = sess.cart.to_summary()
    await _broadcast(sess.session_id, "cart_updated", summary)
    return summary


class RemoveFromCartRequest(BaseModel):
    session_id: str
    product_id: str


@app.post("/tools/cart/remove")
async def tool_cart_remove(req: RemoveFromCartRequest):
    sess = get_or_create_session(req.session_id)
    mgr = CartManager(sess.cart)
    mgr.remove(req.product_id)
    summary = sess.cart.to_summary()
    await _broadcast(sess.session_id, "cart_updated", summary)
    return summary


@app.get("/tools/cart")
async def tool_cart_get(session_id: str = Query("")):
    sess = get_or_create_session(session_id or None)
    return sess.cart.to_summary()


# =====================================================================
#  /tools/ranking/explain — explain a product's rank
# =====================================================================

class ExplainRequest(BaseModel):
    session_id: str
    product_id: str


@app.post("/tools/ranking/explain")
async def tool_explain_ranking(req: ExplainRequest):
    sess = get_or_create_session(req.session_id)
    engine = _get_ranking_engine(sess.session_id)
    mgr = CartManager(sess.cart)
    product = mgr.find_product_in_results(req.product_id, sess.search_results)
    if not product:
        return {"error": "Product not found in search results"}
    explanation = engine.explain(product, sess.spec)
    return {"product_id": req.product_id, "explanation": explanation}


# =====================================================================
#  /tools/checkout — simulate multi-retailer checkout
# =====================================================================

@app.post("/tools/checkout")
async def tool_checkout(session_id: str = ""):
    sess = get_or_create_session(session_id or None)
    plan = CheckoutSimulator.simulate(sess.cart)
    await _broadcast(sess.session_id, "checkout_started", plan.model_dump())
    return plan.model_dump()


# =====================================================================
#  /session — get full session state (for frontend polling)
# =====================================================================

@app.get("/session/{session_id}")
async def get_session_state(session_id: str):
    sess = get_session(session_id)
    if not sess:
        return {"error": "Session not found"}
    return {
        "session_id": sess.session_id,
        "spec": sess.spec.model_dump(),
        "cart": sess.cart.to_summary(),
        "search_results": {
            cat: [p.model_dump() for p in prods]
            for cat, prods in sess.search_results.items()
        },
    }


# =====================================================================
#  /health
# =====================================================================

@app.get("/")
async def root():
    return {
        "name": "CartPilot — Agentic Commerce API",
        "version": "0.1.0",
        "endpoints": [
            "GET  /health",
            "POST /tools/search",
            "POST /tools/cart/add",
            "POST /tools/cart/remove",
            "GET  /tools/cart?session_id=",
            "POST /tools/ranking/explain",
            "POST /tools/checkout?session_id=",
            "GET  /session/{session_id}",
            "WS   /ws/{session_id}",
        ],
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# =====================================================================
#  Entrypoint
# =====================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
