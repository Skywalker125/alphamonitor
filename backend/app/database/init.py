"""Create the SQLite database and tables.

Run from the backend folder:

    python app/database/init.py

Creates data/alphamonitor.db (or DB_PATH) and applies schema.sql. Safe to
run any number of times; the backend also does this on startup.
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.config import settings  # noqa: E402
from app.database import db  # noqa: E402


def init_database():

    conn = db.get_connection()

    db.apply_schema(conn)

    mode = db.enable_wal(conn)

    conn.close()

    if mode.lower() == "wal":
        print("Journal mode: WAL")

    else:
        print(
            "Journal mode: {} - could not switch to WAL. Stop the backend, "
            "then run this again.".format(mode)
        )

    print("SQLite database initialized: {}".format(settings.db_path))


if __name__ == "__main__":

    init_database()
