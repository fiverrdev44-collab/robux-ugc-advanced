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
    conn.commit()
    cur.close()
    conn.close()
