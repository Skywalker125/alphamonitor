from app.parser import is_token_stats, parse_message, parse_money, parse_tokenscan

SAMPLE = """🧬 Super Intelligence ($SI)
└ 💊 🌱 1m 👁 13

📊 Token Stats
 ├ MC:   $106.91K
 ├ ATH:  $120.5K (-11.28% / 1s)
 ├ USD:  0.0001075 (1.38K%)
 ├ LIQ:  $33K
 ├ VOL:  $70.76K (24h)
 ├ 1H:   B 521 / S 378 (37.83%)
 ├ HLD:  236
 ├ P:    FFw...nwdc 💊
 └ DEV:  fT5...aJYc

🔗 Socials [42s]
 └ Web • 𝕏 • About

🛡 Audit 6/10
🔴 DEX [NOT PAID] [info]
🔴 Top 10 Holders [25.59%]
🔴 Bundled [51.06%]
🟠 Sniped [13.6%]

DEX•DEF•GT•MOB•EXP•𝕏s

TRT•TRO•AXI•FMO•GM•PDR•BLO
OKX•MAE•COV•BAN•STB•PHO•BNK

DtFkKBC3Cmi9j3SxBGRUd8gvBLw7nAasrvUJFB69yubM

✨ First Call by jensonSOL @ 106.91K

💭 NEW: Introducing community /thesis and /comment
"""


def test_parse_money():
    assert parse_money("$106.91K") == 106910
    assert parse_money("$1.2M") == 1_200_000
    assert parse_money("$33K") == 33000
    assert parse_money("n/a") is None


def test_parse_tokenscan_sample():
    p = parse_tokenscan(SAMPLE)
    assert p["name"] == "Super Intelligence"
    assert p["symbol"] == "SI"
    assert p["age"] == "1m"
    assert p["views"] == 13
    assert p["market_cap"] == 106910
    assert p["ath"] == 120500
    assert p["ath_drawdown_pct"] == -11.28
    assert p["price_usd"] == 0.0001075
    assert p["price_change_pct"] == 1380
    assert p["liquidity"] == 33000
    assert p["volume"] == 70760
    assert p["volume_period"] == "24h"
    assert p["buys_1h"] == 521 and p["sells_1h"] == 378
    assert p["change_1h_pct"] == 37.83
    assert p["holders"] == 236
    assert p["pair_short"] == "FFw...nwdc"
    assert p["dev_short"] == "fT5...aJYc"
    assert p["audit_score"] == 6 and p["audit_max"] == 10
    assert p["dex_paid"] is False
    assert p["top10_pct"] == 25.59
    assert p["bundled_pct"] == 51.06
    assert p["sniped_pct"] == 13.6
    assert p["socials_age"] == "42s"
    assert p["first_caller"] == "jensonSOL"
    assert p["first_call_mc"] == 106910
    assert p["address"] == "DtFkKBC3Cmi9j3SxBGRUd8gvBLw7nAasrvUJFB69yubM"
    assert p["chain"] == "solana"


def test_non_scan_message_has_no_address():
    assert parse_tokenscan("gm everyone, what are we buying?")["address"] is None


def test_only_token_stats_messages_count():
    assert is_token_stats(SAMPLE)
    assert not is_token_stats("DtFkKBC3Cmi9j3SxBGRUd8gvBLw7nAasrvUJFB69yubM")
    assert not is_token_stats("")
    assert not is_token_stats(None)


# Same card as the second screenshot, written with other tree glyphs, emoji
# placeholders, zero-width marks and NBSPs - the variants that broke the stats.
VARIANT = (
    "🔲 Super Intelligence ($SI)\n"
    "┗🟦🟨 🌱 387d 👁 71\n"
    "\n"
    "📶 Token Stats\n"
    "┣​ MC:   $54.9K\n"
    "┣ 🔹ATH: $61.98K (-11.42% / 1m)\n"
    "╠ USD:  0.00005562 (1.27K%)\n"
    "┠─ LIQ:  $21.64K\n"
    "⎬ VOL： $131.8K (24h)\n"
    "‣ 1H:   B 492 / S 293 (67.92%)\n"
    "┣ HLD:⁠ 242\n"
    "┣ P:    C3U...9mwn 💊\n"
    "╰ DEV:  2EE...hQAs\n"
    "\n"
    "🔗 Socials [2h]\n"
    "└ Web • 𝕏 • About\n"
    "\n"
    "🛡 Audit 🟧 8/10\n"
    "🟩 DEX [PAID] [info]\n"
    "🟥 Top 10 Holders [27.55%]\n"
    "🟧 Bundled [25.75%]\n"
    "\n"
    "DtFkKBC3Cmi9j3SxBGRUd8gvBLw7nAasrvUJFB69yubM\n"
)


def test_parse_tokenscan_variant_glyphs():
    p = parse_tokenscan(VARIANT)
    assert p["market_cap"] == 54900
    assert p["ath"] == 61980
    assert p["price_usd"] == 0.00005562
    assert p["liquidity"] == 21640
    assert p["volume"] == 131800
    assert p["buys_1h"] == 492 and p["sells_1h"] == 293
    assert p["holders"] == 242
    assert p["pair_short"] == "C3U...9mwn"
    assert p["dev_short"] == "2EE...hQAs"
    assert p["audit_score"] == 8 and p["audit_max"] == 10
    assert p["dex_paid"] is True
    assert p["top10_pct"] == 27.55
    assert p["bundled_pct"] == 25.75
    assert p["age"] == "387d" and p["views"] == 71


def test_other_lines_are_not_stats():
    p = parse_tokenscan("💭 NEW: Introducing community /thesis\nTOP: 5\nCAP: 1")
    assert "market_cap" not in p and "pair_short" not in p


def _link(text, label, url, nth=0):
    """A link entity as the listener stores it: label, url and character offset."""
    idx = -1
    for _ in range(nth + 1):
        idx = text.index(label, idx + 1)
    return {"text": label, "url": url, "offset": idx}


def test_socials_from_socials_block_only():
    links = [
        _link(SAMPLE, "Web", "https://supint.ai"),
        _link(SAMPLE, "𝕏", "https://x.com/supint"),
        _link(SAMPLE, "About", "https://t.me/tokenscan?start=about"),
        # platform links further down must not count as socials
        _link(SAMPLE, "DEX", "https://dexscreener.com/solana/x", nth=1),
        _link(SAMPLE, "𝕏s", "https://x.com/search?q=x"),
        _link(SAMPLE, "TRT", "https://trojan.app"),
    ]
    socials = parse_message(SAMPLE, links)["socials"]
    assert socials == [
        {"label": "Web", "url": "https://supint.ai", "kind": "web"},
        {"label": "𝕏", "url": "https://x.com/supint", "kind": "x"},
        {"label": "About", "url": "https://t.me/tokenscan?start=about", "kind": "telegram"},
    ]


def test_socials_fallback_without_offsets():
    links = [
        {"text": "Web", "url": "https://supint.ai"},
        {"text": "𝕏s", "url": "https://x.com/search?q=x"},
        {"text": "TRT", "url": "https://trojan.app"},
    ]
    assert [s["label"] for s in parse_message(SAMPLE, links)["socials"]] == ["Web"]


def test_no_socials_without_links():
    assert parse_message(SAMPLE, [])["socials"] == []
