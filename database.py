import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def setup_database():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS discovered_items (
            id BIGINT PRIMARY KEY
        );
    ''')

    cur.execute('''
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
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS item_history (
            id SERIAL PRIMARY KEY,
            item_id BIGINT,
            favorite_count INTEGER,
            total_sales INTEGER,
            price INTEGER,
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    cur.execute('''
        CREATE INDEX IF NOT EXISTS idx_item_history_item_id 
        ON item_history (item_id);
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS search_suggestions (
            id SERIAL PRIMARY KEY,
            seed_keyword TEXT,
            suggestion TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    cur.execute('''
        CREATE INDEX IF NOT EXISTS idx_search_suggestions_suggestion 
        ON search_suggestions (suggestion);
    ''')

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database tables ready.")
