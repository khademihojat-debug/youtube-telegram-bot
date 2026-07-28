import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "./data/data.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_connection():
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            daily_count INTEGER DEFAULT 0,
            last_reset TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            quality TEXT,
            filename TEXT,
            date TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def ensure_user_row(cursor, user_id: int, today: str):
    cursor.execute(
        "SELECT daily_count, last_reset FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, daily_count, last_reset) VALUES (?, 0, ?)",
            (user_id, today),
        )
        return 0

    count, last_reset = row

    if last_reset != today:
        cursor.execute(
            "UPDATE users SET daily_count = 0, last_reset = ? WHERE user_id = ?",
            (today, user_id),
        )
        return 0

    return count


def get_daily_count(user_id: int) -> int:
    conn = get_connection()
    c = conn.cursor()
    today = get_today()

    count = ensure_user_row(c, user_id, today)

    conn.commit()
    conn.close()
    return count


def try_acquire_download_slot(user_id: int, max_daily: int):
    conn = get_connection()
    c = conn.cursor()
    today = get_today()

    try:
        c.execute("BEGIN IMMEDIATE")
        count = ensure_user_row(c, user_id, today)

        if count >= max_daily:
            conn.commit()
            return False, count

        c.execute(
            "UPDATE users SET daily_count = daily_count + 1, last_reset = ? WHERE user_id = ?",
            (today, user_id),
        )
        conn.commit()
        return True, count + 1

    finally:
        conn.close()


def release_download_slot(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    today = get_today()

    c.execute(
        """
        UPDATE users
        SET daily_count = CASE
            WHEN daily_count > 0 THEN daily_count - 1
            ELSE 0
        END,
        last_reset = ?
        WHERE user_id = ?
        """,
        (today, user_id),
    )

    conn.commit()
    conn.close()


def save_history(user_id: int, link: str, quality: str, filename: str):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute(
        "INSERT INTO history (user_id, link, quality, filename, date) VALUES (?, ?, ?, ?, ?)",
        (user_id, link, quality, filename, now),
    )

    conn.commit()
    conn.close()
