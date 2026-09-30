"""The client against a real (local) Socket.IO server speaking Shrine's protocol."""

import asyncio
import socket

import socketio
from aiohttp import web

from app.shrine.client import ACTIONS, ShrineClient


SIO_KEY = web.AppKey("sio", socketio.AsyncServer)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_server(port, subscribes):
    sio = socketio.AsyncServer(async_mode="aiohttp")
    app = web.Application()
    sio.attach(app)

    @sio.on("subscribe_stream")
    async def sub(sid, data):
        subscribes.append(data)
        await sio.emit("stream", {"action": "buy", "mint": "WATCHED", "quoteAmount": 1}, to=sid)
        await sio.emit("stream", {"action": "buy", "mint": "OTHER", "quoteAmount": 1}, to=sid)
        await sio.emit("stream", [{"action": "sell", "mint": "WATCHED"}], to=sid)  # batched form

    app[SIO_KEY] = sio
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


async def wait_for(cond, timeout=10):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


def test_subscribes_once_routes_events_and_resubscribes_after_restart():
    async def main():
        port = free_port()
        subscribes, got = [], []
        runner = await start_server(port, subscribes)
        client = ShrineClient(f"http://127.0.0.1:{port}", got.append)
        await client.start()
        assert await wait_for(lambda: len(got) == 3)
        assert len(subscribes) == 1 and subscribes[0]["actions"] == ACTIONS
        assert [e["mint"] for e in got] == ["WATCHED", "OTHER", "WATCHED"]
        assert client.status()["connected"]

        sio = runner.app[SIO_KEY]
        for sid in list(sio.manager.get_participants("/", None)):
            await sio.disconnect(sid[0] if isinstance(sid, tuple) else sid)
        await runner.cleanup()  # server goes away...
        assert await wait_for(lambda: not client.connected)
        runner = await start_server(port, subscribes)  # ...and comes back
        assert await wait_for(lambda: len(subscribes) == 2, timeout=20)
        assert await wait_for(lambda: len(got) == 6)
        await client.stop()
        await runner.cleanup()

    asyncio.run(main())
