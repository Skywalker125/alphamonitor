"""Price charts for the top tokens of each feed, from Shrine's OHLCV data API.

The browser says which mints it wants (the first two rows of every feed). One keyed
Socket.IO connection to Shrine (it allows one candle socket per IP, and the key stays on
the server) refreshes each wanted mint with `ohlcv_history` every few seconds, and the
result is pushed to the browser as a compact close-price series over SSE.
"""

import asyncio
import logging
import time
from typing import Any

import socketio

from .broadcaster import broadcaster

log = logging.getLogger("alphamonitor.charts")

WANT_TTL = 90  # a mint is dropped when no browser asked for it for this long
MAX_MINTS = 20
MAX_POINTS = 120  # points sent per chart


def to_points(candles: list[list[float]], max_points: int = MAX_POINTS) -> list[list[float]]:
    """[t_ms, o, h, l, c, v] candles -> at most `max_points` [t_sec, close] points, oldest first."""
    rows = sorted(
        (c for c in candles if isinstance(c, (list, tuple)) and len(c) >= 5 and c[4] is not None),
        key=lambda c: c[0],
    )
    if not rows:
        return []
    if len(rows) <= max_points:
        return [[int(r[0] // 1000), float(r[4])] for r in rows]
    # bucket by time so quiet and busy stretches keep their real proportions
    t0, t1 = rows[0][0], rows[-1][0]
    span = max(t1 - t0, 1)
    buckets: dict[int, list[float]] = {}
    for r in rows:
        b = min(int((r[0] - t0) / span * max_points), max_points - 1)
        buckets[b] = [int(r[0] // 1000), float(r[4])]  # last close in the bucket
    return [buckets[b] for b in sorted(buckets)]


class ChartService:
    def __init__(self, url: str, api_key: str | None, refresh_seconds: float = 10) -> None:
        self.url = url
        self.api_key = api_key
        self.refresh_seconds = refresh_seconds
        self.wanted: dict[str, float] = {}
        self.cache: dict[str, dict[str, Any]] = {}
        self.error: str | None = None if api_key else "SHRINE_API_KEY not set"
        self.sio = socketio.AsyncClient(reconnection=True, reconnection_delay=2, reconnection_delay_max=60)
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # --------------------------------------------------------------- API side
    def want(self, mints: list[str]) -> dict[str, Any]:
        now = time.time()
        for m in mints[:MAX_MINTS]:
            if m not in self.wanted:
                self._wake.set()  # fetch new charts right away
            self.wanted[m] = now
        return {m: self.cache[m] for m in mints if m in self.cache}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self.sio.connected,
            "tracking": len(self.wanted),
            "error": self.error,
        }

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self.enabled:
            self._task = asyncio.create_task(self._run())
        else:
            log.warning("Charts disabled: SHRINE_API_KEY not set")

    async def stop(self) -> None:
        try:
            await self.sio.disconnect()
        except (Exception, asyncio.CancelledError):
            pass
        if self._task:
            self._task.cancel()

    async def _connect(self) -> bool:
        if self.sio.connected:
            return True
        try:
            await self.sio.connect(
                self.url, transports=["websocket"], auth={"api_key": self.api_key}, wait_timeout=15
            )
            self.error = None
            log.info("Connected to Shrine OHLCV")
            return True
        except Exception as e:
            # a wrong or disabled key is refused at the handshake
            self.error = f"connect failed: {e or type(e).__name__}"
            log.warning("Shrine OHLCV %s", self.error)
            return False

    async def _run(self) -> None:
        backoff = 5.0
        while True:
            now = time.time()
            for m in [m for m, t in self.wanted.items() if now - t > WANT_TTL]:
                del self.wanted[m]
                self.cache.pop(m, None)
            if self.wanted:
                if await self._connect():
                    backoff = 5.0
                    for mint in list(self.wanted):
                        await self._refresh(mint)
                else:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                    continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.refresh_seconds)
            except asyncio.TimeoutError:
                pass

    async def _refresh(self, mint: str) -> None:
        try:
            ack = await self.sio.call("ohlcv_history", {"mint": mint, "limit": 500}, timeout=15)
        except Exception as e:
            self.cache.setdefault(mint, {})["error"] = str(e) or type(e).__name__
            return
        if not isinstance(ack, dict) or not ack.get("ok"):
            err = (ack or {}).get("message") or (ack or {}).get("error") if isinstance(ack, dict) else "bad reply"
            self.cache[mint] = {"mint": mint, "points": [], "error": err, "updated_at": time.time()}
            if err in ("api_key_required", "invalid_api_key"):
                self.error = err
            return
        points = to_points(ack.get("data") or ack.get("candles") or [])
        entry = {"mint": mint, "pool": ack.get("pool"), "points": points, "updated_at": time.time()}
        previous = self.cache.get(mint, {}).get("points")
        self.cache[mint] = entry
        if points != previous:
            broadcaster.publish("chart", entry)
