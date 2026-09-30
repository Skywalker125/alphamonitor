"""Helper commands.

    python -m app.cli login        # log the Telethon session in (interactive, once)
    python -m app.cli chats        # list your dialogs with their ids, to fill feeds.json
    python -m app.cli reparse      # re-run the parser over every stored message
    python -m app.cli charts-check [MINT]  # test the Shrine key/connection, print one chart
    python -m app.cli parse FILE   # run the TokenScan parser on a text file
"""

import asyncio
import json
import sys

from .config import settings
from .parser import parse_message, parse_tokenscan


def _client():
    from telethon import TelegramClient

    if not settings.telegram_configured:
        sys.exit("Set TG_API_ID and TG_API_HASH in backend/.env first.")
    return TelegramClient(str(settings.tg_session_path), settings.tg_api_id, settings.tg_api_hash)


async def login() -> None:
    client = _client()
    await client.start()  # prompts for phone, code and 2FA password
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username}). Session: {settings.tg_session_path}.session")
    await client.disconnect()


async def chats() -> None:
    from telethon import utils

    client = _client()
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Not logged in. Run: python -m app.cli login")
    async for d in client.iter_dialogs():
        uname = getattr(d.entity, "username", None)
        print(f"{d.id:>16}  {'@' + uname if uname else '':<24} {utils.get_display_name(d.entity)}")
    await client.disconnect()


def latest_feed_token() -> str:
    """The newest token address from the feeds (a real token with a pool)."""
    from .database import db

    db.init_sync()
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT address FROM scan_messages WHERE address IS NOT NULL "
            "ORDER BY posted_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit("No token in the feeds yet: run  python -m app.cli charts-check <token address>")
    return row["address"]


async def charts_check(mint: str) -> None:
    import time

    from .charts import ChartService

    svc = ChartService(settings.shrine_data_url, settings.shrine_api_key,
                       socketio_path=settings.shrine_socketio_path)
    if not svc.enabled:
        sys.exit("SHRINE_API_KEY is not set in backend/.env")
    print(f"Trying {len(svc.endpoints)} endpoint(s) with token {mint} ...")
    ok = await svc._connect(probe_mint=mint)
    for line in svc.attempts:
        print("  " + line)
    if not ok:
        sys.exit("No endpoint worked. Paste these lines to get it fixed.")
    ep = svc.endpoint
    print(f"Connected to {ep.label()}")
    print(f"(to pin it: SHRINE_DATA_URL={ep.server}{'' if ep.namespace == '/' else ep.namespace}"
          f"{'' if ep.path == 'socket.io' else f' and SHRINE_SOCKETIO_PATH={ep.path}'})")
    print("Requesting ohlcv_history (500 candles) for", mint)
    started = time.monotonic()
    await svc._refresh(mint)
    print(f"(reply after {time.monotonic() - started:.1f}s)")
    entry = svc.cache.get(mint, {})
    if entry.get("error"):
        print("Reply error:", entry["error"])
    else:
        pts = entry.get("points", [])
        span = (pts[-1][0] - pts[0][0]) if len(pts) > 1 else 0
        print(f"OK: pool {entry.get('pool')}, {len(pts)} points over {span}s, last close {pts[-1][1] if pts else None}")
    await svc.sio.disconnect()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        asyncio.run(login())
    elif cmd == "chats":
        asyncio.run(chats())
    elif cmd == "reparse":
        from .database import db

        db.init_sync()
        total, changed = db.reparse_all(parse_message)
        print(f"Re-parsed {total} messages, {changed} updated.")
    elif cmd == "charts-check":
        mint = sys.argv[2] if len(sys.argv) > 2 else latest_feed_token()
        asyncio.run(charts_check(mint))
    elif cmd == "parse" and len(sys.argv) > 2:
        with open(sys.argv[2], encoding="utf-8") as f:
            print(json.dumps(parse_tokenscan(f.read()), indent=2, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
