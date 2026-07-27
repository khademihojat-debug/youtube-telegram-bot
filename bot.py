import logging
import os
import asyncio
import sqlite3
import re
from datetime import date

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

DB_PATH = "data.db"

# -------------------- DATABASE --------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            quality TEXT,
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

def save_download(user_id, link, quality):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO downloads (user_id, link, quality) VALUES (?, ?, ?)",
        (user_id, link, quality),
    )
    conn.commit()
    conn.close()

def get_user_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT link, quality, timestamp FROM downloads WHERE user_id=? ORDER BY timestamp DESC LIMIT 10",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows

def increment_limit(user_id, max_per_day=15):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT count FROM limits WHERE user_id=? AND day=?", (user_id, today))
    row = c.fetchone()

    if row is None:
        c.execute(
            "INSERT INTO limits (user_id, day, count) VALUES (?, ?, ?)",
            (user_id, today, 1),
        )
        conn.commit()
        conn.close()
        return True

    count = row[0]
    if count >= max_per_day:
        conn.close()
        return False

    c.execute(
        "UPDATE limits SET count=? WHERE user_id=? AND day=?",
        (count + 1, user_id, today),
    )
    conn.commit()
    conn.close()
    return True

# -------------------- LINK EXTRACTION --------------------

def extract_youtube_link(text):
    if not text:
        return None

    pattern = r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s]+)"
    match = re.search(pattern, text)

    if match:
        link = match.group(1)
        link = link.split("?")[0]
        return link

    return None

# -------------------- DOWNLOAD QUEUE --------------------

download_queue = asyncio.Queue()
user_links = {}

async def download_youtube(link, quality):
    ydl_opts = {
        "format": f"bestvideo[height={quality}]+bestaudio/best",
        "outtmpl": "%(title)s_" + str(quality) + "p.%(ext)s",
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info)
        thumb = info.get("thumbnail")
        return filename, thumb

async def queue_worker():
    while True:
        user_id, link, quality, query = await download_queue.get()

        try:
            await query.edit_message_text("⬇️ در حال دانلود...")

            filename, thumb = await download_youtube(link, quality)

            size_mb = os.path.getsize(filename) / (1024 * 1024)

            if thumb:
                try:
                    await query.message.reply_photo(thumb)
                except:
                    pass

            if size_mb > 48:
                await query.message.reply_text(
                    f"⚠️ حجم فایل {int(size_mb)}MB است و از محدودیت تلگرام بیشتر است."
                )
                await query.message.reply_document(open(filename, "rb"))
            else:
                await query.message.reply_document(
                    document=open(filename, "rb"),
                    caption=f"✅ ویدیو {quality}p آماده شد!"
                )

        except Exception as e:
            await query.message.reply_text(f"❌ خطا: {e}")

        download_queue.task_done()

# -------------------- HANDLERS --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لینک یوتیوب را ارسال کن.")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = get_user_history(user_id)

    if not rows:
        await update.message.reply_text("📭 هنوز دانلودی انجام نداده‌ای.")
        return

    msg = "📜 آخرین دانلودهای تو:\n\n"
    for link, quality, ts in rows:
        msg += f"{quality}p | {ts}\n{link}\n\n"

    await update.message.reply_text(msg)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM downloads")
    total = c.fetchone()[0]
    conn.close()

    await update.message.reply_text(f"🛠 پنل ادمین\nتعداد دانلودها: {total}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    link = extract_youtube_link(text)

    if not link:
        await update.message.reply_text("❌ لطفاً لینک یوتیوب بفرست.")
        return

    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        if not increment_limit(user_id):
            await update.message.reply_text("⚠️ محدودیت روزانه‌ات تمام شده (۱۵ تا).")
            return

    user_links[user_id] = link

    keyboard = [
        [
            InlineKeyboardButton("360p", callback_data="q_360"),
            InlineKeyboardButton("480p", callback_data="q_480"),
        ],
        [
            InlineKeyboardButton("720p", callback_data="q_720"),
            InlineKeyboardButton("1080p", callback_data="q_1080"),
        ],
        [
            InlineKeyboardButton("❌ لغو", callback_data="cancel")
        ]
    ]

    await update.message.reply_text(
        "کیفیت ویدیو را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    link = user_links.get(user_id)

    if query.data == "cancel":
        await query.edit_message_text("❌ لغو شد.")
        return

    if not link:
        await query.edit_message_text("❌ لینک پیدا نشد.")
        return

    if query.data.startswith("q_"):
        quality = int(query.data.replace("q_", ""))

        save_download(user_id, link, str(quality))

        await query.edit_message_text(f"⏳ در صف دانلود... ({quality}p)")

        await download_queue.put((user_id, link, quality, query))

# -------------------- POST INIT --------------------

async def post_init(app):
    asyncio.create_task(queue_worker())

# -------------------- MAIN --------------------

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT, message_handler))

    port = int(os.environ.get("PORT", 8080))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
