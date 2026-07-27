import asyncio
import logging
import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

import requests
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# -------------------- CONFIG --------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_PATH = "data.db"
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_DAILY_DOWNLOADS = 15
TELEGRAM_FILE_LIMIT_MB = 48

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_id INTEGER PRIMARY KEY
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            quality TEXT,
            file_path TEXT,
            pixeldrain_url TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS limits (
            user_id INTEGER,
            day TEXT,
            count INTEGER,
            PRIMARY KEY (user_id, day)
        )
        """
    )

    conn.commit()
    conn.close()


def save_download(
    user_id: int,
    link: str,
    quality: str,
    file_path: Optional[str] = None,
    pixeldrain_url: Optional[str] = None,
):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO downloads (user_id, link, quality, file_path, pixeldrain_url)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, link, quality, file_path, pixeldrain_url),
    )
    conn.commit()
    conn.close()


def get_cached_download(link: str, quality: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT file_path, pixeldrain_url
        FROM downloads
        WHERE link=? AND quality=?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (link, quality),
    )
    row = c.fetchone()
    conn.close()
    return row


def get_user_history(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT link, quality, timestamp
        FROM downloads
        WHERE user_id=?
        ORDER BY timestamp DESC
        LIMIT 10
        """,
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def increment_limit(user_id: int, max_per_day: int = MAX_DAILY_DOWNLOADS) -> bool:
    today = date.today().isoformat()
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        "SELECT count FROM limits WHERE user_id=? AND day=?",
        (user_id, today),
    )
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


def block_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)",
        (user_id,),
    )
    conn.commit()
    conn.close()


def unblock_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def is_blocked(user_id: int) -> bool:
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


def get_total_downloads() -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM downloads")
    total = c.fetchone()[0]
    conn.close()
    return total


# -------------------- LINK EXTRACTION --------------------


def extract_youtube_link(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    pattern = r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s]+)"
    match = re.search(pattern, text)

    if not match:
        return None

    link = match.group(1).strip()

    # حذف پارامترهای اضافی متداول
    if "youtu.be/" in link:
        return link.split("?")[0]

    if "&" in link:
        link = link.split("&")[0]

    return link


# -------------------- PIXELDRAIN --------------------


def upload_to_pixeldrain(file_path: str) -> Optional[str]:
    url = "https://pixeldrain.com/api/file"
    try:
        with open(file_path, "rb") as f:
            response = requests.post(url, files={"file": f}, timeout=300)

        if response.status_code == 200:
            file_id = response.json().get("id")
            if file_id:
                return f"https://pixeldrain.com/u/{file_id}"
    except Exception as e:
        logger.exception("Pixeldrain upload failed: %s", e)

    return None


# -------------------- DOWNLOAD HELPERS --------------------


def resolve_final_path(prepared_filename: str, expected_ext: str) -> str:
    path = Path(prepared_filename)
    if path.suffix.lower() == f".{expected_ext.lower()}" and path.exists():
        return str(path)

    candidate = path.with_suffix(f".{expected_ext}")
    if candidate.exists():
        return str(candidate)

    return str(path)


def _download_youtube_video_sync(link: str, quality: int) -> Tuple[str, Optional[str]]:
    outtmpl = str(DOWNLOAD_DIR / f"%(title).180B_%(id)s_{quality}p.%(ext)s")

    ydl_opts = {
        "format": f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "quiet": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        prepared = ydl.prepare_filename(info)
        final_path = resolve_final_path(prepared, "mp4")
        thumb = info.get("thumbnail")
        return final_path, thumb


def _download_youtube_audio_sync(link: str, bitrate: str) -> Tuple[str, Optional[str]]:
    outtmpl = str(DOWNLOAD_DIR / f"audio_%(title).180B_%(id)s_{bitrate}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        prepared = ydl.prepare_filename(info)
        final_path = resolve_final_path(prepared, "mp3")
        thumb = info.get("thumbnail")
        return final_path, thumb


async def download_youtube_video(link: str, quality: int) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_youtube_video_sync, link, quality)


async def download_youtube_audio(link: str, bitrate: str) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_youtube_audio_sync, link, bitrate)

async def download_youtube_audio(link, bitrate):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"audio_%(id)s_{bitrate}.%(ext)s",
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            },
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
        thumb = info.get("thumbnail")
        return filename, thumb


def get_quality_caption(quality: str) -> str:
    if quality == "a128":
        return "✅ فایل صوتی 128kbps آماده شد!"
    if quality == "a320":
        return "✅ فایل صوتی 320kbps آماده شد!"
    return f"✅ ویدیو {quality}p آماده شد!"


# -------------------- DOWNLOAD QUEUE --------------------

download_queue: asyncio.Queue = asyncio.Queue()
user_links = {}


async def send_file_or_link(query, file_path: str, quality: str) -> Optional[str]:
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > TELEGRAM_FILE_LIMIT_MB:
        await query.message.reply_text(
            f"⚠️ حجم فایل {int(size_mb)}MB است، روی Pixeldrain آپلود می‌شود..."
        )
        pixeldrain_url = await asyncio.to_thread(upload_to_pixeldrain, file_path)

        if pixeldrain_url:
            await query.message.reply_text(f"✅ لینک مستقیم:\n{pixeldrain_url}")
            return pixeldrain_url

        await query.message.reply_document(
            document=open(file_path, "rb"),
            caption=get_quality_caption(quality),
        )
        return None

    await query.message.reply_document(
        document=open(file_path, "rb"),
        caption=get_quality_caption(quality),
    )
    return None


