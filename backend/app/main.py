import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import db
from .broadcaster import broadcaster
from .config import settings
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

listener = TelegramListener(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init(settings.database_url)
    app.state.http = httpx.AsyncClient(timeout=10)
    await listener.start()
    try:
        yield
    finally:
        await listener.stop()
        await app.state.http.aclose()
        await db.close()


app = FastAPI(title="AlphaMonitor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/status")
async def status():
    return {"telegram": listener.status}


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
