import asyncio
import logging
import re
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    ADMIN_ID,
    BOT_MODE,
    BOT_TOKEN,
    DB_PATH,
    DOWNLOAD_DIR,
    MAX_DAILY_DOWNLOADS,
    PORT,
    STORAGE_DIR,
    WEBHOOK_URL,
)
from database import (
    block_user,
    get_blocked_users,
    get_cached_download,
    get_total_downloads,
    get_user_history,
    increment_limit,
    init_db,
    is_blocked,
    save_download,
    unblock_user,
)
from downloader import (
    download_audio,
    download_video,
    get_available_qualities,
    send_file_or_link,
)
from keyboards import build_quality_keyboard


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


download_queue: asyncio.Queue = asyncio.Queue()
user_links: dict[int, str] = {}


def extract_youtube_link(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    pattern = (
        r"(https?://(?:www\.|m\.|music\.)?"
        r"(?:youtube\.com|youtu\.be)[^\s]+)"
    )
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


async def queue_worker():
    while True:
        try:
            user_id, link, quality, query = await download_queue.get()
        except asyncio.CancelledError:
            logger.info("queue_worker cancelled while waiting for next job")
            break

        try:
            await query.edit_message_text("⬇️ در حال دانلود...")

            cached = get_cached_download(link, quality)
            if cached:
                file_path, cached_url = cached

                if cached_url:
                    await query.message.reply_text(
                        "✅ این فایل قبلاً دانلود شده بود.\n"
                        f"لینک مستقیم:\n{cached_url}"
                    )
                    continue

                if file_path:
                    try:
                        cached_link = await send_file_or_link(
                            query.message,
                            file_path,
                            quality,
                        )
                        if cached_link:
                            save_download(
                                user_id,
                                link,
                                quality,
                                file_path,
                                cached_link,
                            )
                        continue
                    except FileNotFoundError:
                        logger.warning(
                            "Cached file no longer exists: %s",
                            file_path,
                        )

            if quality == "a128":
                filename, thumb = await download_audio(link, "128")
            elif quality == "a320":
                filename, thumb = await download_audio(link, "320")
            else:
                filename, thumb = await download_video(link, int(quality))

            if thumb:
                try:
                    await query.message.reply_photo(thumb)
                except Exception:
                    logger.warning("Could not send thumbnail", exc_info=True)

            direct_url = await send_file_or_link(query.message, filename, quality)
            save_download(user_id, link, quality, filename, direct_url)

        except asyncio.CancelledError:
            logger.info("queue_worker cancelled during job processing")
            raise
        except Exception as exc:
            logger.exception("Download worker error: %s", exc)
            try:
                await query.message.reply_text(f"❌ خطا: {exc}")
            except Exception:
                logger.warning(
                    "Could not send error message to user",
                    exc_info=True,
                )
        finally:
            download_queue.task_done()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "سلام! لینک یوتیوب را بفرست تا دانلود کنم."
        )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    rows = get_user_history(user_id)

    if not rows:
        await update.message.reply_text("📭 هنوز دانلودی انجام نداده‌ای.")
        return

    message = "📜 آخرین دانلودهای تو:\n\n"
    for link, quality, timestamp in rows:
        message += f"{quality} | {timestamp}\n{link}\n\n"

    await update.message.reply_text(message)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    total = get_total_downloads()
    await update.message.reply_text(
        f"🛠 پنل ادمین\n"
        f"تعداد کل دانلودها: {total}\n"
        f"محدودیت روزانه کاربران: {MAX_DAILY_DOWNLOADS}\n"
        f"ادمین: نامحدود"
    )


async def blocked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین اجازه دارد.")
        return

    rows = get_blocked_users()
    if not rows:
        await update.message.reply_text("هیچ کاربری بلاک نشده است.")
        return

    message = "🚫 کاربران بلاک‌شده:\n\n"
    for (uid,) in rows:
        message += f"- {uid}\n"

    await update.message.reply_text(message)


async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

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
    if not update.message or not update.effective_user:
        return

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
    if not update.message or not update.effective_user:
        return

    text = update.message.text
    link = extract_youtube_link(text)

    if not link:
        await update.message.reply_text("❌ لطفاً لینک معتبر یوتیوب بفرست.")
        return

    user_id = update.effective_user.id
    if is_blocked(user_id):
        await update.message.reply_text(
            "❌ دسترسی شما توسط ادمین مسدود شده است."
        )
        return

    user_links[user_id] = link

    try:
        qualities = await asyncio.to_thread(get_available_qualities, link)
    except Exception:
        logger.warning(
            "Could not fetch real qualities for link: %s",
            link,
            exc_info=True,
        )
        qualities = []

    await update.message.reply_text(
        "کیفیت را انتخاب کن:",
        reply_markup=build_quality_keyboard(qualities),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    user_id = query.from_user.id
    link = user_links.get(user_id)

    if query.data == "cancel":
        await query.edit_message_text("❌ لغو شد.")
        return

    if not link:
        await query.edit_message_text(
            "❌ لینک پیدا نشد. دوباره لینک را ارسال کن."
        )
        return

    if is_blocked(user_id):
        await query.edit_message_text(
            "❌ دسترسی شما توسط ادمین مسدود شده است."
        )
        return

    if not query.data or not query.data.startswith("q_"):
        await query.edit_message_text("❌ گزینه نامعتبر است.")
        return

    if user_id != ADMIN_ID and not increment_limit(user_id):
        await query.edit_message_text(
            f"⚠️ محدودیت روزانه‌ات تمام شده ({MAX_DAILY_DOWNLOADS} تا)."
        )
        return

    quality = query.data.replace("q_", "")
    waiting_label = quality if quality.startswith("a") else f"{quality}p"

    await query.edit_message_text(f"⏳ در صف دانلود ... ({waiting_label})")
    await download_queue.put((user_id, link, quality, query))


async def post_init(app: Application):
    logger.info("Starting queue worker")
    worker = asyncio.create_task(queue_worker(), name="queue_worker")
    app.bot_data["queue_worker"] = worker


async def post_stop(app: Application):
    logger.info("Stopping queue worker")
    worker = app.bot_data.get("queue_worker")

    if worker and not worker.done():
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            logger.info("queue_worker cancelled successfully")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("blocked", blocked_list))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    logger.info("Storage dir: %s", STORAGE_DIR)
    logger.info("Download dir: %s", DOWNLOAD_DIR)
    logger.info("DB path: %s", DB_PATH)

    if BOT_MODE == "polling" or not WEBHOOK_URL:
        logger.info("Starting bot in polling mode on port %s", PORT)
        app.run_polling(drop_pending_updates=True)
        return

    logger.info("Starting bot in webhook mode on port %s", PORT)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}",
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
