"""Watches every new TokenScan token on the Shrine stream and decides ENTRY / SKIPPED.

Dedup: one TokenState per mint, however many feeds or messages mention it. The Shrine
socket subscribes once; `on_event` drops everything whose mint isn't in `self.states`.
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..broadcaster import broadcaster
from ..database import db
from ..shrine.prices import QuotePrices
from .engine import Context, Decider, Evaluation, Trade, evaluate

log = logging.getLogger("alphamonitor.signals")

TICK_SECONDS = 5
QUEUE_MAX_AGE = 120
COOLDOWN_SECONDS = 30 * 60
OUTCOME_SECONDS = 10 * 60
MC_TICK_SECONDS = 1.0


def _iso(t: float | None) -> str | None:
    return db.ts(datetime.fromtimestamp(t, timezone.utc)) if t else None


@dataclass
class TokenState:
    session_id: int
    mint: str
    symbol: str | None
    name: str | None
    started_at: float
    sources: list[str]
    ctx: Context
    decider: Decider
    status: str = "WATCHING"
    trades: list[Trade] = field(default_factory=list)
    pending_rows: list[tuple] = field(default_factory=list)
    quote_mint: str | None = None
    last_price: float | None = None
    last_mc_quote: float | None = None
    start_mc: float | None = None
    last_mc: float | None = None
    peak_mc: float | None = None
    entry_mc: float | None = None
    entry_price: float | None = None
    decided_at: float | None = None
    tracking_until: float | None = None
    mc_5m: float | None = None
    last_eval: Evaluation | None = None
    last_mc_published: float = 0.0

    def payload(self, max_seconds: float) -> dict[str, Any]:
        ev = self.last_eval
        return {
            "id": self.session_id,
            "mint": self.mint,
            "symbol": self.symbol,
            "name": self.name,
            "status": self.status,
            "tracking": True,
            "started_at": _iso(self.started_at),
            "decided_at": _iso(self.decided_at),
            "tracking_until": _iso(self.tracking_until),
            "max_seconds": max_seconds,
            "score": round(ev.score, 1) if ev else None,
            "best_score": round(self.decider.best, 1),
            "reasons": ev.reasons if ev else [],
            "sources": self.sources,
            "trades": len(self.trades),
            "start_mc": self.start_mc,
            "entry_mc": self.entry_mc,
            "last_mc": self.last_mc,
            "peak_mc": self.peak_mc,
            "mc_5m": self.mc_5m,
            "dismissed_at": None,
        }


class Watcher:
    def __init__(self, cfg: dict[str, Any], prices: QuotePrices, *, capacity: int = 100,
                 min_seconds: float = 60, max_seconds: float = 180,
                 track_seconds: float = 600) -> None:
        self.cfg = cfg
        self.prices = prices
        self.capacity = capacity
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self.track_seconds = track_seconds
        self.states: dict[str, TokenState] = {}
        # skipped tokens: only their MC is followed, to record the 10-minute outcome
        self.shadow: dict[str, dict[str, Any]] = {}
        self.cooldown: dict[str, float] = {}
        self.queue: deque[tuple[float, str, list[str], dict[str, Any]]] = deque()
        self.pool_mint: dict[str, str] = {}
        # mints whose session row is being created, with the feeds that asked meanwhile
        self._starting: dict[str, list[str]] = {}
        self.matched = 0
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------ intake
    async def submit(self, mint: str, feed_keys: list[str], parsed: dict[str, Any]) -> str:
        """A new TokenScan scan mentioned `mint`. Returns what happened (for logs/tests)."""
        if not mint or parsed.get("chain") not in (None, "solana"):
            return "unsupported"
        state = self.states.get(mint)
        if state:
            added = [k for k in feed_keys if k not in state.sources]
            if added:
                state.sources.extend(added)
                state.ctx.feeds = len(state.sources)
                await asyncio.to_thread(db.update_session, state.session_id, {"sources": state.sources})
                self._publish(state)
            return "merged"
        if mint in self._starting:
            self._starting[mint].extend(k for k in feed_keys if k not in self._starting[mint])
            return "merged"
        if time.time() - self.cooldown.get(mint, 0) < COOLDOWN_SECONDS:
            return "cooldown"
        if any(q[1] == mint for q in self.queue):
            return "queued"
        if len(self.states) >= self.capacity:
            self.queue.append((time.time(), mint, list(feed_keys), parsed))
            return "queued"
        await self._start(mint, list(feed_keys), parsed)
        return "started"

    async def _start(self, mint: str, feed_keys: list[str], parsed: dict[str, Any]) -> None:
        now = time.time()
        ctx = Context(
            top10_pct=parsed.get("top10_pct"),
            bundled_pct=parsed.get("bundled_pct"),
            sniped_pct=parsed.get("sniped_pct"),
            dex_paid=parsed.get("dex_paid"),
            audit_score=parsed.get("audit_score"),
            feeds=len(set(feed_keys)),
        )
        start_mc = parsed.get("market_cap")
        self._starting[mint] = feed_keys
        try:
            session_id = await asyncio.to_thread(db.insert_session, {
                "mint": mint, "symbol": parsed.get("symbol"), "name": parsed.get("name"),
                "status": "WATCHING", "started_at": datetime.fromtimestamp(now, timezone.utc),
                "sources": feed_keys, "context": ctx.__dict__, "start_mc": start_mc,
            })
        finally:
            feed_keys = self._starting.pop(mint, feed_keys)
        ctx.feeds = len(feed_keys)
        state = TokenState(
            session_id=session_id, mint=mint, symbol=parsed.get("symbol"), name=parsed.get("name"),
            started_at=now, sources=feed_keys, ctx=ctx,
            decider=Decider(self.cfg, self.min_seconds, self.max_seconds),
            start_mc=start_mc, last_mc=start_mc,
        )
        self.states[mint] = state
        self.shadow.pop(mint, None)
        log.info("Watching %s (%s) from %s", state.symbol, mint, feed_keys)
        self._publish(state)

    # ------------------------------------------------------------------ stream
    def on_event(self, e: dict[str, Any]) -> None:
        action = e.get("action")
        if action in ("buy", "sell"):
            mint = e.get("mint")
            state = self.states.get(mint)
            if state is not None:
                self.matched += 1
                self._add_trade(state, e, action)
            elif mint in self.shadow:
                mcq, usd = e.get("marketCapQuote"), self.prices.usd(e.get("quoteMint"))
                if mcq and usd:
                    self.shadow[mint]["last_mc"] = float(mcq) * usd
        elif action == "remove":
            mint = self.pool_mint.get(e.get("pool"))
            if mint in self.states:
                self.states[mint].ctx.liquidity_removed = True
        elif action == "migrate":
            mint = e.get("mint") or self.pool_mint.get(e.get("fromPool"))
            if mint in self.states and e.get("toPool"):
                self.pool_mint[e["toPool"]] = mint

    def _add_trade(self, state: TokenState, e: dict[str, Any], side: str) -> None:
        now = time.time()
        price = float(e.get("price") or 0) or state.last_price or 0.0
        quote = float(e.get("quoteAmount") or 0)
        traders = tuple(e.get("tradersInvolved") or ([e["txSigner"]] if e.get("txSigner") else []))
        amounts = tuple(
            (b["trader"], float(b.get("quoteAmount") or 0))
            for b in (e.get("breakdown") or [])
            if b.get("trader") and b.get("action", side) == side
        )
        qip = e.get("quoteInPool")
        mcq = e.get("marketCapQuote")
        pool = e.get("pool")
        trade = Trade(
            t=now, side=side, quote=quote, price=price, traders=traders, trader_amounts=amounts,
            quote_in_pool=float(qip) if qip is not None else None,
            mc_quote=float(mcq) if mcq is not None else None, pool=pool,
        )
        state.trades.append(trade)
        if pool:
            self.pool_mint[pool] = state.mint
        state.quote_mint = e.get("quoteMint") or state.quote_mint
        state.last_price = price or state.last_price
        if trade.mc_quote:
            state.last_mc_quote = trade.mc_quote
            usd = self.prices.usd(state.quote_mint)
            if usd:
                state.last_mc = trade.mc_quote * usd
                state.peak_mc = max(state.peak_mc or 0, state.last_mc)
        state.pending_rows.append((
            state.session_id, now, side, quote, price, trade.mc_quote, trade.quote_in_pool,
            json.dumps(list(traders)), pool, e.get("signature"),
        ))
        # live market cap for entry cards, at most once per second per token
        if state.status == "ENTRY" and state.last_mc and now - state.last_mc_published >= MC_TICK_SECONDS:
            state.last_mc_published = now
            broadcaster.publish("mc", {"mint": state.mint, "mc": state.last_mc, "t": now})

    # ------------------------------------------------------------------ loop
    async def start(self) -> None:
        closed = await asyncio.to_thread(db.close_stale_watching)
        if closed:
            log.info("Closed %d sessions left WATCHING by a previous run", closed)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("signal tick failed")
            await asyncio.sleep(TICK_SECONDS)

    async def tick(self, now: float | None = None) -> None:
        now = now or time.time()
        for state in list(self.states.values()):
            rows, state.pending_rows = state.pending_rows, []
            await asyncio.to_thread(db.insert_trades, rows)
            if state.status == "WATCHING":
                await self._evaluate(state, now)
            else:
                await self._track(state, now)

        for mint, sh in list(self.shadow.items()):
            if now >= sh["until"]:
                del self.shadow[mint]
                await asyncio.to_thread(db.update_session, sh["session_id"], {"mc_10m": sh.get("last_mc")})

        while self.queue and len(self.states) < self.capacity:
            queued_at, mint, feeds, parsed = self.queue.popleft()
            if now - queued_at <= QUEUE_MAX_AGE and mint not in self.states and mint not in self._starting:
                await self._start(mint, feeds, parsed)

    async def _evaluate(self, state: TokenState, now: float) -> None:
        ev = evaluate(state.trades, state.ctx, state.started_at, now, self.cfg)
        state.last_eval = ev
        decision = state.decider.step(ev, now - state.started_at)
        fields: dict[str, Any] = {
            "score": ev.score, "best_score": state.decider.best, "evaluation": ev.to_dict(),
            "reasons": ev.reasons, "trades": len(state.trades), "last_mc": state.last_mc,
            "peak_mc": state.peak_mc,
        }
        if decision == "ENTRY":
            state.status, state.decided_at = "ENTRY", now
            state.entry_mc, state.entry_price = state.last_mc, state.last_price
            state.tracking_until = now + self.track_seconds
            fields.update(status="ENTRY", decided_at=datetime.fromtimestamp(now, timezone.utc),
                          entry_mc=state.entry_mc, entry_price=state.entry_price,
                          tracking_until=datetime.fromtimestamp(state.tracking_until, timezone.utc))
            log.info("ENTRY %s score %.0f: %s", state.symbol, ev.score, ", ".join(ev.reasons[:4]))
        elif decision == "SKIPPED":
            state.status, state.decided_at = "SKIPPED", now
            fields.update(status="SKIPPED", decided_at=datetime.fromtimestamp(now, timezone.utc))
            del self.states[state.mint]
            self.cooldown[state.mint] = now
            self.shadow[state.mint] = {"session_id": state.session_id, "until": now + OUTCOME_SECONDS,
                                       "last_mc": state.last_mc}
        await asyncio.to_thread(db.update_session, state.session_id, fields)
        payload = state.payload(self.max_seconds)
        payload["tracking"] = state.status != "SKIPPED"
        broadcaster.publish("watch", payload)

    async def _track(self, state: TokenState, now: float) -> None:
        fields: dict[str, Any] = {"last_mc": state.last_mc, "peak_mc": state.peak_mc,
                                  "trades": len(state.trades)}
        if state.mc_5m is None and now - (state.decided_at or now) >= 300:
            state.mc_5m = fields["mc_5m"] = state.last_mc
        done = now >= (state.tracking_until or now)
        if done:
            fields["mc_10m"] = state.last_mc
            del self.states[state.mint]
            self.cooldown[state.mint] = state.decided_at or now
        await asyncio.to_thread(db.update_session, state.session_id, fields)
        payload = state.payload(self.max_seconds)
        payload["tracking"] = not done
        broadcaster.publish("watch", payload)

    async def dismiss(self, mint: str) -> bool:
        """Hide an ENTRY card. Its 10-minute outcome is still recorded in the background."""
        now = time.time()
        state = self.states.get(mint)
        if state and state.status == "ENTRY":
            del self.states[mint]
            self.cooldown[mint] = state.decided_at or now
            self.shadow[mint] = {"session_id": state.session_id,
                                 "until": state.tracking_until or now, "last_mc": state.last_mc}
            session_id = state.session_id
        else:
            since = datetime.fromtimestamp(now - 86400, timezone.utc)
            rows = await asyncio.to_thread(db.recent_sessions, since)
            match = [r for r in rows if r["mint"] == mint and r["status"] == "ENTRY"]
            if not match:
                return False
            session_id = match[0]["id"]
        await asyncio.to_thread(db.update_session, session_id, {"dismissed_at": datetime.now(timezone.utc)})
        broadcaster.publish("watch", {"mint": mint, "id": session_id, "dismissed": True})
        return True

    def _publish(self, state: TokenState) -> None:
        broadcaster.publish("watch", state.payload(self.max_seconds))

    def status(self) -> dict[str, Any]:
        return {
            "watching": sum(1 for s in self.states.values() if s.status == "WATCHING"),
            "tracking_entries": sum(1 for s in self.states.values() if s.status == "ENTRY"),
            "queued": len(self.queue),
            "capacity": self.capacity,
            "matched_events": self.matched,
            "sol_usd": self.prices.sol_usd,
            "sol_usd_source": self.prices.source,
        }
