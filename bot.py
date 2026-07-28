import os
import asyncio
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from downloader import get_available_qualities, download_video, download_audio

# ========== تنظیمات ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_MODE = os.environ.get("BOT_MODE", "webhook")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ساخت اپلیکیشن ==========
app = Application.builder().token(BOT_TOKEN).build()

# ========== هندلرها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 به ربات دانلود یوتیوب خوش آمدید!\n"
        "لینک ویدئو را ارسال کنید تا کیفیت‌های موجود را ببینید."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 راهنما:\n"
        "۱. لینک ویدئو را ارسال کنید.\n"
        "۲. کیفیت مورد نظر را انتخاب کنید.\n"
        "۳. منتظر دانلود و ارسال فایل باشید.\n"
        "⚠️ فایل‌های بالای ۴۸ مگابایت از طریق Pixeldrain ارسال می‌شوند."
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("❌ لطفاً یک لینک معتبر ارسال کنید.")
        return

    msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات ویدئو...")
    try:
        qualities = await asyncio.to_thread(get_available_qualities, link)
        if not qualities:
            await msg.edit_text("❌ هیچ کیفیتی برای این ویدئو پیدا نشد.")
            return

        keyboard = []
        for label, qid in qualities.items():
            # ارسال داده با json به جای | برای جلوگیری از خطا
            data = json.dumps({"action": "video", "link": link, "quality": qid})
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=data)])
        
        # دکمه‌های صوتی
        data_audio_128 = json.dumps({"action": "audio", "link": link, "quality": "128"})
        data_audio_320 = json.dumps({"action": "audio", "link": link, "quality": "320"})
        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=data_audio_128)])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=data_audio_320)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        await msg.edit_text("🎯 کیفیت مورد نظر را انتخاب کنید:", reply_markup=reply_markup)
        context.user_data['last_link'] = link

    except Exception as e:
        logger.error(f"Error in message_handler: {e}")
        await msg.edit_text(f"❌ خطا: {str(e)[:100]}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        # دریافت داده از json
        data = json.loads(query.data)
        action = data["action"]
        link = data["link"]
        quality = data["quality"]
    except Exception as e:
        await query.edit_message_text("❌ داده نامعتبر است.")
        logger.error(f"Callback data error: {e}")
        return

    await query.edit_message_text("⏳ در حال دانلود... لطفاً صبر کنید.")

    try:
        if action == "video":
            filename, thumb = await download_video(link, quality)
            caption = "🎬 ویدئو دانلود شد!"
        else:  # audio
            filename, thumb = await download_audio(link, quality)
            caption = "🎵 فایل صوتی دانلود شد!"

        # ارسال فایل به کاربر
        with open(filename, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=f,
                caption=caption,
                filename=os.path.basename(filename)
            )
        # پاک کردن فایل بعد از ارسال
        os.remove(filename)
        if thumb and os.path.exists(thumb):
            os.remove(thumb)
        await query.edit_message_text("✅ دانلود کامل شد!")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(f"❌ خطا در دانلود: {str(e)[:100]}")

# ========== ثبت هندلرها ==========
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(CallbackQueryHandler(callback_handler))

# ========== اجرا ==========
if __name__ == "__main__":
    if BOT_MODE == "webhook":
        if not WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL is required in webhook mode")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        app.run_polling()
