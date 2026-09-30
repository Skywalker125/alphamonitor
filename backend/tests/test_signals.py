import random

from app.signals.engine import Context, Decider, Trade, evaluate, load_config

CFG = load_config()
T0 = 1_000_000.0


def organic(seconds=120, rate=1.0, drift=0.004, seed=1, whale_share=0.0, start_price=1e-5):
    """Many different wallets buying steadily with a few small sells, price creeping up."""
    rnd = random.Random(seed)
    trades, price, n = [], start_price, 0
    t = T0
    while t < T0 + seconds:
        t += rnd.expovariate(rate * (1 + (t - T0) / seconds))  # accelerating
        n += 1
        side = "sell" if rnd.random() < 0.25 else "buy"
        q = rnd.uniform(0.2, 1.5)
        wallet = f"w{n}"
        if whale_share and side == "buy" and rnd.random() < whale_share:
            wallet, q = "whale", q * 6
        price *= 1 + (drift if side == "buy" else -drift / 2)
        trades.append(Trade(t, side, q, price, (wallet,), quote_in_pool=80.0, mc_quote=price * 1e9))
    return trades


def run(trades, ctx=None, max_s=180):
    ctx = ctx or Context(feeds=1)
    d = Decider(CFG, min_seconds=60, max_seconds=max_s)
    ev = None
    for now in range(int(T0) + 5, int(T0) + max_s + 1, 5):
        seen = [t for t in trades if t.t <= now]
        ev = evaluate(seen, ctx, T0, now, CFG)
        decision = d.step(ev, now - T0)
        if decision:
            return decision, now - T0, ev
    return None, max_s, ev


def test_organic_buying_enters():
    decision, at, ev = run(organic(seconds=180))
    assert decision == "ENTRY", ev.to_dict()
    assert 60 <= at <= 180
    assert ev.score >= CFG["entry_score"]


def test_needs_two_consecutive_passes():
    d = Decider(CFG, 60, 180)
    good = evaluate(organic(seconds=90), Context(), T0, T0 + 90, CFG)
    assert good.score >= 70
    assert d.step(good, 90) is None  # first pass only
    assert d.step(good, 95) == "ENTRY"


def test_single_wallet_pumping_is_not_an_entry():
    decision, _, ev = run(organic(seconds=180, whale_share=0.9))
    assert decision == "SKIPPED"
    assert ev.components["dispersion"]["points"] < 5


def test_dump_is_penalised_and_skipped():
    trades = organic(seconds=45)  # dump starts before a decision is allowed (60s)
    last = trades[-1]
    t, price = last.t, last.price
    for i in range(40):  # heavy selling
        t += 1.5
        price *= 0.985
        trades.append(Trade(t, "sell", 2.0, price, (f"s{i}",), quote_in_pool=80.0, mc_quote=price * 1e9))
    decision, _, ev = run(trades)
    assert decision == "SKIPPED"
    assert "drawdown_pct" in ev.penalties


def test_risky_holders_lower_score_without_blocking():
    trades = organic(seconds=120)
    clean = evaluate(trades, Context(), T0, T0 + 120, CFG)
    risky = evaluate(trades, Context(bundled_pct=55, top10_pct=45), T0, T0 + 120, CFG)
    assert risky.score < clean.score
    assert risky.score > 0  # penalty, not a hard filter
    assert {"bundled_pct", "top10_pct"} <= set(risky.penalties)


def test_liquidity_removed_penalty():
    trades = organic(seconds=120)
    ev = evaluate(trades, Context(liquidity_removed=True), T0, T0 + 120, CFG)
    assert ev.penalties["liquidity_removed"]["points"] == -40


def test_quiet_token_skips_at_max_time():
    trades = [Trade(T0 + 10 * i, "buy", 0.1, 1e-5, (f"w{i}",)) for i in range(6)]
    decision, at, ev = run(trades)
    assert decision == "SKIPPED" and at == 180
    assert ev.confidence < 1


def test_confluence_counts_feeds():
    trades = organic(seconds=120)
    one = evaluate(trades, Context(feeds=1), T0, T0 + 120, CFG)
    three = evaluate(trades, Context(feeds=3, audit_score=8, dex_paid=True), T0, T0 + 120, CFG)
    assert three.components["confluence"]["points"] == CFG["weights"]["confluence"]
    assert three.score > one.score


def test_reasons_are_readable():
    ev = evaluate(organic(seconds=120), Context(bundled_pct=50), T0, T0 + 120, CFG)
    assert any(r.startswith("Buy flow") for r in ev.reasons)
    assert "Bundled 50%" in ev.reasons


def test_acceleration_ignores_time_before_the_watch():
    # steady 1 trade/s from the moment the watch starts: no acceleration
    trades = [Trade(T0 + i, "buy", 0.5, 1e-5, (f"w{i}",)) for i in range(45)]
    ev = evaluate(trades, Context(), T0, T0 + 45, CFG)
    assert 0.8 <= ev.components["acceleration"]["value"] <= 1.3
    early = evaluate(trades[:20], Context(), T0, T0 + 20, CFG)
    assert early.components["acceleration"]["label"] == "Trades: too early"
