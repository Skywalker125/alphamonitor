"""Parser for TokenScan bot messages (plain text as returned by Telethon's raw_text)."""

import re
from typing import Any

BASE58_ADDR = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
EVM_ADDR = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
NAME_LINE = re.compile(r"^[^\w$]*(?P<name>.+?)\s*\(\$(?P<symbol>[^)\s]+)\)")
# The label can be preceded by any tree glyph / emoji (├ ┣ ╰ …), so search instead of anchoring;
# the lookbehind keeps "P:" from matching inside a word.
STAT_LINE = re.compile(r"(?<![A-Za-z0-9])(?P<key>MC|ATH|USD|LIQ|VOL|1H|5M|HLD|P|DEV)\s*[:：]\s*(?P<val>.+?)\s*$")
MONEY = re.compile(r"\$?\s*(?P<num>-?[\d.,]+)\s*(?P<suffix>[KMBT])?\b", re.I)
PCT_IN_PARENS = re.compile(r"\((?P<pct>[+-]?[\d.,]+)\s*([KMB])?%")
AUDIT = re.compile(r"Audit\D{0,12}?(?P<score>\d+)\s*/\s*(?P<max>\d+)")
# Zero-width / direction marks and variation selectors Telegram leaves in text.
INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufe0e\ufe0f\ufeff]")
DEX_PAID = re.compile(r"DEX\s*\[(?P<v>[^\]]+)\]")
TOP10 = re.compile(r"Top\s*10\s*Holders?\s*\[(?P<v>[\d.]+)\s*%\]", re.I)
BUNDLED = re.compile(r"Bundled\s*\[(?P<v>[\d.]+)\s*%\]", re.I)
SNIPED = re.compile(r"Snip(?:ed|ers)\s*\[(?P<v>[\d.]+)\s*%\]", re.I)
FIRST_CALL = re.compile(r"First Call by\s+(?P<who>.+?)\s*@\s*\$?(?P<mc>[\d.,]+\s*[KMB]?)", re.I)
BUYS_SELLS = re.compile(r"B\s*(?P<b>[\d,]+)\s*/\s*S\s*(?P<s>[\d,]+)(?:\s*\((?P<pct>[+-]?[\d.]+)%\))?")
AGE_VIEWS = re.compile(r"(?P<age>\d+\s*(?:mo|[smhdwy]))\b\D{0,4}?(?P<views>\d[\d,]*)\s*$")
SOCIALS_AGE = re.compile(r"Socials\s*\[(?P<v>[^\]]+)\]", re.I)

_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_money(text: str | None) -> float | None:
    if not text:
        return None
    m = MONEY.search(text)
    if not m:
        return None
    try:
        num = float(m.group("num").replace(",", ""))
    except ValueError:
        return None
    suffix = (m.group("suffix") or "").upper()
    return num * _MULT.get(suffix, 1)


def _pct(text: str) -> float | None:
    m = PCT_IN_PARENS.search(text)
    if not m:
        return None
    try:
        v = float(m.group("pct").replace(",", ""))
    except ValueError:
        return None
    return v * _MULT.get((m.group(2) or "").upper(), 1)


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def is_token_stats(text: str | None) -> bool:
    """Only TokenScan's full scan cards carry a "Token Stats" block; skip everything else."""
    return bool(text) and "token stats" in text.lower()


def parse_tokenscan(text: str) -> dict[str, Any]:
    """Extract structured fields from a TokenScan message. Missing fields are left out/None."""
    out: dict[str, Any] = {}
    if not text:
        return out
    text = INVISIBLE.sub("", text).replace("\xa0", " ")
    lines = [ln.rstrip() for ln in text.splitlines()]

    for i, line in enumerate(lines):
        m = NAME_LINE.match(line.strip())
        if m and "name" not in out:
            out["name"] = m.group("name").strip()
            out["symbol"] = m.group("symbol").strip()
            # age / views usually live on the same or following line
            for cand in lines[i : i + 2]:
                av = AGE_VIEWS.search(cand)
                if av:
                    out["age"] = av.group("age").replace(" ", "")
                    out["views"] = int(av.group("views").replace(",", ""))
                    break
            continue

        sm = STAT_LINE.search(line)
        if sm:
            key, val = sm.group("key"), sm.group("val")
            if key == "MC":
                out["market_cap"] = parse_money(val)
            elif key == "ATH":
                out["ath"] = parse_money(val)
                out["ath_drawdown_pct"] = _pct(val)
            elif key == "USD":
                out["price_usd"] = parse_money(val.split("(")[0])
                out["price_change_pct"] = _pct(val)
            elif key == "LIQ":
                out["liquidity"] = parse_money(val)
            elif key == "VOL":
                out["volume"] = parse_money(val)
                period = re.search(r"\((\w+)\)", val)
                out["volume_period"] = period.group(1) if period else None
            elif key in ("1H", "5M"):
                bs = BUYS_SELLS.search(val)
                if bs:
                    out[f"buys_{key.lower()}"] = int(bs.group("b").replace(",", ""))
                    out[f"sells_{key.lower()}"] = int(bs.group("s").replace(",", ""))
                    out[f"change_{key.lower()}_pct"] = _float(bs.group("pct"))
            elif key == "HLD":
                h = re.search(r"[\d,]+", val)
                out["holders"] = int(h.group().replace(",", "")) if h else None
            elif key == "P":
                out["pair_short"] = val.split()[0]
            elif key == "DEV":
                out["dev_short"] = val.split()[0]

    joined = "\n".join(lines)
    if m := AUDIT.search(joined):
        out["audit_score"] = int(m.group("score"))
        out["audit_max"] = int(m.group("max"))
    if m := DEX_PAID.search(joined):
        v = m.group("v").strip().upper()
        out["dex_paid"] = not v.startswith("NOT") and v not in ("NO", "UNPAID")
    if m := TOP10.search(joined):
        out["top10_pct"] = float(m.group("v"))
    if m := BUNDLED.search(joined):
        out["bundled_pct"] = float(m.group("v"))
    if m := SNIPED.search(joined):
        out["sniped_pct"] = float(m.group("v"))
    if m := SOCIALS_AGE.search(joined):
        out["socials_age"] = m.group("v").strip()
    if m := FIRST_CALL.search(joined):
        out["first_caller"] = m.group("who").strip()
        out["first_call_mc"] = parse_money(m.group("mc"))

    # Contract address: prefer the one on its own line (the full CA near the bottom).
    address = None
    for line in reversed(lines):
        s = line.strip()
        if BASE58_ADDR.fullmatch(s) or EVM_ADDR.fullmatch(s):
            address = s
            break
    if not address:
        cands = EVM_ADDR.findall(joined) or BASE58_ADDR.findall(joined)
        address = max(cands, key=len) if cands else None
    out["address"] = address
    out["chain"] = "evm" if address and address.startswith("0x") else ("solana" if address else None)
    return out
