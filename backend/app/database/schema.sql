-- AlphaMonitor schema (SQLite). Applied by `python app/database/init.py`
-- and on every backend start; every statement is idempotent.

-- One row per TokenScan message per feed. A chat can feed several columns,
-- so the feed key is part of the primary key. Edited messages (TokenScan
-- refreshes its stats in place) update the existing row.
-- Timestamps are fixed-width ISO 8601 UTC text, so they sort as strings.
-- parsed / links / buttons / reply hold JSON text.
CREATE TABLE IF NOT EXISTS scan_messages
(
    feed_key      TEXT    NOT NULL,
    chat_id       INTEGER NOT NULL,
    message_id    INTEGER NOT NULL,
    chat_title    TEXT,
    chat_username TEXT,
    sender_id     INTEGER,
    sender_name   TEXT,
    posted_at     TEXT    NOT NULL,
    edited_at     TEXT,
    raw_text      TEXT    NOT NULL,
    address       TEXT,
    symbol        TEXT,
    name          TEXT,
    market_cap    REAL,
    parsed        TEXT    NOT NULL DEFAULT '{}',
    links         TEXT    NOT NULL DEFAULT '[]',
    buttons       TEXT    NOT NULL DEFAULT '[]',
    reply         TEXT,
    inserted_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (feed_key, chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS scan_messages_feed_posted_idx
    ON scan_messages (feed_key, posted_at DESC);

CREATE INDEX IF NOT EXISTS scan_messages_address_idx
    ON scan_messages (address);
