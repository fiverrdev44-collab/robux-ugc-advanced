"""One-time Phase 3 migration runner.

Reads migrations/2026-11-02_astra_outcomes.sql and applies it inside a
transaction. Safe to re-run (all statements are IF NOT EXISTS).

Usage: python apply_phase3_migration.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SQL_PATH = ROOT / "migrations" / "2026-11-02_astra_outcomes.sql"
ENV_CANDIDATES = [
    ROOT / ".env",
    Path.cwd() / ".env",
    Path("/home/ubuntu/robux-ugc-advanced/.env"),
]


def load_env():
    """Populate os.environ from the bot's .env without printing any values."""
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
    if not SQL_PATH.exists():
        print(f"❌ Migration file not found: {SQL_PATH}")
        return 1
    sql = SQL_PATH.read_text(encoding="utf-8")
    if not sql.strip():
        print("❌ Migration file is empty.")
        return 1

    load_env()
    try:
        from bot_core import get_db
        conn = get_db()
    except Exception as e:
        print(f"❌ Could not connect to the database: {type(e).__name__}: {e}")
        return 1

    try:
        with conn:                      # commits on success, rolls back on error
            cur = conn.cursor()
            try:
                cur.execute(sql)
            finally:
                cur.close()
        print("✅ Migration applied successfully!")
        return 0
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"❌ Migration failed: {type(e).__name__}: {e}")
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
