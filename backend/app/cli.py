"""Helper commands.

    python -m app.cli login        # log the Telethon session in (interactive, once)
    python -m app.cli chats        # list your dialogs with their ids, to fill feeds.json
    python -m app.cli parse FILE   # run the TokenScan parser on a text file
"""

import asyncio
import json
import sys

from .config import settings
from .parser import parse_tokenscan


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


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        asyncio.run(login())
    elif cmd == "chats":
        asyncio.run(chats())
    elif cmd == "parse" and len(sys.argv) > 2:
        with open(sys.argv[2], encoding="utf-8") as f:
            print(json.dumps(parse_tokenscan(f.read()), indent=2, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