async def queue_worker():
    while True:
        user_id, link, quality, query = await download_queue.get()

        try:
            await query.edit_message_text("⬇️ در حال دانلود...")

            cached = get_cached_download(link, quality)
            if cached:
                file_path, pixeldrain_url = cached

                if pixeldrain_url:
                    await query.message.reply_text(
                        "✅ این فایل قبلاً دانلود شده بود.\n"
                        f"لینک مستقیم:\n{pixeldrain_url}"
                    )
                    continue

                if file_path and os.path.exists(file_path):
                    cached_size_mb = os.path.getsize(file_path) / (1024 * 1024)

                    if cached_size_mb > TELEGRAM_FILE_LIMIT_MB:
                        pix_url = await asyncio.to_thread(upload_to_pixeldrain, file_path)
                        if pix_url:
                            save_download(user_id, link, quality, file_path, pix_url)
                            await query.message.reply_text(
                                f"✅ لینک مستقیم (کش):\n{pix_url}"
                            )
                        else:
                            await query.message.reply_document(
                                document=open(file_path, "rb"),
                                caption=get_quality_caption(quality),
                            )
                    else:
                        await query.message.reply_document(
                            document=open(file_path, "rb"),
                            caption=get_quality_caption(quality),
                        )
                    continue

            if quality == "a128":
                filename, thumb = await download_youtube_audio(link, "128")
            elif quality == "a320":
                filename, thumb = await download_youtube_audio(link, "320")
            else:
                filename, thumb = await download_youtube_video(link, int(quality))

            if thumb:
                try:
                    await query.message.reply_photo(thumb)
                except Exception:
                    logger.warning("Could not send thumbnail", exc_info=True)

            pixeldrain_url = await send_file_or_link(query, filename, quality)
            save_download(user_id, link, quality, filename, pixeldrain_url)

        except Exception as e:
            logger.exception("Download worker error: %s", e)
            await query.message.reply_text(f"❌ خطا: {e}")

        finally:
            download_queue.task_done()


# -------------------- HANDLERS --------------------


def build_quality_keyboard() -> InlineKeyboardMarkup:
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
    ],
    [
    InlineKeyboardButton("🎧 128kbps", callback_data="q_a128"),
    InlineKeyboardButton("🎧 320kbps", callback_data="q_a320"),
    ],
    [
        InlineKeyboardButton("❌ لغو", callback_data="cancel")
    ]
]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! لینک یوتیوب را ارسال کن تا دانلود کنم.")


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

    total = get_total_downloads()
    await update.message.reply_text(
        f"🛠 پنل ادمین\n"
        f"تعداد کل دانلودها: {total}\n"
        f"کاربران روزانه محدود: {MAX_DAILY_DOWNLOADS}\n"
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


async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("استفاده: /block <user_id>")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id باید عدد باشد.")
        return

    block_user(uid)
    await update.message.reply_text(f"🚫 کاربر {uid} بلاک شد.")


async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("استفاده: /unblock <user_id>")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id باید عدد باشد.")
        return

    unblock_user(uid)
    await update.message.reply_text(f"✅ کاربر {uid} آن‌بلاک شد.")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    link = extract_youtube_link(text)

    if not link:
        await update.message.reply_text("❌ لطفاً لینک یوتیوب بفرست.")
        return

    user_id = update.effective_user.id

    if is_blocked(user_id):
        await update.message.reply_text("❌ دسترسی شما توسط ادمین مسدود شده است.")
        return

    if user_id != ADMIN_ID and not increment_limit(user_id):
        await update.message.reply_text(
            f"⚠️ محدودیت روزانه‌ات تمام شده ({MAX_DAILY_DOWNLOADS} تا)."
        )
        return

    user_links[user_id] = link

    await update.message.reply_text(
        "کیفیت را انتخاب کن:",
        reply_markup=build_quality_keyboard(),
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
        await query.edit_message_text("❌ لینک پیدا نشد. دوباره لینک را بفرست.")
        return

   if query.data == "q_a128":
    await query.edit_message_text("⏳ در صف دانلود ... (128kbps)")
    await download_queue.put((user_id, link, "a128", query))
    return

if query.data == "q_a320":
    await query.edit_message_text("⏳ در صف دانلود ... (320kbps)")
    await download_queue.put((user_id, link, "a320", query))
    return

        await query.edit_message_text(f"⏳ در صف دانلود ... ({q}p)")
        await download_queue.put((user_id, link, q, query))
        return

    await query.edit_message_text("❌ گزینه نامعتبر است.")


# -------------------- POST INIT --------------------


async def post_init(app: Application):
    app.bot_data["queue_worker"] = asyncio.create_task(queue_worker())


# -------------------- MAIN --------------------


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL is not set")

    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("blocked", blocked_list))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    port = int(os.environ.get("PORT", 8080))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )


if __name__ == "__main__":
    main()
