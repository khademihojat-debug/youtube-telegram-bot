import sqlite3
from datetime import date
from config import DB_PATH, MAX_DAILY_DOWNLOADS

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_id INTEGER PRIMARY KEY
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            quality TEXT,
            file_path TEXT,
            pixeldrain_url TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS limits (
            user_id INTEGER,
            day TEXT,
            count INTEGER,
            PRIMARY KEY (user_id, day)
        )
    """)

    conn.commit()
    conn.close()

def save_download(user_id, link, quality, file_path=None, pixeldrain_url=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO downloads (user_id, link, quality, file_path, pixeldrain_url)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, link, quality, file_path, pixeldrain_url))
    conn.commit()
    conn.close()

def get_cached_download(link, quality):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT file_path, pixeldrain_url
        FROM downloads
        WHERE link=? AND quality=?
        ORDER BY timestamp DESC
        LIMIT 1
    """, (link, quality))
    row = c.fetchone()
    conn.close()
    return row

def get_user_history(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT link, quality, timestamp
        FROM downloads
        WHERE user_id=?
        ORDER BY timestamp DESC
        LIMIT 10
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def increment_limit(user_id, max_per_day=MAX_DAILY_DOWNLOADS):
    today = date.today().isoformat()
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT count FROM limits WHERE user_id=? AND day=?", (user_id, today))
    row = c.fetchone()

    if row is None:
        c.execute("INSERT INTO limits (user_id, day, count) VALUES (?, ?, ?)",
                  (user_id, today, 1))
        conn.commit()
        conn.close()
        return True

    count = row[0]
    if count >= max_per_day:
        conn.close()
        return False

    c.execute("UPDATE limits SET count=? WHERE user_id=? AND day=?",
              (count + 1, user_id, today))
    conn.commit()
    conn.close()
    return True

def block_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def unblock_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_blocked(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM blocked_users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def get_blocked_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM blocked_users ORDER BY user_id DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_total_downloads():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM downloads")
    total = c.fetchone()[0]
    conn.close()
    return total
