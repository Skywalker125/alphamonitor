# AlphaMonitor

Live dashboard with five feeds:

1. **Telegram** – calls from your existing calls API (`http://localhost:8000/api/feed/calls`), polled every 5 s.
2. **Scan feeds 1–4** – TokenScan bot messages scraped live with [Telethon](https://docs.telethon.dev) from Telegram groups/channels you choose, stored in Postgres and pushed to the browser over Server-Sent Events.

```
frontend/  Next.js (App Router) UI            → http://localhost:3000
backend/   FastAPI + Telethon + asyncpg        → http://localhost:8001
```

The backend runs on **8001** because your calls API already uses 8000. It proxies the calls API (`/api/feeds/telegram`), so the browser never talks to port 8000 directly.

## 1. Postgres

Use a local Postgres, or start one with `docker compose up -d postgres`. Then create the database:

```bash
createdb -U postgres alphamonitor
```

The `scan_messages` table is created automatically on backend startup.

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
- `senders` – optional filter: only messages whose sender username / display name contains one of these strings. Leave empty to accept every message in the chat.
- Only messages containing a contract address are stored (chatter is ignored). Edits (TokenScan refreshes its stats) update the stored row.
- On startup the last `BACKFILL_LIMIT` messages of every chat are imported.

Telethon logs in as your **user account** (bots can't read other bots' messages), so you must be a member of every chat you list.

### API

| Endpoint | Description |
| --- | --- |
| `GET /api/feeds` | The five feeds |
| `GET /api/feeds/telegram?…` | Proxy to the calls API (same query params, sensible defaults) |
| `GET /api/feeds/{key}/messages?limit=&before=` | Stored TokenScan messages for a feed |
| `GET /api/stream` | SSE stream, `scan` events: `{feed, item}` |
| `GET /api/status` | Telethon listener state and per-chat resolution errors |

Run the parser tests with `pytest` in `backend/`.

## 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8001
npm run dev                  # http://localhost:3000
```

If port 3000 is already taken, run `npx next dev -p 3001` and add that origin to `CORS_ORIGINS` in `backend/.env`.
