import logging
import os
import asyncio
import sqlite3
import re
from datetime import date

import requests
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO downloads (user_id, link, quality, file_path, pixeldrain_url) VALUES (?, ?, ?, ?, ?)",
        (user_id, link, quality, file_path, pixeldrain_url),
    )
    conn.commit()
    conn.close()

def get_cached_download(link, quality):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT file_path, pixeldrain_url FROM downloads WHERE link=? AND quality=? ORDER BY timestamp DESC LIMIT 1",
        (link, quality),
    )
    row = c.fetchone()
    conn.close()
    return row

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

def block_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def unblock_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_blocked(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM blocked_users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def get_blocked_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM blocked_users")
    rows = c.fetchall()
    conn.close()
    return rows
    
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
        link = link.split("&")[0]
        return link

    return None

# -------------------- PIXELDRAIN --------------------

def upload_to_pixeldrain(file_path):
    url = "https://pixeldrain.com/api/file"
    with open(file_path, "rb") as f:
        files = {"file": f}
        r = requests.post(url, files=files)
    if r.status_code == 200:
        file_id = r.json().get("id")
        return f"https://pixeldrain.com/u/{file_id}"
    return None

# -------------------- DOWNLOAD QUEUE --------------------

download_queue = asyncio.Queue()
user_links = {}

async def download_youtube_video(link, quality):
    ydl_opts = {
        "format": f"bestvideo[height={quality}]+bestaudio/best/best",
        "outtmpl": f"%(title)s_{quality}p.%(ext)s",
        "noplaylist": True,
        "merge_output_format": "mp4",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info)
        thumb = info.get("thumbnail")
        return filename, thumb

async def download_youtube_audio(link):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": "%(title)s_audio.%(ext)s",
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
        thumb = info.get("thumbnail")
        return filename, thumb

async def queue_worker():
    while True:
        user_id, link, quality, query = await download_queue.get()

        try:
            await query.edit_message_text("⬇️ در حال دانلود...")

            # کش
            cached = get_cached_download(link, quality)
            if cached:
                file_path, pixeldrain_url = cached
                if pixeldrain_url:
                    await query.message.reply_text(
                        f"✅ این ویدیو قبلاً دانلود شده بود.\nلینک مستقیم:\n{pixeldrain_url}"
                    )
                    download_queue.task_done()
                    continue
                if file_path and os.path.exists(file_path):
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    if size_mb > 48:
                        pix_url = upload_to_pixeldrain(file_path)
                        if pix_url:
                            save_download(user_id, link, str(quality), file_path, pix_url)
                            await query.message.reply_text(
                                f"✅ لینک مستقیم (کش):\n{pix_url}"
                            )
                        else:
                            await query.message.reply_document(open(file_path, "rb"))
                    else:
                        await query.message.reply_document(open(file_path, "rb"))
                    download_queue.task_done()
                    continue

            # دانلود جدید
            if quality == "audio":
                filename, thumb = await download_youtube_audio(link)
            else:
                filename, thumb = await download_youtube_video(link, int(quality))

            size_mb = os.path.getsize(filename) / (1024 * 1024)

            if thumb:
                try:
                    await query.message.reply_photo(thumb)
                except:
                    pass

            pixeldrain_url = None

            if size_mb > 48:
                await query.message.reply_text(
                    f"⚠️ حجم فایل {int(size_mb)}MB است، روی Pixeldrain آپلود می‌شود..."
                )
                pixeldrain_url = upload_to_pixeldrain(filename)
                if pixeldrain_url:
                    await query.message.reply_text(
                        f"✅ لینک مستقیم:\n{pixeldrain_url}"
                    )
                else:
                    await query.message.reply_document(open(filename, "rb"))
            else:
                if quality == "audio":
                    await query.message.reply_document(
                        document=open(filename, "rb"),
                        caption=f"✅ فایل صوتی آماده شد!"
                    )
                else:
                    await query.message.reply_document(
                        document=open(filename, "rb"),
                        caption=f"✅ ویدیو {quality}p آماده شد!"
                    )

            save_download(user_id, link, str(quality), filename, pixeldrain_url)

        except Exception as e:
            await query.message.reply_text(f"❌ خطا: {e}")

        download_queue.task_done()

# -------------------- HANDLERS --------------------
if is_blocked(update.effective_user.id):
    await update.message.reply_text("❌ دسترسی شما توسط ادمین مسدود شده است.")
    return

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
        msg += f"{quality} | {ts}\n{link}\n\n"

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

    await update.message.reply_text(
        f"🛠 پنل ادمین\n"
        f"تعداد کل دانلودها: {total}\n"
        f"کاربران روزانه محدود: ۱۵\n"
        f"ادمین: نامحدود"
    )

async def blocked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    rows = get_blocked_users()
    if not rows:
        await update.message.reply_text("هیچ کاربری بلاک نشده است.")
        return

    msg = "🚫 کاربران بلاک‌شده:\n\n"
    for (uid,) in rows:
        msg += f"- {uid}\n"

    await update.message.reply_text(msg)

async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("استفاده: /unblock <user_id>")
        return

    uid = int(context.args[0])
    unblock_user(uid)
    await update.message.reply_text(f"✅ کاربر {uid} آن‌بلاک شد.")

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("استفاده: /block <user_id>")
        return

    uid = int(context.args[0])
    block_user(uid)
    await update.message.reply_text(f"🚫 کاربر {uid} بلاک شد.")

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
            InlineKeyboardButton("4K", callback_data="q_2160"),
            InlineKeyboardButton("🎧 Audio", callback_data="q_audio"),
        ],
        [
            InlineKeyboardButton("❌ لغو", callback_data="cancel")
        ]
    ]

    await update.message.reply_text(
        "کیفیت را انتخاب کن:",
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
        q = query.data.replace("q_", "")
        quality = "audio" if q == "audio" else q

        await query.edit_message_text(f"⏳ در صف دانلود... ({quality})")

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
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("blocked", blocked_list))
    
    port = int(os.environ.get("PORT", 8080))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
