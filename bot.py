import os
import asyncio
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from downloader import get_available_qualities, download_video, download_audio

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_MODE = os.environ.get("BOT_MODE", "webhook")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 به ربات دانلود یوتیوب خوش آمدید!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 راهنما: لینک یوتیوب بفرست، کیفیت رو انتخاب کن، دانلود کن.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("❌ لینک معتبر بفرستید.")
        return

    msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات...")
    try:
        qualities = await asyncio.to_thread(get_available_qualities, link)
        if not qualities:
            await msg.edit_text("❌ کیفیتی پیدا نشد.")
            return

        keyboard = []
        for label, qid in qualities.items():
            data = json.dumps({"action": "video", "link": link, "quality": qid})
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=data)])
        
        data_audio_128 = json.dumps({"action": "audio", "link": link, "quality": "128"})
        data_audio_320 = json.dumps({"action": "audio", "link": link, "quality": "320"})
        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=data_audio_128)])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=data_audio_320)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text("🎯 کیفیت را انتخاب کنید:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"message_handler error: {e}")
        await msg.edit_text(f"❌ خطا: {str(e)[:100]}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        data = json.loads(query.data)
        action = data["action"]
        link = data["link"]
        quality = data["quality"]
    except Exception as e:
        logger.error(f"JSON parse error: {e}")
        await query.edit_message_text("❌ داده نامعتبر است.")
        return

    await query.edit_message_text("⏳ در حال دانلود...")

    try:
        if action == "video":
            filename, thumb = await download_video(link, quality)
            caption = "🎬 ویدئو دانلود شد!"
        else:
            filename, thumb = await download_audio(link, quality)
            caption = "🎵 فایل صوتی دانلود شد!"

        with open(filename, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=f,
                caption=caption,
                filename=os.path.basename(filename)
            )
        os.remove(filename)
        await query.edit_message_text("✅ دانلود کامل شد!")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(f"❌ خطا: {str(e)[:100]}")

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(CallbackQueryHandler(callback_handler))

if __name__ == "__main__":
    if BOT_MODE == "webhook":
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()
