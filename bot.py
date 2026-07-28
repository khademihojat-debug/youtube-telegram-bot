import os
import asyncio
import logging
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

app = Application.builder().token(BOT_TOKEN).build()

# ========== دیکشنری برای ذخیره موقت لینک‌ها ==========
user_data_store = {}

def generate_id(update: Update) -> str:
    """ساخت شناسه یکتا برای هر کاربر و هر پیام"""
    return f"{update.effective_user.id}_{update.effective_message.message_id}"

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

        uid = generate_id(update)
        user_data_store[uid] = {"link": link}

        keyboard = []
        for label, qid in qualities.items():
            callback = f"v|{uid}|{qid}"
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=callback)])
        
        callback_128 = f"a|{uid}|128"
        callback_320 = f"a|{uid}|320"
        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=callback_128)])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=callback_320)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text("🎯 کیفیت مورد نظر را انتخاب کنید:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error in message_handler: {e}")
        await msg.edit_text(f"❌ خطا: {str(e)[:100]}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split('|')
        if len(parts) != 3:
            await query.edit_message_text("❌ داده نامعتبر.")
            return
        
        action, uid, quality = parts[0], parts[1], parts[2]
        
        if uid not in user_data_store:
            await query.edit_message_text("❌ لینک منقضی شده. لطفاً دوباره لینک را ارسال کنید.")
            return
        
        link = user_data_store[uid]["link"]
        
    except Exception as e:
        logger.error(f"Callback parse error: {e}")
        await query.edit_message_text("❌ خطا در پردازش داده.")
        return

    await query.edit_message_text("⏳ در حال دانلود... لطفاً صبر کنید.")

    try:
        if action == "v":
            filename, thumb = await download_video(link, quality)
            caption = "🎬 ویدئو دانلود شد!"
        else:  # action == "a"
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
        
        # ====== پاک کردن فایل‌ها با مدیریت خطا (کاملاً ایمن) ======
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception as e:
            logger.warning(f"Could not remove file {filename}: {e}")
        
        # بررسی thumb فقط در صورتی که None نباشد و string باشد
        if thumb is not None and isinstance(thumb, str):
            if os.path.exists(thumb):
                try:
                    os.remove(thumb)
                except Exception as e:
                    logger.warning(f"Could not remove thumbnail {thumb}: {e}")
        
        # پاک کردن از دیکشنری
        if uid in user_data_store:
            del user_data_store[uid]
        
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
