"""Telethon user-client that listens to the configured chats and stores TokenScan messages."""

import asyncio
import logging
from typing import Any

from telethon import TelegramClient, events, utils
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from .database import db
from .broadcaster import broadcaster
from .config import FeedConfig, Settings
from .parser import is_token_stats, parse_tokenscan

log = logging.getLogger("alphamonitor.telegram")


def _chat_ref(ref: str | int) -> str | int:
    """Numeric strings are chat ids; everything else is a username / t.me link."""
    if isinstance(ref, int):
        return ref
    s = str(ref).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    return s


def _sender_matches(feed: FeedConfig, sender: Any) -> bool:
    if not feed.senders:
        return True
    if sender is None:
        return False
    haystack = " ".join(
        filter(None, [getattr(sender, "username", None), utils.get_display_name(sender)])
    ).lower()
    return any(s.lower().lstrip("@") in haystack for s in feed.senders)


def _extract_links(msg: Any) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    try:
        for ent, text in msg.get_entities_text():
            if isinstance(ent, MessageEntityTextUrl):
                links.append({"text": text, "url": ent.url})
            elif isinstance(ent, MessageEntityUrl):
                links.append({"text": text, "url": text})
    except Exception:  # entities may be malformed on edited messages
        log.debug("could not extract entities", exc_info=True)
    return links


def _extract_buttons(msg: Any) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    markup = getattr(msg, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for b in row.buttons:
            url = getattr(b, "url", None)
            out.append({"text": b.text, "url": url if isinstance(url, str) else None})
    return out


class TelegramListener:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: TelegramClient | None = None
        # peer id -> feeds that listen to it
        self.chat_feeds: dict[int, list[FeedConfig]] = {}
        self.status: dict[str, Any] = {"state": "stopped", "error": None, "chats": {}}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.settings.telegram_configured:
            self.status = {
                "state": "disabled",
                "error": "TG_API_ID / TG_API_HASH not set",
                "chats": {},
            }
            log.warning("Telegram listener disabled: TG_API_ID / TG_API_HASH not set")
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.client:
            await self.client.disconnect()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self) -> None:
        s = self.settings
        self.client = TelegramClient(str(s.tg_session_path), s.tg_api_id, s.tg_api_hash)
        self.status["state"] = "connecting"
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                self.status.update(
                    state="unauthorized",
                    error="Session not logged in. Run: python -m app.cli login",
                )
                log.error(self.status["error"])
                return

            await self._resolve_chats()
            chat_ids = list(self.chat_feeds)
            if not chat_ids:
                self.status.update(state="idle", error="No chats configured in feeds file")
                return

            self.client.add_event_handler(self._on_message, events.NewMessage(chats=chat_ids))
            self.client.add_event_handler(self._on_message, events.MessageEdited(chats=chat_ids))
            self.status.update(state="listening", error=None)
            log.info("Listening to %d chats", len(chat_ids))

            await self._backfill()
            await self.client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # keep the API alive even if Telegram fails
            log.exception("Telegram listener crashed")
            self.status.update(state="error", error=str(e))

    async def _resolve_chats(self) -> None:
        assert self.client
        for feed in self.settings.feeds:
            for ref in feed.chats:
                key = str(ref)
                try:
                    entity = await self.client.get_entity(_chat_ref(ref))
                    peer_id = utils.get_peer_id(entity)
                    self.chat_feeds.setdefault(peer_id, []).append(feed)
                    self.status["chats"][key] = {
                        "ok": True,
                        "id": peer_id,
                        "title": utils.get_display_name(entity),
                    }
                except Exception as e:
                    log.error("Cannot resolve chat %r for feed %s: %s", ref, feed.key, e)
                    self.status["chats"][key] = {"ok": False, "error": str(e)}

    async def _backfill(self) -> None:
        assert self.client
        limit = self.settings.backfill_limit
        if limit <= 0:
            return
        for chat_id in self.chat_feeds:
            try:
                msgs = [m async for m in self.client.iter_messages(chat_id, limit=limit)]
                for msg in reversed(msgs):
                    await self._handle(msg, publish=False)
                log.info("Backfilled %d messages from %s", len(msgs), chat_id)
            except Exception:
                log.exception("Backfill failed for %s", chat_id)

    async def _on_message(self, event: Any) -> None:
        try:
            await self._handle(event.message, publish=True)
        except Exception:
            log.exception("Failed to handle message")

    async def _handle(self, msg: Any, publish: bool) -> None:
        text = msg.raw_text or ""
        if not is_token_stats(text):
            return
        feeds = self.chat_feeds.get(msg.chat_id, [])
        if not feeds:
            return

        sender = await msg.get_sender()
        matching = [f for f in feeds if _sender_matches(f, sender)]
        if not matching:
            return

        parsed = parse_tokenscan(text)
        if not parsed.get("address"):
            return

        chat = await msg.get_chat()
        reply = None
        if msg.is_reply:
            try:
                r = await msg.get_reply_message()
                if r:
                    rs = await r.get_sender()
                    reply = {
                        "message_id": r.id,
                        "sender_name": utils.get_display_name(rs) if rs else None,
                        "text": (r.raw_text or "")[:500],
                    }
            except Exception:
                log.debug("could not load reply", exc_info=True)

        base = {
            "chat_id": msg.chat_id,
            "message_id": msg.id,
            "chat_title": utils.get_display_name(chat) if chat else None,
            "chat_username": getattr(chat, "username", None),
            "sender_id": msg.sender_id,
            "sender_name": utils.get_display_name(sender) if sender else None,
            "posted_at": msg.date,
            "edited_at": msg.edit_date,
            "raw_text": text,
            "address": parsed.get("address"),
            "symbol": parsed.get("symbol"),
            "name": parsed.get("name"),
            "market_cap": parsed.get("market_cap"),
            "parsed": parsed,
            "links": _extract_links(msg),
            "buttons": _extract_buttons(msg),
            "reply": reply,
        }
        for feed in matching:
            item = await db.upsert_scan({**base, "feed_key": feed.key})
            if publish:
                broadcaster.publish("scan", {"feed": feed.key, "item": item})
