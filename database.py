import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    """Get a DB connection with a hard 10-second timeout."""
    return psycopg2.connect(
        DATABASE_URL,
        sslmode='require',
        connect_timeout=10,
    )


def _safe_exec(cur, sql, label=""):
    """Run one CREATE statement. Rollback on failure, never crash the bot."""
    try:
        cur.execute(sql)
    except Exception as e:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        print(f"⚠️ [setup] {label or 'stmt'} failed: {type(e).__name__}: {str(e)[:200]}", flush=True)


def setup_database():
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"❌ [setup] DB connection failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return

    cur = conn.cursor()

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS discovered_items (
            id BIGINT PRIMARY KEY
        );
    ''', "discovered_items")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS items (
            id BIGINT PRIMARY KEY,
            name TEXT,
            favorite_count INTEGER,
            price INTEGER,
            total_sales INTEGER,
            description TEXT,
            creator_name TEXT,
            asset_type_id INTEGER,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''', "items")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS item_history (
            id SERIAL PRIMARY KEY,
            item_id BIGINT,
            favorite_count INTEGER,
            total_sales INTEGER,
            price INTEGER,
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''', "item_history")

    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_item_history_item_id 
        ON item_history (item_id);
    ''', "idx_item_history_item_id")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS search_suggestions (
            id SERIAL PRIMARY KEY,
            seed_keyword TEXT,
            suggestion TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''', "search_suggestions")

    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_search_suggestions_suggestion 
        ON search_suggestions (suggestion);
    ''', "idx_search_suggestions_suggestion")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS learned_keywords (
            id SERIAL PRIMARY KEY,
            keyword TEXT UNIQUE,
            score DOUBLE PRECISION,
            avg_favorites DOUBLE PRECISION,
            avg_sales DOUBLE PRECISION,
            item_count INTEGER,
            learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''', "learned_keywords")

    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_learned_keywords_score 
        ON learned_keywords (score DESC);
    ''', "idx_learned_keywords_score")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS user_profiles (
            discord_id BIGINT PRIMARY KEY,
            username TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_consultations INTEGER DEFAULT 0,
            notes TEXT
        );
    ''', "user_profiles")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS saved_consultations (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT,
            seed TEXT,
            verdict_label TEXT,
            verdict_emoji TEXT,
            full_report TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''', "saved_consultations")

    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_saved_consult_discord 
        ON saved_consultations (discord_id);
    ''', "idx_saved_consult_discord")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT,
            keyword TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            baseline_favs INTEGER DEFAULT 0,
            last_checked TIMESTAMP,
            alert_sent BOOLEAN DEFAULT FALSE,
            UNIQUE(discord_id, keyword)
        );
    ''', "watchlist")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS competitor_tracking (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT,
            creator_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(discord_id, creator_name)
        );
    ''', "competitor_tracking")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS item_tracker (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT,
            item_id BIGINT,
            item_name TEXT,
            claimed_keywords TEXT,
            claimed_price INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(discord_id, item_id)
        );
    ''', "item_tracker")

    try:
        conn.commit()
    except Exception as e:
        print(f"⚠️ [setup] commit failed: {e}", flush=True)

    try:
        cur.close()
        conn.close()
    except Exception:
        pass

    print("✅ Database setup complete (non-fatal).", flush=True)


if __name__ == "__main__":
    setup_database()
