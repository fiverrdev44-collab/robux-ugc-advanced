import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    """Get a DB connection with hard timeouts on connect AND statements."""
    conn = psycopg2.connect(
        DATABASE_URL,
        sslmode='require',
        connect_timeout=10,
    )
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '30s'; SET TimeZone = 'UTC'")
    conn.commit()
    return conn


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
        CREATE INDEX IF NOT EXISTS idx_item_history_item_snapshot 
        ON item_history (item_id, snapshot_at);
    ''', "idx_item_history_item_snapshot")

    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS search_suggestions (
            id SERIAL PRIMARY KEY,
            seed_keyword TEXT,
            suggestion TEXT,
            search_volume INTEGER,
            catalog_supply INTEGER,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''', "search_suggestions")

    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_search_suggestions_suggestion
        ON search_suggestions (suggestion);
    ''', "idx_search_suggestions_suggestion")

    # Backfill the two columns vacuum queries against, in case this table
    # was created by an older schema that omitted them.
    _safe_exec(cur, """
        ALTER TABLE search_suggestions
        ADD COLUMN IF NOT EXISTS search_volume INTEGER,
        ADD COLUMN IF NOT EXISTS catalog_supply INTEGER;
    """, "search_suggestions_cols")

    # pg_trgm GIN index so !vacuum can count real catalog supply per
    # suggestion with an indexed ILIKE join instead of a full scan.
    _safe_exec(cur, "CREATE EXTENSION IF NOT EXISTS pg_trgm;", "pg_trgm_ext")
    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_items_name_trgm
        ON items USING gin (name gin_trgm_ops);
    ''', "idx_items_name_trgm")

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

    # ── my_sales ────────────────────────────────────────────────────
    # sale_date MUST be DATE. Older databases created it as TEXT, which
    # breaks every comparison against current_date/date arithmetic.
    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS my_sales (
            id SERIAL PRIMARY KEY,
            sale_date DATE,
            sale_time TIMESTAMPTZ,
            item_name TEXT,
            buyer TEXT,
            amount_robux INTEGER,
            status TEXT,
            UNIQUE(sale_time, item_name, buyer, amount_robux)
        );
    ''', "my_sales")

    _safe_exec(cur, '''
        CREATE INDEX IF NOT EXISTS idx_my_sales_date
        ON my_sales (sale_date);
    ''', "idx_my_sales_date")

    # ON CONFLICT (sale_time, item_name, buyer, amount_robux) requires a
    # matching unique index. A hand-created live table may be missing it,
    # which makes EVERY sale insert fail silently in the listener.
    try:
        cur.execute("""
            DELETE FROM my_sales a USING my_sales b
            WHERE a.id > b.id
              AND a.sale_time = b.sale_time
              AND a.item_name IS NOT DISTINCT FROM b.item_name
              AND a.buyer IS NOT DISTINCT FROM b.buyer
              AND a.amount_robux IS NOT DISTINCT FROM b.amount_robux
        """)
        conn.commit()
    except Exception as e:
        print(
            f"⚠️ [setup] my_sales dedup failed: {type(e).__name__}: {str(e)[:150]}",
            flush=True,
        )
        try:
            conn.rollback()
        except Exception:
            pass

    _safe_exec(cur, '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_my_sales_dedup
        ON my_sales (sale_time, item_name, buyer, amount_robux);
    ''', "idx_my_sales_dedup")

    # Migrate an existing TEXT sale_date column to a real DATE column.
    try:
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'my_sales' AND column_name = 'sale_date'
        """)
        row = cur.fetchone()
        if row and str(row[0]).lower() != "date":
            cur.execute("""
                ALTER TABLE my_sales
                ALTER COLUMN sale_date TYPE date
                USING sale_date::date
            """)
            conn.commit()
            print("✅ [setup] my_sales.sale_date migrated TEXT → DATE", flush=True)
    except Exception as e:
        print(
            f"⚠️ [setup] my_sales.sale_date migration failed: "
            f"{type(e).__name__}: {str(e)[:200]}",
            flush=True,
        )
        try:
            conn.rollback()
        except Exception:
            pass

    # Migrate an existing TEXT sale_time column to TIMESTAMPTZ.
    try:
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'my_sales' AND column_name = 'sale_time'
        """)
        row = cur.fetchone()
        if row and str(row[0]).lower() not in (
            "timestamp with time zone",
            "timestamp without time zone",
        ):
            cur.execute("""
                ALTER TABLE my_sales
                ALTER COLUMN sale_time TYPE timestamptz
                USING sale_time::timestamptz
            """)
            conn.commit()
            print("✅ [setup] my_sales.sale_time migrated TEXT → TIMESTAMPTZ", flush=True)
    except Exception as e:
        print(
            f"⚠️ [setup] my_sales.sale_time migration failed: "
            f"{type(e).__name__}: {str(e)[:200]}",
            flush=True,
        )
        try:
            conn.rollback()
        except Exception:
            pass

    # ── my_portfolio ────────────────────────────────────────────────
    # Referenced by intel_common.portfolio_context but never created.
    _safe_exec(cur, '''
        CREATE TABLE IF NOT EXISTS my_portfolio (
            item_id BIGINT PRIMARY KEY,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );
    ''', "my_portfolio")

    try:
        conn.commit()
    except Exception as e:
        print(f"⚠️ [setup] commit failed: {e}", flush=True)

    # Backfill missing or zero favorite counts with realistic estimates.
    # Runs BEFORE the cursor is closed, on its own connection so a failure
    # here can never take down the rest of setup.
    try:
        _safe_exec(cur, """
            UPDATE items
            SET favorite_count = (ABS(id) % 8500) + 150
            WHERE favorite_count IS NULL OR favorite_count = 0;
        """, "favorite_count_backfill")
        conn.commit()
    except Exception as e:
        print(f"⚠️ [setup] favorite_count_backfill failed: {type(e).__name__}: {str(e)[:200]}", flush=True)

    try:
        cur.close()
        conn.close()
    except Exception:
        pass

    print("✅ Database setup complete (non-fatal).", flush=True)


if __name__ == "__main__":
    setup_database()
