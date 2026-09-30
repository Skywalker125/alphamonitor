import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .database import db
from .broadcaster import broadcaster
from .config import settings
from .shrine.client import ShrineClient
from .shrine.prices import QuotePrices
from .signals.engine import load_config
from .signals.watcher import Watcher
from .telegram_listener import TelegramListener

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("alphamonitor")

# Defaults for the upstream calls feed; any query param sent by the frontend overrides them.
CALLS_DEFAULTS = {
    "min_calls": "1",
    "interval": "1d",
    "sort": "recent",
    "chain": "solana",
    "calls_per_token": "0",
    "limit": "25",
    "offset": "0",
}

prices = QuotePrices()
watcher = (
    Watcher(
        load_config(settings.signals_file),
        prices,
        capacity=settings.watch_capacity,
        min_seconds=settings.watch_min_seconds,
        max_seconds=settings.watch_max_seconds,
        track_seconds=settings.entry_track_minutes * 60,
    )
    if settings.signals_enabled
    else None
)
shrine = ShrineClient(settings.shrine_url, watcher.on_event) if watcher else None
listener = TelegramListener(settings, watcher)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    app.state.http = httpx.AsyncClient(timeout=10)
    if watcher and shrine:
        await prices.start()
        await watcher.start()
        await shrine.start()
    await listener.start()
    try:
        yield
    finally:
        await listener.stop()
        if watcher and shrine:
            await shrine.stop()
            await watcher.stop()
            await prices.stop()
        await app.state.http.aclose()
        await db.close()


app = FastAPI(title="AlphaMonitor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/status")
async def status():
    return {
        "telegram": listener.status,
        "signals": (
            {"enabled": True, "stream": shrine.status(), **watcher.status()}
            if watcher and shrine
            else {"enabled": False}
        ),
    }


@app.get("/api/feeds")
async def feeds():
    """The five feeds shown in the UI: the upstream calls feed + the TokenScan feeds."""
    return [
        {
            "key": "telegram",
            "kind": "calls",
            "title": "Telegram",
            "description": "Latest calls from tracked Telegram channels.",
        }
    ] + [
        {
            "key": f.key,
            "kind": "scan",
            "title": f.title,
            "description": f.description,
            "chats": len(f.chats),
        }
        for f in settings.feeds
    ]


@app.get("/api/feeds/telegram")
async def telegram_calls(request: Request):
    params = {**CALLS_DEFAULTS, **dict(request.query_params)}
    try:
        r = await request.app.state.http.get(settings.calls_api_url, params=params)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Calls API unreachable: {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"Calls API error: {r.text[:300]}")
    return r.json()


@app.get("/api/feeds/{feed_key}/messages")
async def feed_messages(
    feed_key: str,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
):
    if feed_key not in {f.key for f in settings.feeds}:
        raise HTTPException(404, "Unknown feed")
    return {"items": await db.list_scans(feed_key, limit=limit, before=before)}


@app.get("/api/stream")
async def stream(request: Request):
    """Server-sent events: `scan` events carry {feed, item} for every new/edited scan."""
    q = broadcaster.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/signals")
async def signals(minutes: int = Query(60, ge=1, le=24 * 60)):
    """Watch sessions of the last `minutes` (plus any still watching), live state merged in."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = await asyncio.to_thread(db.recent_sessions, since)
    live = {s.mint: s for s in watcher.states.values()} if watcher else {}
    out = []
    for r in rows:
        state = live.get(r["mint"])
        if state and state.session_id == r["id"]:
            item = state.payload(watcher.max_seconds)
        else:
            item = {k: r.get(k) for k in (
                "id", "mint", "symbol", "name", "status", "started_at", "decided_at",
                "tracking_until", "score", "best_score", "reasons", "sources", "trades",
                "start_mc", "entry_mc", "last_mc", "peak_mc", "mc_5m", "mc_10m", "dismissed_at")}
            item["tracking"] = False
            item["max_seconds"] = watcher.max_seconds if watcher else None
        out.append(item)
    return {"enabled": bool(watcher), "sessions": out}


@app.post("/api/signals/{mint}/dismiss")
async def dismiss_signal(mint: str):
    if not watcher or not await watcher.dismiss(mint):
        raise HTTPException(404, "No entry signal for this token")
    return {"ok": True}


@app.get("/api/signals/history")
async def signal_history(limit: int = Query(200, ge=1, le=2000), status: str | None = None):
    """Decided sessions with their outcomes (mc at signal, +5m, +10m, peak) for tuning."""
    return {"items": await asyncio.to_thread(db.session_history, limit, status)}
