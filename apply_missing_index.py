"""Apply the D-09 functional index (CREATE INDEX CONCURRENTLY).

Must run outside a transaction; uses an autocommit connection. Safe to re-run.
"""
import os
import sys
from pathlib import Path

ENV_CANDIDATES = [
    Path(__file__).resolve().parent / ".env",
    Path.cwd() / ".env",
    Path("/home/ubuntu/robux-ugc-advanced/.env"),
]

SQL = ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_items_name_lower_trim "
       "ON items (lower(trim(name)));")


def load_env():
    if os.getenv("DATABASE_URL"):
        return True
    for path in ENV_CANDIDATES:
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip().strip('"')
            if os.getenv("DATABASE_URL"):
                return True
        except Exception:
            continue
    return bool(os.getenv("DATABASE_URL"))


def main():
    load_env()
    try:
        from bot_core import get_db
        conn = get_db()
    except Exception as e:
        print(f"❌ Could not connect to the database: {type(e).__name__}: {e}")
        return 1
    try:
        conn.autocommit = True       # required for CONCURRENTLY
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '300000'")
        cur.execute(SQL)
        cur.close()
        print("✅ Index applied successfully: idx_items_name_lower_trim")
        return 0
    except Exception as e:
        print(f"❌ Index creation failed: {type(e).__name__}: {e}")
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
