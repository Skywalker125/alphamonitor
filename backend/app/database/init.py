"""Create the PostgreSQL database and tables.

Run from the backend folder:

    python app/database/init.py

Creates the database named in DATABASE_URL if it doesn't exist yet, then
applies schema.sql. Safe to run any number of times. Postgres itself has to
be running; the backend also does all of this on startup.
"""

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.config import settings  # noqa: E402
from app.database import db  # noqa: E402


async def init_database():

    created = await db.ensure_database(settings.database_url)

    print("Database created" if created else "Database already exists")

    await db.init(settings.database_url)

    await db.close()

    print("PostgreSQL database initialized")


if __name__ == "__main__":

    try:
        asyncio.run(init_database())

    except Exception as e:
        sys.exit(
            "Database init failed: {}: {}\n"
            "Is Postgres running, and is DATABASE_URL in backend/.env right?".format(
                type(e).__name__, e
            )
        )
