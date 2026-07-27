import asyncio
import logging
import os
import re

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, WEBHOOK_URL, ADMIN_ID
from database import (
    init_db,
    increment_limit,
    is_blocked,
    block_user,
    unblock_user,
    get_blocked_users,
    get_user_history,
    get_total_downloads,
    save_download,
    get_cached_download,
)
from downloader import download_video, download_audio, send_file_or_link
from keyboards import build_quality_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

queue = asyncio.Queue()
user_links = {}

def extract_link(text):
    m = re.search(r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s]+)", text)
    if not m:
        return None
    link = m.group(1)
    if "&" in link:
        link = link.split("&")[0]
    if "youtu.be/" in link:
        link = link.split("?")[0]
    return link

async def worker():
    while True:
        user_id, link, quality, query = await queue.get()
        try:
            await query.edit_message_text("⬇️ در حال دانلود...")

            cached = get_cached_download(link, quality)
            if cached:
                file_path, pix = cached
                if pix:
                    await query.message.reply_text(f"لینک مستقیم:\n{pix}")
                else:
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
                except:
                    pass

            pix = await send_file_or_link(query, filename, quality)
            save_download(user_id, link, quality, filename, pix)

        except Exception as e:
            await query.message.reply_text(f"❌ خطا: {e}")
        finally:
            queue.task_done()

async def start(update: Update, _):
    await update.message.reply_text("سلام! لینک یوتیوب را ارسال کن.")

async def history(update: Update, _):
    rows = get_user_history(update.effective_user.id)
    if not rows:
        await update.message.reply_text("📭 هیچ دانلودی نداری.")
        return
    msg = ""
    for link, q, ts in rows:
        msg += f"{q} | {ts}\n{link}\n\n"
    await update.message.reply_text(msg)

async def admin(update: Update, _):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ فقط ادمین.")
    total = get_total_downloads()
    await update.message.reply_text(f"کل دانلودها: {total}\nمحدودیت کاربران: 15\nادمین: نامحدود")

async def blocked(update: Update, _):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ فقط ادمین.")
    rows = get_blocked_users()
    if not rows:
        return await update.message.reply_text("هیچ کاربری بلاک نیست.")
    msg = "\n".join(str(uid[0]) for uid in rows)
    await update.message.reply_text(msg)

async def block_cmd(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ فقط ادمین.")
    if not context.args:
        return await update.message.reply_text("استفاده: /block <id>")
    block_user(int(context.args[0]))
    await update.message.reply_text("بلاک شد.")

async def unblock_cmd(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ فقط ادمین.")
    if not context.args:
        return await update.message.reply_text("استفاده: /unblock <id>")
    unblock_user(int(context.args[0]))
    await update.message.reply_text("آن‌بلاک شد.")

async def msg(update: Update, _):
    text = update.message.text
    link = extract_link(text)
    if not link:
        return await update.message.reply_text("❌ لینک یوتیوب بده.")

    user_id = update.effective_user.id

    if is_blocked(user_id):
        return await update.message.reply_text("❌ بلاک هستی.")

    if user_id != ADMIN_ID:
        if not increment_limit(user_id):
            return await update.message.reply_text("⚠️ محدودیت روزانه‌ات تمام شد.")

    user_links[user_id] = link
    await update.message.reply_text("کیفیت را انتخاب کن:", reply_markup=build_quality_keyboard())

async def btn(update: Update, _):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    link = user_links.get(user_id)

    if q.data == "cancel":
        return await q.edit_message_text("لغو شد.")

    if not link:
        return await q.edit_message_text("❌ لینک پیدا نشد.")

    if q.data == "q_a128":
        await q.edit_message_text("در صف (128kbps)")
        return await queue.put((user_id, link, "a128", q))

    if q.data == "q_a320":
        await q.edit_message_text("در صف (320kbps)")
        return await queue.put((user_id, link, "a320", q))

    if q.data.startswith("q_"):
        quality = q.data.replace("q_", "")
        await q.edit_message_text(f"در صف ({quality}p)")
        return await queue.put((user_id, link, quality, q))

async def post_init(app):
    app.bot_data["worker"] = asyncio.create_task(worker())

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("blocked", blocked))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    port = int(os.environ.get("PORT", 8080))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
