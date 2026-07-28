import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from downloader import get_available_qualities, download_video, download_audio

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Application.builder().token(BOT_TOKEN).build()
user_data_store = {}

def generate_uid(update: Update) -> str:
    return f"{update.effective_user.id}_{update.effective_message.message_id}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 لینک یوتیوب را بفرستید.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("❌ لینک نامعتبر.")
        return

    msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات...")
    try:
        qualities = await asyncio.to_thread(get_available_qualities, link)
        if not qualities:
            await msg.edit_text("❌ کیفیتی یافت نشد.")
            return

        uid = generate_uid(update)
        user_data_store[uid] = {"link": link}

        keyboard = []
        for label, qid in qualities.items():
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=f"v|{uid}|{qid}")])
        keyboard.append([InlineKeyboardButton("🎵 MP3 128", callback_data=f"a|{uid}|128")])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320", callback_data=f"a|{uid}|320")])

        await msg.edit_text("🎯 کیفیت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"message_handler: {e}")
        await msg.edit_text(f"❌ خطا: {str(e)[:100]}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split('|')
        if len(parts) != 3:
            await query.edit_message_text("❌ داده نامعتبر.")
            return
        action, uid, quality = parts
        if uid not in user_data_store:
            await query.edit_message_text("❌ لینک منقضی شده. دوباره ارسال کن.")
            return
        link = user_data_store[uid]["link"]
    except Exception as e:
        logger.error(f"callback parse: {e}")
        await query.edit_message_text("❌ خطا در پردازش.")
        return

    await query.edit_message_text("⏳ دانلود...")

    try:
        if action == "v":
            filename = await download_video(link, quality)
            caption = "🎬 ویدیو"
        else:
            filename = await download_audio(link, quality)
            caption = "🎵 صدا"

        with open(filename, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=f,
                caption=caption,
                filename=os.path.basename(filename)
            )

        # پاک کردن فایل
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except:
            pass

        if uid in user_data_store:
            del user_data_store[uid]

        await query.edit_message_text("✅ دانلود کامل شد!")

    except Exception as e:
        logger.error(f"download: {e}")
        await query.edit_message_text(f"❌ خطا: {str(e)[:100]}")

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(CallbackQueryHandler(callback_handler))

if __name__ == "__main__":
    app.run_polling()
