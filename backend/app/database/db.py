import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

JSON_COLUMNS = ("parsed", "links", "buttons", "reply")

COLUMNS = (
    "feed_key, chat_id, message_id, chat_title, chat_username, sender_id, sender_name, "
    "posted_at, edited_at, raw_text, address, symbol, name, market_cap, parsed, links, "
    "buttons, reply, inserted_at"
)

# SQLite allows exactly one writer; the listener is the only one, but keep
# writes queued in-process rather than colliding inside SQLite.
_write_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = settings.db_busy_timeout_ms
    # Autocommit: every statement commits on its own, so no deferred
    # transaction ever has to upgrade its lock ("database is locked").
    conn = sqlite3.connect(settings.db_path, timeout=timeout_ms / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={timeout_ms}")
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn


def enable_wal(conn: sqlite3.Connection) -> str:
    """WAL lets the API read while the listener writes. Stored in the file, so once is enough."""
    try:
        return str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0])
    except sqlite3.OperationalError as e:
        return f"unchanged ({e})"


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))


def init_sync() -> str:
    conn = get_connection()
    try:
        apply_schema(conn)
        return enable_wal(conn)
    finally:
        conn.close()


async def init() -> None:
    await asyncio.to_thread(init_sync)


async def close() -> None:
    """Connections are per call; nothing to close. Kept for a symmetric lifespan."""


def ts(value: datetime | str | None) -> str | None:
    """Fixed-width UTC ISO text, so timestamps compare correctly as strings."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for k in JSON_COLUMNS:
        if item.get(k) is not None:
            item[k] = json.loads(item[k])
    return item


def _upsert_scan(rec: dict[str, Any]) -> dict[str, Any]:
    params = (
        rec["feed_key"],
        rec["chat_id"],
        rec["message_id"],
        rec.get("chat_title"),
        rec.get("chat_username"),
        rec.get("sender_id"),
        rec.get("sender_name"),
        ts(rec["posted_at"]),
        ts(rec.get("edited_at")),
        rec["raw_text"],
        rec.get("address"),
        rec.get("symbol"),
        rec.get("name"),
        rec.get("market_cap"),
        json.dumps(rec.get("parsed") or {}),
        json.dumps(rec.get("links") or []),
        json.dumps(rec.get("buttons") or []),
        json.dumps(rec["reply"]) if rec.get("reply") is not None else None,
    )
    with _write_lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO scan_messages (
                    feed_key, chat_id, message_id, chat_title, chat_username, sender_id,
                    sender_name, posted_at, edited_at, raw_text, address, symbol, name,
                    market_cap, parsed, links, buttons, reply
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT (feed_key, chat_id, message_id) DO UPDATE SET
                    chat_title    = excluded.chat_title,
                    chat_username = excluded.chat_username,
                    edited_at     = excluded.edited_at,
                    raw_text      = excluded.raw_text,
                    address       = COALESCE(excluded.address, scan_messages.address),
                    symbol        = COALESCE(excluded.symbol, scan_messages.symbol),
                    name          = COALESCE(excluded.name, scan_messages.name),
                    market_cap    = COALESCE(excluded.market_cap, scan_messages.market_cap),
                    parsed        = excluded.parsed,
                    links         = excluded.links,
                    buttons       = excluded.buttons,
                    reply         = COALESCE(excluded.reply, scan_messages.reply)
                """,
                params,
            )
            row = conn.execute(
                f"SELECT {COLUMNS} FROM scan_messages "
                "WHERE feed_key = ? AND chat_id = ? AND message_id = ?",
                params[:3],
            ).fetchone()
        finally:
            conn.close()
    return row_to_item(row)


def _list_scans(feed_key: str, limit: int, before: datetime | None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT {COLUMNS} FROM scan_messages
            WHERE feed_key = ? AND (? IS NULL OR posted_at < ?)
            ORDER BY posted_at DESC, message_id DESC
            LIMIT ?
            """,
            (feed_key, ts(before), ts(before), limit),
        ).fetchall()
    finally:
        conn.close()
    return [row_to_item(r) for r in rows]


async def upsert_scan(rec: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_upsert_scan, rec)


async def list_scans(
    feed_key: str, limit: int = 50, before: datetime | None = None
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_scans, feed_key, limit, before)


def reparse_all(parse) -> tuple[int, int]:
    """Re-run `parse` over every stored raw_text (after a parser fix). Returns (rows, changed)."""
    with _write_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT feed_key, chat_id, message_id, raw_text, parsed FROM scan_messages"
            ).fetchall()
            changed = 0
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                p = parse(r["raw_text"])
                new = json.dumps(p)
                if new == r["parsed"]:
                    continue
                conn.execute(
                    """
                    UPDATE scan_messages
                    SET parsed = ?, address = COALESCE(?, address), symbol = COALESCE(?, symbol),
                        name = COALESCE(?, name), market_cap = ?
                    WHERE feed_key = ? AND chat_id = ? AND message_id = ?
                    """,
                    (new, p.get("address"), p.get("symbol"), p.get("name"), p.get("market_cap"),
                     r["feed_key"], r["chat_id"], r["message_id"]),
                )
                changed += 1
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    return len(rows), changed
