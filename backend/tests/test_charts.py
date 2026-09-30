import asyncio
import socket
import time

import socketio
from aiohttp import web

from app import charts as charts_mod
from app.broadcaster import broadcaster
from app.charts import ChartService, describe_error, split_namespace, to_points

NS = "/solana"


def test_url_path_is_the_namespace():
    assert split_namespace("https://shrine.trade/solana") == ("https://shrine.trade", "/solana")
    assert split_namespace("https://shrine.trade") == ("https://shrine.trade", "/")

SIO_KEY = web.AppKey("sio", socketio.AsyncServer)


def test_to_points_keeps_order_and_downsamples():
    candles = [[1_000_000 + i * 1000, 1, 2, 0.5, 1 + i, 10] for i in range(500)]
    pts = to_points(list(reversed(candles)), max_points=100)
    assert len(pts) <= 100
    assert pts[0][0] < pts[-1][0]  # oldest first
    assert pts[-1][1] == 500  # last close kept
    assert to_points([[1000, 1, 1, 1, 2, 0]]) == [[1, 2.0]]
    assert to_points([]) == [] and to_points([["bad"]]) == []


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def fake_shrine(port, calls, good_key="sk_test"):
    sio = socketio.AsyncServer(async_mode="aiohttp")
    app = web.Application()
    app[SIO_KEY] = sio
    sio.attach(app)

    @sio.on("connect", namespace=NS)
    async def connect(sid, environ, auth):
        if not auth or auth.get("api_key") != good_key:
            raise socketio.exceptions.ConnectionRefusedError("invalid_api_key")

    @sio.on("ohlcv_history", namespace=NS)
    async def history(sid, data):
        calls.append(data)
        if data["mint"] == "UNKNOWN":
            return {"ok": False, "error": "not_found"}
        now = int(time.time() * 1000)
        # like Shrine: only a rolling ~2 minute window, moving on every call
        n = len(calls)
        return {"ok": True, "pool": "pool-" + data["mint"],
                "data": [[now - (60 - i) * 1000 + n * 30_000, 1, 1, 1, 1 + i / 10, 5] for i in range(60)]}

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    return runner


async def wait_for(cond, timeout=10):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


def test_fetches_wanted_mints_and_pushes_charts(monkeypatch):
    async def main():
        port, calls = free_port(), []
        runner = await fake_shrine(port, calls)
        events = broadcaster.subscribe()
        svc = ChartService(f"http://127.0.0.1:{port}{NS}", "sk_test", refresh_seconds=0.3)
        await svc.start()
        assert svc.want(["MintA", "MintB", "MintA", "UNKNOWN"]) == {}
        assert await wait_for(lambda: "MintA" in svc.cache and "MintB" in svc.cache)
        assert svc.cache["MintA"]["pool"] == "pool-MintA"
        assert len(svc.cache["MintA"]["points"]) >= 60
        assert svc.cache["UNKNOWN"]["error"] == "not_found"
        assert {c["mint"] for c in calls} == {"MintA", "MintB", "UNKNOWN"}
        assert all(c["limit"] == 500 for c in calls)
        # the 2-minute windows of successive refreshes are merged into a longer history
        assert await wait_for(lambda: len(svc.candles["MintA"]) > 60)
        # the same address asked for again (another feed, another tab) is fetched once per round
        per_round = len(calls)
        svc.want(["MintA", "MintA", "MintB"])
        await asyncio.sleep(0.45)
        new = calls[per_round:]
        rounds = max(1, new.count({"mint": "UNKNOWN", "limit": 500}))
        assert new.count({"mint": "MintA", "limit": 500}) == rounds
        # second want returns the cached charts straight away
        assert set(svc.want(["MintA"])) == {"MintA"}
        pushed = []
        while not events.empty():
            name, data = events.get_nowait()
            if name == "chart":
                pushed.append(data["mint"])
        assert {"MintA", "MintB"} <= set(pushed)
        # mints nobody asks for any more are dropped
        monkeypatch.setattr(charts_mod, "WANT_TTL", 0)
        await asyncio.sleep(0.5)
        assert svc.wanted == {} and svc.cache == {}
        broadcaster.unsubscribe(events)
        await svc.stop()
        await runner.cleanup()

    asyncio.run(main())


def test_bad_key_is_reported():
    async def main():
        port, calls = free_port(), []
        runner = await fake_shrine(port, calls)
        svc = ChartService(f"http://127.0.0.1:{port}{NS}", "sk_wrong", refresh_seconds=0.3)
        await svc.start()
        svc.want(["MintA"])
        assert await wait_for(lambda: svc.error and "connect failed" in svc.error)
        assert calls == [] and not svc.status()["connected"]
        await svc.stop()
        await runner.cleanup()

    asyncio.run(main())


def test_disabled_without_key():
    svc = ChartService("http://x", None)
    assert not svc.enabled and svc.status()["error"] == "SHRINE_API_KEY not set"


def test_describe_error_shows_the_hidden_cause():
    try:
        try:
            raise OSError("certificate verify failed: unable to get local issuer certificate")
        except OSError:
            raise ConnectionError("Connection error")  # what python-engineio does
    except ConnectionError as e:
        text = describe_error(e)
    assert text.startswith("Connection error <- OSError: certificate verify failed")
