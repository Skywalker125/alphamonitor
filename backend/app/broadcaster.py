import asyncio
from typing import Any


class Broadcaster:
    """Tiny in-process pub/sub used to fan out new scan messages to SSE clients."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, data: Any) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                # slow client: drop it, the browser's EventSource will reconnect
                self._subscribers.discard(q)


broadcaster = Broadcaster()
