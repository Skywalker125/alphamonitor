"""Shrine's free, keyless Socket.IO firehose (https://sol.shrine.trade, event `stream`).

One connection, one `subscribe_stream`. Nothing is subscribed per token: every event goes to
`on_event`, and the watcher drops anything whose mint it isn't watching with a set lookup.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable

import socketio

log = logging.getLogger("alphamonitor.shrine")

PROTOCOLS = [
    "PUMPFUN", "PUMPFUN_MAYHEM", "PUMPSWAP", "BONK", "STONKFUN",
    "RAYDIUM", "RAYDIUM_CLMM", "METEORA", "METEORA_DBC", "METEORA_DLMM", "ORCA",
]
ACTIONS = ["buy", "sell", "migrate", "add", "remove"]


class ShrineClient:
    def __init__(self, url: str, on_event: Callable[[dict[str, Any]], None]) -> None:
        self.url = url
        self.on_event = on_event
        self.sio = socketio.AsyncClient(
            reconnection=True, reconnection_delay=1, reconnection_delay_max=30, logger=False
        )
        self.connected = False
        self.subscribe_count = 0
        self.events = 0
        self.last_event_at: float | None = None
        self.last_error: str | None = None
        self._recent: deque[float] = deque(maxlen=5000)
        self._task: asyncio.Task | None = None

        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("stream", self._on_stream)

    async def _on_connect(self) -> None:
        self.connected, self.last_error = True, None
        # subscriptions are per socket, so (re)subscribe on every (re)connect
        await self.sio.emit("subscribe_stream", {"protocols": PROTOCOLS, "actions": ACTIONS})
        self.subscribe_count += 1
        log.info("Shrine stream connected and subscribed")

    async def _on_disconnect(self, *args: Any) -> None:
        self.connected = False
        log.warning("Shrine stream disconnected")

    async def _on_stream(self, data: Any) -> None:
        batch = data if isinstance(data, list) else [data]
        now = time.time()
        for e in batch:
            if not isinstance(e, dict):
                continue
            self.events += 1
            self.last_event_at = now
            self._recent.append(now)
            try:
                self.on_event(e)
            except Exception:
                log.exception("stream event handler failed")

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        delay = 1.0
        while True:
            try:
                await self.sio.connect(self.url, transports=["websocket"], wait_timeout=15)
                delay = 1.0
                await self.sio.wait()  # returns only if reconnection gives up
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = str(e) or type(e).__name__
                log.warning("Shrine connect failed (%s), retrying in %.0fs", self.last_error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def stop(self) -> None:
        # disconnect first: cancelling the task mid-read makes disconnect() raise
        try:
            await self.sio.disconnect()
        except (Exception, asyncio.CancelledError):
            pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (Exception, asyncio.CancelledError):
                pass

    def status(self) -> dict[str, Any]:
        now = time.time()
        rate = sum(1 for t in self._recent if t > now - 10) / 10
        return {
            "connected": self.connected,
            "url": self.url,
            "events": self.events,
            "events_per_s": round(rate, 1),
            "last_event_at": self.last_event_at,
            "error": self.last_error,
        }
