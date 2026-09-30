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

### Row colours and charts

- Each token row is tinted by how many feeds currently show that address: **red** = 1 feed,
  **yellow** = 2, **green** = 3 or more (the Telegram calls feed counts too).
- The first two rows of every feed get a faint price chart in the background (green rising, red
  falling), from 1-second candles of Shrine's data API. Set `SHRINE_API_KEY=sk_...` in `backend/.env`.
  The backend holds the single keyed Shrine connection (Shrine allows one candle socket per IP, and the
  key never reaches the browser), fetches each chart token once however many feeds show it, and
  refreshes every `CHART_REFRESH_SECONDS` (10). Status: `charts` in `/api/status`.

### API

| Endpoint | Description |
| --- | --- |
| `GET /api/feeds` | The five feeds |
| `GET /api/feeds/telegram?…` | Proxy to the calls API (same query params, sensible defaults) |
| `GET /api/feeds/{key}/messages?limit=&before=` | Stored TokenScan messages for a feed |
| `GET /api/stream` | SSE stream: `scan` events `{feed, item}`, `chart` events `{mint, points}` |
| `POST /api/charts/want` | `{mints: [...]}`: the tokens the page wants charts for; returns cached charts |
| `GET /api/status` | Telethon listener state and per-chat resolution errors |

Run the parser tests with `pytest` in `backend/`. After a parser change, fix already stored
messages with `python -m app.cli reparse` (no need to delete the database).

## 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8001
npm run dev                  # http://localhost:3000
```

If port 3000 is already taken, run `npx next dev -p 3001` and add that origin to `CORS_ORIGINS` in `backend/.env`.
