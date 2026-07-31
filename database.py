import sqlite3
import os
from datetime import datetime, timedelta

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
            last_reset TEXT,
            vip_until TEXT
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

    # اگه دیتابیس قدیمی‌تر بدون ستون vip_until باشه، اضافه‌اش می‌کنیم
    c.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in c.fetchall()]
    if "vip_until" not in columns:
        c.execute("ALTER TABLE users ADD COLUMN vip_until TEXT")

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


# ========== VIP ==========

def is_vip(user_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT vip_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()

    if row is None or row[0] is None:
        return False

    try:
        vip_until = datetime.fromisoformat(row[0])
    except ValueError:
        return False

    return datetime.now() < vip_until


def get_vip_expiry(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT vip_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()

    if row is None or row[0] is None:
        return None

    try:
        return datetime.fromisoformat(row[0])
    except ValueError:
        return None


def grant_vip(user_id: int, days: int):
    """VIP رو از الان یا از تاریخ انقضای فعلی (هرکدوم دیرتره) به مدت `days` روز تمدید می‌کنه."""
    conn = get_connection()
    c = conn.cursor()
    today = get_today()

    c.execute(
        "SELECT vip_until FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = c.fetchone()

    now = datetime.now()
    current_expiry = None
    if row and row[0]:
        try:
            current_expiry = datetime.fromisoformat(row[0])
        except ValueError:
            current_expiry = None

    base = current_expiry if (current_expiry and current_expiry > now) else now
    new_expiry = base + timedelta(days=days)

    if row is None:
        c.execute(
            "INSERT INTO users (user_id, daily_count, last_reset, vip_until) VALUES (?, 0, ?, ?)",
            (user_id, today, new_expiry.isoformat()),
        )
    else:
        c.execute(
            "UPDATE users SET vip_until = ? WHERE user_id = ?",
            (new_expiry.isoformat(), user_id),
        )

    conn.commit()
    conn.close()
    return new_expiry
