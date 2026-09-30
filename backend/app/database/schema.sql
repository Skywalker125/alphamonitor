-- AlphaMonitor schema (PostgreSQL). Applied by `python app/database/init.py`
-- and on every backend start; every statement is idempotent.

-- One row per TokenScan message per feed. A chat can feed several columns,
-- so the feed key is part of the primary key. Edited messages (TokenScan
-- refreshes its stats in place) update the existing row.
CREATE TABLE IF NOT EXISTS scan_messages (
    feed_key     text        NOT NULL,
    chat_id      bigint      NOT NULL,
    message_id   bigint      NOT NULL,
    chat_title   text,
    chat_username text,
    sender_id    bigint,
    sender_name  text,
    posted_at    timestamptz NOT NULL,
    edited_at    timestamptz,
    raw_text     text        NOT NULL,
    address      text,
    symbol       text,
    name         text,
    market_cap   double precision,
    parsed       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    links        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    buttons      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    reply        jsonb,
    inserted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (feed_key, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS scan_messages_feed_posted_idx
    ON scan_messages (feed_key, posted_at DESC);
CREATE INDEX IF NOT EXISTS scan_messages_address_idx
    ON scan_messages (address);
