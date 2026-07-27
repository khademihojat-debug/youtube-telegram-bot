import asyncio
import logging
import os
import re

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, WEBHOOK_URL, ADMIN_ID
from database import (
    init_db,
    get_user_history,
    get_total_downloads,
    get_blocked_users,
    block_user,
    unblock_user,
    is_blocked,
    increment_limit,
    save_download,
    get_cached_download,
)
from downloader import (
    download_video,
    download_audio,
    send_file_or_link,
)
from keyboards import build_quality_keyboard

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

download_queue: asyncio.Queue = asyncio.Queue()
user_links = {}

def extract_youtube_link(text: str):
    pattern = r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s]+)"
    m = re.search(pattern, text)
    if not m:
        return None
    link = m.group(1).strip()
    if "youtu.be/" in link:
        return link.split("?")[0]
    if "&" in link:
        link = link.split("&")[0]
    return link

async def queue_worker():
    while True:
        user_id, link, quality, query = await download_queue.get()
        try:
            await query.edit_message_text("⬇️ در حال دانلود...")

            cached = get_cached_download(link, quality)
            if cached:
                file_path, pix_url = cached
                if pix_url:
                    await query.message.reply_text(
                        "✅ این فایل قبلاً دانلود شده بود.\n"
                        f"لینک مستقیم:\n{pix_url}"
                    )
                    continue
                if file_path:
                    await send_file_or_link(query, file_path, quality)
                    continue

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

            pix_url = await send_file_or_link(query, filename, quality)
            save_download(user_id, link, quality, filename, pix_url)

        except Exception as e:
            logger.exception("Download worker error: %s", e)
            await query.message.reply_text(f"❌ خطا: {e}")
        finally:
            download_queue.task_done()

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
        f"کاربران روزانه محدود: {ADMIN_ID}\n"
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
        await update.message.reply_text("⚠️ محدودیت روزانه‌ات تمام شده.")
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

    if query.data.startswith("q_"):
        q = query.data.replace("q_", "")
        await query.edit_message_text(f"⏳ در صف دانلود ... ({q}p)")
        await download_queue.put((user_id, link, q, query))
        return

    await query.edit_message_text("❌ گزینه نامعتبر است.")

async def post_init(app: Application):
    app.bot_data["queue_worker"] = asyncio.create_task(queue_worker())

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
