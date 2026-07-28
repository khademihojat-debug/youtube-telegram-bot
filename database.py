import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "./data/data.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            daily_count INTEGER DEFAULT 0,
            last_reset TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            quality TEXT,
            filename TEXT,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_daily_count(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT daily_count, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        count, last_reset = row
        if last_reset != today:
            c.execute("UPDATE users SET daily_count = 0, last_reset = ? WHERE user_id = ?", (today, user_id))
            conn.commit()
            count = 0
        conn.close()
        return count
    else:
        c.execute("INSERT INTO users (user_id, daily_count, last_reset) VALUES (?, 0, ?)", (user_id, today))
        conn.commit()
        conn.close()
        return 0

def increment_daily_count(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("UPDATE users SET daily_count = daily_count + 1, last_reset = ? WHERE user_id = ?", (today, user_id))
    conn.commit()
    conn.close()

def save_history(user_id: int, link: str, quality: str, filename: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("INSERT INTO history (user_id, link, quality, filename, date) VALUES (?, ?, ?, ?, ?)",
              (user_id, link, quality, filename, now))
    conn.commit()
    conn.close()
