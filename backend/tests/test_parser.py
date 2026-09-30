from app.parser import is_token_stats, parse_money, parse_tokenscan

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
