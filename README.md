# AlphaMonitor

Live dashboard with five feeds:

1. **Telegram** – calls from your existing calls API (`http://localhost:8000/api/feed/calls`), polled every 5 s.
2. **Scan feeds 1–4** – TokenScan bot messages scraped live with [Telethon](https://docs.telethon.dev) from Telegram groups/channels you choose, stored in SQLite and pushed to the browser over Server-Sent Events.

```
frontend/  Next.js (App Router) UI            → http://localhost:3000
backend/   FastAPI + Telethon + SQLite         → http://localhost:8001
```

The backend runs on **8001** because your calls API already uses 8000. It proxies the calls API (`/api/feeds/telegram`), so the browser never talks to port 8000 directly.

## 1. Database (SQLite – no server needed)

```bash
cd backend
python app/database/init.py
```

Creates `backend/data/alphamonitor.db` (override with `DB_PATH`) and applies
`app/database/schema.sql` in WAL mode. Safe to re-run; the backend does the same on startup.

## 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # fill TG_API_ID / TG_API_HASH from https://my.telegram.org
python -m app.cli login           # one-time interactive Telegram login (creates alphamonitor.session)
python -m app.cli chats           # prints your chats with their ids
cp feeds.example.json feeds.json  # put the chat ids / @usernames in the 4 feeds
uvicorn app.main:app --port 8001
```

### feeds.json

```json
[
  { "key": "scan_1", "title": "Scan Alpha", "description": "…",
    "chats": ["-1001234567890", "some_public_group"],
    "senders": ["TokenScan"] }
]
```

- `chats` – numeric chat ids (from `app.cli chats`) or public usernames. A chat can appear in several feeds.
- `senders` – only messages whose sender username / display name contains one of these strings are kept. Defaults to `["TokenScan"]` when left out or empty.
- The links under **Socials** (Web • 𝕏 • About …) are shown on each row; click a social to open it.
- Only TokenScan scan cards are stored: the message must contain **"Token Stats"** and a contract address (chatter, commands and other bot replies are ignored). Edits (TokenScan refreshes its stats) update the stored row.
- On startup the last `BACKFILL_LIMIT` messages of every chat are imported.

Telethon logs in as your **user account** (bots can't read other bots' messages), so you must be a member of every chat you list.

### API

| Endpoint | Description |
| --- | --- |
| `GET /api/feeds` | The five feeds |
| `GET /api/feeds/telegram?…` | Proxy to the calls API (same query params, sensible defaults) |
| `GET /api/feeds/{key}/messages?limit=&before=` | Stored TokenScan messages for a feed |
| `GET /api/stream` | SSE stream, `scan` events: `{feed, item}` |
| `GET /api/status` | Telethon listener state, per-chat errors, trade-stream and watcher state |
| `GET /api/signals?minutes=60` | Watch sessions (watching / entry / skipped) with live state |
| `POST /api/signals/{mint}/dismiss` | Hide an entry card (its outcome is still recorded) |
| `GET /api/signals/history` | Decided sessions with outcomes, for tuning |

Run the parser tests with `pytest` in `backend/`. After a parser change, fix already stored
messages with `python -m app.cli reparse` (no need to delete the database).

## Entry signals

Every **new** TokenScan token (message under 2 min old, not an edit) is watched live on
[Shrine's](https://sol.shrine.trade) free, keyless Socket.IO trade stream for 60–180 s and scored.
Tokens that qualify appear in the **Entry signals** box above the feeds with a live market cap for
10 minutes. Feed rows show a badge: `👁 1:24` watching, `✅ ENTRY 78`, `✖ skip 42`.

- **One watch per token.** The same address from several feeds or messages joins the running watch
  (each extra feed counts towards the score). One socket, subscribed once; events for other tokens
  are dropped with a set lookup. Up to `WATCH_CAPACITY` (100) tokens at a time, the rest queue for 2 min.
- **Score (0–100), every 5 s:** order-flow imbalance (buy vs sell volume), trade-rate acceleration,
  unique/new buyers, buyer dispersion (share of the biggest buyer), trend quality (return, higher lows,
  above VWAP) and confluence (feeds, audit, DEX paid).
- **No hard filters.** Risks only subtract points: TokenScan top-10 / bundled / sniped %, drawdown from
  the high, MC drop since the watch started, a single sell that's a large share of the pool, liquidity
  removed. With few trades the score is scaled down instead of blocked.
- **ENTRY** needs score ≥ 70 on two evaluations in a row, from 60 s on. No ENTRY by 180 s → skipped.
- Weights and thresholds live in `backend/signals.json`. Every session is stored with its score breakdown,
  raw trades and outcome (MC at entry, +5 min, +10 min, peak; skips get +10 min too), so you can check the
  hit rate at `GET /api/signals/history` and tune.
- Market caps are in USD using SOL/USD from Jupiter (CoinGecko fallback). Stream health is in `/api/status`.
- Turn it off with `SIGNALS_ENABLED=false`.

This is a transparent momentum/order-flow heuristic, not a proven edge. Judge it by the recorded outcomes.

## 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8001
npm run dev                  # http://localhost:3000
```

If port 3000 is already taken, run `npx next dev -p 3001` and add that origin to `CORS_ORIGINS` in `backend/.env`.
