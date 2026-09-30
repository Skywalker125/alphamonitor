import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import asyncpg

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

COLUMNS = (
    "feed_key, chat_id, message_id, chat_title, chat_username, sender_id, sender_name, "
    "posted_at, edited_at, raw_text, address, symbol, name, market_cap, parsed, links, "
    "buttons, reply, inserted_at"
)

log = logging.getLogger("alphamonitor.db")

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def ensure_database(database_url: str) -> bool:
    """Create the database from DATABASE_URL if it doesn't exist. Returns True if created."""
    url = urlsplit(database_url)
    name = unquote(url.path.lstrip("/"))
    if not name:
        raise ValueError("DATABASE_URL has no database name")
    try:
        conn = await asyncpg.connect(database_url)
        await conn.close()
        return False
    except asyncpg.InvalidCatalogNameError:
        pass
    # connect to the default "postgres" maintenance database to create ours
    admin = await asyncpg.connect(urlunsplit(url._replace(path="/postgres")))
    try:
        await admin.execute(f'CREATE DATABASE "{name.replace(chr(34), chr(34) * 2)}"')
    finally:
        await admin.close()
    return True


async def init(database_url: str) -> asyncpg.Pool:
    global _pool
    if await ensure_database(database_url):
        log.info("Created database from DATABASE_URL")
    _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10, init=_init_conn)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    return _pool


async def close() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database not initialised")
    return _pool


def row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    item = dict(row)
    for k in ("posted_at", "edited_at", "inserted_at"):
        if isinstance(item.get(k), datetime):
            item[k] = item[k].isoformat()
    return item


async def upsert_scan(rec: dict[str, Any]) -> dict[str, Any]:
    row = await pool().fetchrow(
        f"""
        INSERT INTO scan_messages (
            feed_key, chat_id, message_id, chat_title, chat_username, sender_id, sender_name,
            posted_at, edited_at, raw_text, address, symbol, name, market_cap,
            parsed, links, buttons, reply
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
        ON CONFLICT (feed_key, chat_id, message_id) DO UPDATE SET
            chat_title = EXCLUDED.chat_title,
            chat_username = EXCLUDED.chat_username,
            edited_at  = EXCLUDED.edited_at,
            raw_text   = EXCLUDED.raw_text,
            address    = COALESCE(EXCLUDED.address, scan_messages.address),
            symbol     = COALESCE(EXCLUDED.symbol, scan_messages.symbol),
            name       = COALESCE(EXCLUDED.name, scan_messages.name),
            market_cap = COALESCE(EXCLUDED.market_cap, scan_messages.market_cap),
            parsed     = EXCLUDED.parsed,
            links      = EXCLUDED.links,
            buttons    = EXCLUDED.buttons,
            reply      = COALESCE(EXCLUDED.reply, scan_messages.reply)
        RETURNING {COLUMNS}
        """,
        rec["feed_key"],
        rec["chat_id"],
        rec["message_id"],
        rec.get("chat_title"),
        rec.get("chat_username"),
        rec.get("sender_id"),
        rec.get("sender_name"),
        rec["posted_at"],
        rec.get("edited_at"),
        rec["raw_text"],
        rec.get("address"),
        rec.get("symbol"),
        rec.get("name"),
        rec.get("market_cap"),
        rec.get("parsed") or {},
        rec.get("links") or [],
        rec.get("buttons") or [],
        rec.get("reply"),
    )
    return row_to_item(row)


async def list_scans(
    feed_key: str, limit: int = 50, before: datetime | None = None
) -> list[dict[str, Any]]:
    rows = await pool().fetch(
        f"""
        SELECT {COLUMNS} FROM scan_messages
        WHERE feed_key = $1 AND ($2::timestamptz IS NULL OR posted_at < $2)
        ORDER BY posted_at DESC, message_id DESC
        LIMIT $3
        """,
        feed_key,
        before,
        limit,
    )
    return [row_to_item(r) for r in rows]
