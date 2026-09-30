import asyncio
import json
import time

import pytest

from app.broadcaster import broadcaster
from app.config import settings
from app.database import db
from app.shrine.prices import SOL, QuotePrices
from app.signals.engine import Trade, load_config
from app.signals.watcher import Watcher

from .test_signals import organic

MINT = "DtFkKBC3Cmi9j3SxBGRUd8gvBLw7nAasrvUJFB69yubM"
OTHER = "8KWEXgDLcH45SBjosFUpLe53fEntQQ8dWDDHVjqipump"
PARSED = {"symbol": "SI", "name": "Super Intelligence", "chain": "solana", "market_cap": 50_000,
          "top10_pct": 20.0, "bundled_pct": 10.0, "audit_score": 8, "dex_paid": True}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    db.init_sync()


def make_watcher(**kw):
    prices = QuotePrices()
    prices.sol_usd = 200.0
    return Watcher(load_config(), prices, **kw)


def trade_event(mint, side="buy", trader="w1", quote=0.5, price=1e-5):
    return {"action": side, "mint": mint, "pool": f"pool-{mint[:4]}", "quoteMint": SOL,
            "quoteAmount": quote, "price": price, "marketCapQuote": price * 1e9,
            "quoteInPool": 80.0, "tradersInvolved": [trader], "signature": "sig"}


def test_same_mint_from_many_feeds_is_watched_once():
    async def main():
        w = make_watcher()
        results = []
        for feed in ("discord", "hot", "smart"):
            for _ in range(5):
                results.append(await w.submit(MINT, [feed], PARSED))
        assert results.count("started") == 1
        assert list(w.states) == [MINT]
        assert w.states[MINT].sources == ["discord", "hot", "smart"]
        assert w.states[MINT].ctx.feeds == 3
        rows = db.recent_sessions(db.datetime.fromtimestamp(0, db.timezone.utc))
        assert len(rows) == 1 and rows[0]["sources"] == ["discord", "hot", "smart"]
    asyncio.run(main())


def test_concurrent_submits_create_one_session():
    async def main():
        w = make_watcher()
        await asyncio.gather(*(w.submit(MINT, [f], PARSED) for f in ("a", "b", "c", "a")))
        assert len(w.states) == 1 and sorted(w.states[MINT].sources) == ["a", "b", "c"]
        assert len(db.recent_sessions(db.datetime.fromtimestamp(0, db.timezone.utc))) == 1
    asyncio.run(main())


def test_only_watched_mints_are_routed():
    async def main():
        w = make_watcher()
        await w.submit(MINT, ["hot"], PARSED)
        for i in range(10):
            w.on_event(trade_event(MINT, trader=f"w{i}"))
            w.on_event(trade_event(OTHER, trader=f"x{i}"))
        w.on_event({"action": "create", "mint": MINT})
        assert w.matched == 10 and len(w.states[MINT].trades) == 10
        assert w.states[MINT].last_mc == pytest.approx(1e-5 * 1e9 * 200)
        await w.tick()
        conn = db.get_connection()
        assert conn.execute("select count(*) from watch_trades").fetchone()[0] == 10
        conn.close()
    asyncio.run(main())


def test_liquidity_remove_on_known_pool_flags_token():
    async def main():
        w = make_watcher()
        await w.submit(MINT, ["hot"], PARSED)
        w.on_event(trade_event(MINT))
        w.on_event({"action": "remove", "pool": f"pool-{MINT[:4]}"})
        assert w.states[MINT].ctx.liquidity_removed
    asyncio.run(main())


def test_skip_then_cooldown_and_queue():
    async def main():
        w = make_watcher(capacity=1, max_seconds=100)
        assert await w.submit(MINT, ["hot"], PARSED) == "started"
        assert await w.submit(OTHER, ["hot"], PARSED) == "queued"
        start = w.states[MINT].started_at
        await w.tick(now=start + 105)  # no trades -> SKIPPED at max time
        assert MINT not in w.states
        assert OTHER in w.states  # queued token took the free slot
        assert await w.submit(MINT, ["smart"], PARSED) == "cooldown"
        assert MINT in w.shadow
        row = db.session_history()[0]
        assert row["mint"] == MINT and row["status"] == "SKIPPED"
    asyncio.run(main())


def test_entry_is_tracked_then_released_with_outcome():
    async def main():
        events = broadcaster.subscribe()
        w = make_watcher(track_seconds=600)
        await w.submit(MINT, ["hot", "smart"], PARSED)
        state = w.states[MINT]
        t0 = state.started_at
        # replay a healthy order flow relative to the watch start
        for tr in organic(seconds=180):
            state.trades.append(Trade(**{**tr.__dict__, "t": tr.t - 1_000_000.0 + t0}))
        state.last_mc = 60_000
        decision_at = None
        for now in range(5, 185, 5):
            await w.tick(now=t0 + now)
            if state.status == "ENTRY":
                decision_at = now
                break
        assert decision_at is not None and decision_at >= 60
        assert state.entry_mc == 60_000 and MINT in w.states
        state.last_mc = 90_000
        await w.tick(now=state.decided_at + 301)
        assert state.mc_5m == 90_000
        await w.tick(now=state.decided_at + 601)
        assert MINT not in w.states
        row = db.session_history(status="ENTRY")[0]
        assert row["entry_mc"] == 60_000 and row["mc_10m"] == 90_000
        kinds = []
        while not events.empty():
            kinds.append(events.get_nowait()[1].get("status"))
        broadcaster.unsubscribe(events)
        assert "WATCHING" in kinds and "ENTRY" in kinds
    asyncio.run(main())


def test_dismiss_entry():
    async def main():
        w = make_watcher()
        await w.submit(MINT, ["hot"], PARSED)
        w.states[MINT].status = "ENTRY"
        w.states[MINT].decided_at = time.time()
        assert await w.dismiss(MINT)
        assert MINT not in w.states and MINT in w.shadow
        assert not await w.dismiss(OTHER)
    asyncio.run(main())


def test_non_solana_is_ignored():
    async def main():
        w = make_watcher()
        assert await w.submit("0x" + "a" * 40, ["hot"], {**PARSED, "chain": "evm"}) == "unsupported"
    asyncio.run(main())


def test_stale_queue_items_expire():
    async def main():
        w = make_watcher(capacity=1)
        await w.submit(MINT, ["hot"], PARSED)
        await w.submit(OTHER, ["hot"], PARSED)
        await w.tick(now=w.states[MINT].started_at + 200)  # queued item is now > 2 min old
        assert w.states == {} and not w.queue
    asyncio.run(main())
