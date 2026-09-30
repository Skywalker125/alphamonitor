"""Price charts for the top tokens of each feed, from Shrine's OHLCV data API.

The browser says which mints it wants (the first two rows of every feed). One keyed
Socket.IO connection to Shrine (it allows one candle socket per IP, and the key stays on
the server) refreshes each wanted mint with `ohlcv_history` every few seconds, and the
result is pushed to the browser as a compact close-price series over SSE.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import socketio

from .broadcaster import broadcaster

log = logging.getLogger("alphamonitor.charts")

WANT_TTL = 90  # a mint is dropped when no browser asked for it for this long
MAX_MINTS = 20
MAX_POINTS = 120  # points sent per chart
# ohlcv_history only holds the last ~2 minutes, so candles from every refresh are merged
# per token; keep this much history for the chart.
HISTORY_SECONDS = 30 * 60


def split_namespace(url: str) -> tuple[str, str]:
    """'https://shrine.trade/solana' -> ('https://shrine.trade', '/solana').

    In socket.io-client (JS) the URL path is the namespace; python-socketio would instead
    append /socket.io/ to it and hit a page that doesn't exist.
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/") or "/"


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


@dataclass(frozen=True)
class Endpoint:
    server: str
    namespace: str = "/"
    path: str = "socket.io"

    def label(self) -> str:
        return f"{self.server} namespace {self.namespace} path /{self.path.strip('/')}/"


# Where the data API's Socket.IO server may live. The example repo's
# io("https://shrine.trade/solana") answers 404 on /socket.io/, and Shrine's stream docs use
# io("https://sol.shrine.trade"), so try the plausible layouts and keep the first that works.
AUTO_ENDPOINTS = [
    Endpoint("https://sol.shrine.trade", "/"),
    Endpoint("https://shrine.trade", "/solana"),
    Endpoint("https://shrine.trade", "/", "solana/socket.io"),
    Endpoint("https://sol.shrine.trade", "/solana"),
]


def endpoints_for(url: str | None, socketio_path: str | None = None) -> list[Endpoint]:
    if not url or url.strip().lower() == "auto":
        return list(AUTO_ENDPOINTS)
    server, namespace = split_namespace(url.strip())
    return [Endpoint(server, namespace, (socketio_path or "socket.io").strip("/"))]


def describe_error(e: BaseException) -> str:
    """The exception plus whatever it hides: python-engineio raises a bare
    'Connection error' and keeps the real aiohttp/SSL/DNS error only as its context."""
    parts, seen, cur = [], set(), e
    while cur is not None and id(cur) not in seen and len(parts) < 4:
        seen.add(id(cur))
        text = str(cur) or type(cur).__name__
        if not parts or text not in parts[-1]:
            parts.append(text if cur is e else f"{type(cur).__name__}: {text}")
        cur = cur.__cause__ or cur.__context__
    out = " <- ".join(parts)
    if "namespaces failed to connect" in out:
        out += " (the server refused the handshake: check SHRINE_API_KEY)"
    return out


class ChartService:
    def __init__(self, url: str | None, api_key: str | None, refresh_seconds: float = 10,
                 socketio_path: str | None = None, endpoints: list[Endpoint] | None = None) -> None:
        self.endpoints = endpoints or endpoints_for(url, socketio_path)
        self.endpoint: Endpoint | None = None  # the one that worked
        self.attempts: list[str] = []
        self.api_key = api_key
        self.refresh_seconds = refresh_seconds
        self.wanted: dict[str, float] = {}
        self.cache: dict[str, dict[str, Any]] = {}
        # mint -> {second: candle}, merged across refreshes
        self.candles: dict[str, dict[int, list[float]]] = {}
        self.error: str | None = None if api_key else "SHRINE_API_KEY not set"
        self.sio = socketio.AsyncClient(reconnection=True, reconnection_delay=2, reconnection_delay_max=60)
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    @property
    def namespace(self) -> str:
        return self.endpoint.namespace if self.endpoint else "/"

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
            "endpoint": self.endpoint.label() if self.endpoint else None,
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
        self.attempts = []
        # the endpoint that worked before goes first
        order = sorted(self.endpoints, key=lambda ep: ep != self.endpoint)
        for ep in order:
            # direct WebSocket first (what Shrine's example uses), then the standard
            # polling -> WebSocket upgrade, which gets through where a direct upgrade is refused
            for transports in (["websocket"], ["polling", "websocket"]):
                try:
                    await self.sio.connect(
                        ep.server,
                        namespaces=[ep.namespace],
                        socketio_path=ep.path,
                        transports=transports,
                        auth={"api_key": self.api_key},
                        wait_timeout=15,
                    )
                    self.endpoint, self.error = ep, None
                    self.attempts.append(f"OK   {ep.label()} ({'+'.join(transports)})")
                    log.info("Connected to Shrine OHLCV at %s", ep.label())
                    return True
                except Exception as e:
                    err = describe_error(e)
                    self.attempts.append(f"FAIL {ep.label()} ({'+'.join(transports)}): {err}")
                    try:
                        await self.sio.disconnect()
                    except Exception:
                        pass
                    if "404" in err:
                        break  # nothing there; polling would 404 too
        # a wrong or disabled key is refused at the handshake
        self.error = "connect failed: " + " | ".join(a[5:] for a in self.attempts)
        log.warning("Shrine OHLCV %s", self.error)
        return False

    async def _run(self) -> None:
        backoff = 5.0
        while True:
            now = time.time()
            for m in [m for m, t in self.wanted.items() if now - t > WANT_TTL]:
                del self.wanted[m]
                self.cache.pop(m, None)
                self.candles.pop(m, None)
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
            ack = await self.sio.call(
                "ohlcv_history", {"mint": mint, "limit": 500}, namespace=self.namespace, timeout=15
            )
        except Exception as e:
            self.cache.setdefault(mint, {})["error"] = str(e) or type(e).__name__
            return
        if not isinstance(ack, dict) or not ack.get("ok"):
            err = (ack or {}).get("message") or (ack or {}).get("error") if isinstance(ack, dict) else "bad reply"
            self.cache[mint] = {"mint": mint, "points": [], "error": err, "updated_at": time.time()}
            if err in ("api_key_required", "invalid_api_key"):
                self.error = err
            return
        merged = self.candles.setdefault(mint, {})
        for c in ack.get("data") or ack.get("candles") or []:
            if isinstance(c, (list, tuple)) and len(c) >= 5:
                merged[int(c[0] // 1000)] = list(c)
        cutoff = max(merged, default=0) - HISTORY_SECONDS
        for sec in [s for s in merged if s < cutoff]:
            del merged[sec]
        points = to_points(list(merged.values()))
        entry = {"mint": mint, "pool": ack.get("pool"), "points": points, "updated_at": time.time()}
        previous = self.cache.get(mint, {}).get("points")
        self.cache[mint] = entry
        if points != previous:
            broadcaster.publish("chart", entry)
