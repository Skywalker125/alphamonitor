"""Entry-signal model: scores a token from its live trades plus TokenScan context.

Pure functions only (no I/O) so it can be unit-tested and replayed over stored trades.

The ingredients are standard order-flow / momentum measures - order-flow imbalance,
trade-intensity acceleration, participant growth, buyer concentration, trend quality -
combined into a transparent 0-100 score. There are no hard filters: every risk check
(holder concentration, dumps, liquidity pulls, whale exits) is a penalty that lowers the
score, and a thin trade history scales the score down instead of blocking it.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS_FILE = Path(__file__).resolve().parents[2] / "signals.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULTS_FILE
    return json.loads(p.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Trade:
    t: float  # unix seconds
    side: str  # "buy" | "sell"
    quote: float  # trade size in the quote asset (mostly SOL)
    price: float  # token price in the quote asset, post-trade
    traders: tuple[str, ...] = ()
    # per-trader quote amounts when the event carries a breakdown, else split evenly
    trader_amounts: tuple[tuple[str, float], ...] = ()
    quote_in_pool: float | None = None
    mc_quote: float | None = None
    pool: str | None = None


@dataclass
class Context:
    """What TokenScan (and the watcher) knows about the token besides its trades."""

    top10_pct: float | None = None
    bundled_pct: float | None = None
    sniped_pct: float | None = None
    dex_paid: bool | None = None
    audit_score: int | None = None
    feeds: int = 1
    liquidity_removed: bool = False


@dataclass
class Evaluation:
    score: float
    raw_score: float
    confidence: float
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    penalties: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def reasons(self) -> list[str]:
        """Human readable, strongest positives first, then every penalty."""
        pos = sorted(
            (c for c in self.components.values() if c["points"] > 0),
            key=lambda c: c["points"] / c["max"],
            reverse=True,
        )
        neg = sorted(self.penalties.values(), key=lambda p: p["points"])
        return [c["label"] for c in pos] + [p["label"] for p in neg]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "raw_score": round(self.raw_score, 1),
            "confidence": round(self.confidence, 2),
            "components": self.components,
            "penalties": self.penalties,
            "stats": self.stats,
            "reasons": self.reasons,
        }


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _ramp(value: float | None, frm: float, to: float) -> float:
    """0 at `frm`, 1 at `to` (works for descending ranges too)."""
    if value is None or to == frm:
        return 0.0
    return _clamp01((value - frm) / (to - frm))


def _buyer_amounts(trades: list[Trade]) -> dict[str, float]:
    amounts: dict[str, float] = {}
    for tr in trades:
        if tr.side != "buy":
            continue
        if tr.trader_amounts:
            pairs = tr.trader_amounts
        elif tr.traders:
            share = tr.quote / len(tr.traders)
            pairs = tuple((w, share) for w in tr.traders)
        else:
            pairs = (("?", tr.quote),)
        for w, q in pairs:
            amounts[w] = amounts.get(w, 0.0) + q
    return amounts


def evaluate(
    trades: list[Trade],
    ctx: Context,
    started_at: float,
    now: float,
    cfg: dict[str, Any],
) -> Evaluation:
    w = cfg["weights"]
    comps: dict[str, dict[str, Any]] = {}
    pens: dict[str, dict[str, Any]] = {}

    def comp(name: str, frac: float, label: str, **extra: Any) -> None:
        pts = round(w[name] * _clamp01(frac), 2)
        comps[name] = {"points": pts, "max": w[name], "label": label, **extra}

    def pen(name: str, points: float, label: str, **extra: Any) -> None:
        if points > 0:
            pens[name] = {"points": -round(points, 2), "label": label, **extra}

    watch = [t for t in trades if t.t >= started_at]
    last60 = [t for t in watch if t.t > now - 60]
    last30 = [t for t in last60 if t.t > now - 30]
    prev30 = [t for t in last60 if t.t <= now - 30]

    # 1. order-flow imbalance (quote-denominated, so SOL price doesn't matter)
    buy_q = sum(t.quote for t in last60 if t.side == "buy")
    sell_q = sum(t.quote for t in last60 if t.side == "sell")
    ofi = (buy_q - sell_q) / (buy_q + sell_q) if buy_q + sell_q > 0 else 0.0
    comp("order_flow", ofi / cfg["ofi_full"], f"Buy flow {ofi:+.0%}", value=round(ofi, 3))

    # 2. trade-intensity acceleration: trade rate in the last 30s vs the observed time before
    #    it (clipped to the watch start - earlier trades were never seen, not absent)
    n30, p30 = len(last30), len(prev30)
    prev_dur = (now - 30) - max(started_at, now - 60)
    if prev_dur < 10:
        accel, label = 1.0, "Trades: too early"
    else:
        rate_prev = p30 / prev_dur
        accel = (n30 / 30) / rate_prev if rate_prev else (cfg["accel_full"] if n30 else 0.0)
        label = f"Trades {min(accel, 9.9):.1f}x" + ("+" if accel > 9.9 else "")
    comp(
        "acceleration",
        (accel - 1.0) / (cfg["accel_full"] - 1.0),
        label,
        value=round(accel, 2),
    )

    # 3. participation: unique buyers in the last 60s + buyers never seen before in the watch
    buyers60 = set(_buyer_amounts(last60))
    seen_before = set(_buyer_amounts([t for t in watch if t.t <= now - 30]))
    new_buyers = set(_buyer_amounts(last30)) - seen_before
    frac = 0.67 * (len(buyers60) / cfg["unique_buyers_full"]) + 0.33 * (
        len(new_buyers) / cfg["new_buyers_full"]
    )
    comp(
        "participation",
        frac,
        f"{len(buyers60)} buyers ({len(new_buyers)} new)",
        buyers=len(buyers60),
        new_buyers=len(new_buyers),
    )

    # 4. buyer dispersion: how much of the buy volume the single biggest wallet did
    amounts = _buyer_amounts(last60)
    total = sum(amounts.values())
    top_share = max(amounts.values()) / total if total > 0 else 1.0
    comp(
        "dispersion",
        _ramp(top_share, cfg["top_buyer_share_zero"], cfg["top_buyer_share_full"]) if total else 0,
        f"Top buyer {top_share:.0%}",
        value=round(top_share, 3),
    )

    # 5. trend quality
    ret = drawdown = 0.0
    trend_frac = 0.0
    if watch:
        first, last = watch[0].price, watch[-1].price
        ret = last / first - 1 if first else 0.0
        high = max(t.price for t in watch)
        drawdown = 1 - last / high if high else 0.0
        lo, hi, chase = cfg["trend_return_low"], cfg["trend_return_high"], cfg["trend_return_chase"]
        if ret <= 0:
            ret_frac = 0.0
        elif ret < lo:
            ret_frac = ret / lo
        elif ret <= hi:
            ret_frac = 1.0
        else:  # fading credit for a move that's already vertical
            ret_frac = max(0.0, 1 - (ret - hi) / (chase - hi))
        mid = started_at + (now - started_at) / 2
        first_half = [t.price for t in watch if t.t <= mid]
        second_half = [t.price for t in watch if t.t > mid]
        higher_lows = bool(first_half and second_half and min(second_half) > min(first_half))
        vol = sum(t.quote for t in last60)
        vwap = sum(t.price * t.quote for t in last60) / vol if vol else last
        above_vwap = last >= vwap
        trend_frac = 0.5 * ret_frac + 0.25 * higher_lows + 0.25 * above_vwap
        label = f"Price {ret:+.0%}" + (", higher lows" if higher_lows else "")
    else:
        higher_lows = above_vwap = False
        label = "No trades yet"
    comp("trend", trend_frac, label, value=round(ret, 3))

    # 6. confluence / TokenScan context
    conf = 0.5 * _clamp01((ctx.feeds - 1) / 1) + 0.3 * ((ctx.audit_score or 0) >= 7) + 0.2 * bool(ctx.dex_paid)
    parts = [f"{ctx.feeds} feed{'s' if ctx.feeds != 1 else ''}"]
    if (ctx.audit_score or 0) >= 7:
        parts.append(f"audit {ctx.audit_score}")
    if ctx.dex_paid:
        parts.append("DEX paid")
    comp("confluence", conf, ", ".join(parts), feeds=ctx.feeds)

    # penalties (no hard filters - each only lowers the score)
    p = cfg["penalties"]

    def ramp_pen(key: str, value: float | None, label: str) -> None:
        spec = p[key]
        pen(key, spec["points"] * _ramp(value, spec["from"], spec["to"]), label)

    ramp_pen("top10_pct", ctx.top10_pct, f"Top 10 hold {ctx.top10_pct}%")
    ramp_pen("bundled_pct", ctx.bundled_pct, f"Bundled {ctx.bundled_pct}%")
    ramp_pen("sniped_pct", ctx.sniped_pct, f"Sniped {ctx.sniped_pct}%")
    ramp_pen("drawdown_pct", drawdown * 100, f"{drawdown:.0%} off the high")
    if watch and watch[0].mc_quote and watch[-1].mc_quote:
        drop = (1 - watch[-1].mc_quote / watch[0].mc_quote) * 100
        ramp_pen("mc_drop_pct", drop, f"MC {-drop:+.0f}% since watch start")
    whale = max(
        (t.quote / (t.quote_in_pool + t.quote) * 100 for t in watch if t.side == "sell" and t.quote_in_pool),
        default=0.0,
    )
    ramp_pen("whale_sell_pct", whale, f"Sell of {whale:.1f}% of the pool")
    if ctx.liquidity_removed:
        pen("liquidity_removed", p["liquidity_removed"], "Liquidity removed")

    raw = sum(c["points"] for c in comps.values()) + sum(x["points"] for x in pens.values())
    confidence = _clamp01(len(watch) / cfg["full_confidence_trades"])
    score = max(0.0, min(100.0, raw)) * confidence

    return Evaluation(
        score=score,
        raw_score=raw,
        confidence=confidence,
        components=comps,
        penalties=pens,
        stats={
            "trades": len(watch),
            "trades_60s": len(last60),
            "buy_quote_60s": round(buy_q, 4),
            "sell_quote_60s": round(sell_q, 4),
            "return": round(ret, 4),
            "drawdown": round(drawdown, 4),
            "higher_lows": higher_lows,
            "above_vwap": above_vwap,
        },
    )


@dataclass
class Decider:
    """Turns successive evaluations into ENTRY / SKIPPED, needing N consecutive passes."""

    cfg: dict[str, Any]
    min_seconds: float
    max_seconds: float
    streak: int = 0
    best: float = 0.0

    def step(self, ev: Evaluation, elapsed: float) -> str | None:
        self.best = max(self.best, ev.score)
        if elapsed < self.min_seconds:
            return None
        if ev.score >= self.cfg["entry_score"]:
            self.streak += 1
            if self.streak >= self.cfg["consecutive_passes"]:
                return "ENTRY"
        else:
            self.streak = 0
        if elapsed >= self.max_seconds:
            return "SKIPPED"
        return None
