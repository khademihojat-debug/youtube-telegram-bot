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

# ========== دیکشنری برای ذخیره موقت لینک‌ها ==========
# هر کاربر یه شناسه داره که لینک و کیفیت رو نگه می‌داره
user_data_store = {}

def generate_id(update: Update) -> str:
    """ساخت شناسه یکتا برای هر کاربر و هر پیام"""
    return f"{update.effective_user.id}_{update.effective_message.message_id}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 به ربات دانلود یوتیوب خوش آمدید!\nلینک ویدئو را ارسال کنید.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 لینک یوتیوب بفرست، کیفیت رو انتخاب کن، دانلود کن.")

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

        # ساخت شناسه یکتا برای این درخواست
        uid = generate_id(update)
        # ذخیره لینک در دیکشنری با شناسه
        user_data_store[uid] = {"link": link}

        keyboard = []
        for label, qid in qualities.items():
            # فقط کیفیت رو توی callback_data می‌فرستیم (کوتاه)
            callback = f"v|{uid}|{qid}"
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=callback)])
        
        # دکمه‌های صوتی
        callback_128 = f"a|{uid}|128"
        callback_320 = f"a|{uid}|320"
        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=callback_128)])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=callback_320)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text("🎯 کیفیت را انتخاب کنید:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"message_handler error: {e}")
        await msg.edit_text(f"❌ خطا: {str(e)[:100]}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        # داده به صورت: action|uid|quality
        parts = query.data.split('|')
        if len(parts) != 3:
            await query.edit_message_text("❌ داده نامعتبر.")
            return
        
        action, uid, quality = parts[0], parts[1], parts[2]
        
        # دریافت لینک از دیکشنری با شناسه
        if uid not in user_data_store:
            await query.edit_message_text("❌ لینک منقضی شده. لطفاً دوباره لینک را ارسال کنید.")
            return
        
        link = user_data_store[uid]["link"]
        
    except Exception as e:
        logger.error(f"Callback parse error: {e}")
        await query.edit_message_text("❌ خطا در پردازش داده.")
        return

    await query.edit_message_text("⏳ در حال دانلود...")

    try:
        if action == "v":
            filename, thumb = await download_video(link, quality)
            caption = "🎬 ویدئو دانلود شد!"
        else:  # action == "a"
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
        # پاک کردن از دیکشنری بعد از دانلود
        if uid in user_data_store:
            del user_data_store[uid]
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
        
