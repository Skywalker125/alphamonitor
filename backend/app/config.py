import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


# Only TokenScan posts are scraped unless a feed names other senders.
DEFAULT_SENDERS = ["TokenScan"]


@dataclass
class FeedConfig:
    key: str
    title: str
    description: str = ""
    # Chat usernames, invite-less links, or numeric ids ("-100...").
    chats: list[str | int] = field(default_factory=list)
    # Sender filter: username / display name substrings (case-insensitive).
    senders: list[str] = field(default_factory=lambda: list(DEFAULT_SENDERS))


@dataclass
class Settings:
    db_path: Path
    db_busy_timeout_ms: int
    calls_api_url: str
    tg_api_id: int | None
    tg_api_hash: str | None
    tg_session: str
    backfill_limit: int
    cors_origins: list[str]
    feeds: list[FeedConfig]
    shrine_api_key: str | None
    shrine_data_url: str
    shrine_socketio_path: str | None
    chart_refresh_seconds: float

    @property
    def tg_session_path(self) -> Path:
        p = Path(self.tg_session)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def telegram_configured(self) -> bool:
        return bool(self.tg_api_id and self.tg_api_hash)


def _load_feeds(path: str) -> list[FeedConfig]:
    p = Path(path)
    if not p.is_absolute():
        p = BACKEND_DIR / p
    if not p.exists():
        p = BACKEND_DIR / "feeds.example.json"
    raw = json.loads(p.read_text())
    return [
        FeedConfig(
            key=f["key"],
            title=f.get("title", f["key"]),
            description=f.get("description", ""),
            chats=list(f.get("chats", [])),
            senders=list(f.get("senders") or DEFAULT_SENDERS),
        )
        for f in raw
    ]


def _resolve(path: str | Path) -> Path:
    """Relative paths are relative to the backend folder, not the current directory."""
    p = Path(path)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_settings() -> Settings:
    api_id = os.getenv("TG_API_ID", "").strip()
    return Settings(
        db_path=_resolve(
            os.getenv("DB_PATH")
            or Path(os.getenv("DATA_DIR", "data")) / "alphamonitor.db"
        ),
        db_busy_timeout_ms=int(os.getenv("DB_BUSY_TIMEOUT_MS", "5000")),
        calls_api_url=os.getenv("CALLS_API_URL", "http://localhost:8000/api/feed/calls"),
        tg_api_id=int(api_id) if api_id else None,
        tg_api_hash=os.getenv("TG_API_HASH", "").strip() or None,
        tg_session=os.getenv("TG_SESSION", "alphamonitor"),
        backfill_limit=int(os.getenv("BACKFILL_LIMIT", "50")),
        cors_origins=[
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
            ).split(",")
            if o.strip()
        ],
        feeds=_load_feeds(os.getenv("FEEDS_FILE", "feeds.json")),
        shrine_api_key=os.getenv("SHRINE_API_KEY", "").strip() or None,
        shrine_data_url=os.getenv("SHRINE_DATA_URL", "auto"),
        shrine_socketio_path=os.getenv("SHRINE_SOCKETIO_PATH", "").strip() or None,
        chart_refresh_seconds=float(os.getenv("CHART_REFRESH_SECONDS", "10")),
    )


settings = load_settings()
