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

-- One row per time a token is watched on the Shrine stream. status goes
-- WATCHING -> ENTRY or SKIPPED. Market caps are USD (NULL while SOL/USD is
-- unknown). mc_5m / mc_10m record what happened after the decision, so the
-- model can be judged and tuned on real outcomes.
CREATE TABLE IF NOT EXISTS watch_sessions
(
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mint          TEXT    NOT NULL,
    symbol        TEXT,
    name          TEXT,
    status        TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,
    decided_at    TEXT,
    tracking_until TEXT,
    score         REAL,
    best_score    REAL,
    evaluation    TEXT,
    reasons       TEXT    NOT NULL DEFAULT '[]',
    sources       TEXT    NOT NULL DEFAULT '[]',
    context       TEXT    NOT NULL DEFAULT '{}',
    trades        INTEGER NOT NULL DEFAULT 0,
    start_mc      REAL,
    entry_mc      REAL,
    entry_price   REAL,
    last_mc       REAL,
    peak_mc       REAL,
    mc_5m         REAL,
    mc_10m        REAL,
    dismissed_at  TEXT,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS watch_sessions_mint_idx ON watch_sessions (mint);

CREATE INDEX IF NOT EXISTS watch_sessions_started_idx ON watch_sessions (started_at DESC);

-- Raw trades seen while a token was watched, for replaying the model offline.
CREATE TABLE IF NOT EXISTS watch_trades
(
    session_id    INTEGER NOT NULL,
    t             REAL    NOT NULL,
    side          TEXT    NOT NULL,
    quote         REAL    NOT NULL,
    price         REAL    NOT NULL,
    mc_quote      REAL,
    quote_in_pool REAL,
    traders       TEXT,
    pool          TEXT,
    signature     TEXT
);

CREATE INDEX IF NOT EXISTS watch_trades_session_idx ON watch_trades (session_id, t);
