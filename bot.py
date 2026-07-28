import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from downloader import get_available_qualities, download_video, download_audio
import json

# تنظیمات از متغیرهای محیطی
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_MODE = os.environ.get("BOT_MODE", "webhook")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
DATA_DIR = os.environ.get("DATA_DIR", "./data")
MAX_DAILY = int(os.environ.get("MAX_DAILY_DOWNLOADS", 15))

# راه‌اندازی لاگر
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# صف دانلود (برای جلوگیری از بار زیاد)
download_queue = asyncio.Queue()
is_worker_running = False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 به ربات دانلود یوتیوب خوش آمدید!\n"
        "لینک ویدئو یا پلی‌لیست را ارسال کنید تا کیفیت‌های موجود را ببینید."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 راهنما:\n"
        "۱. لینک ویدئو را ارسال کنید.\n"
        "۲. کیفیت مورد نظر را انتخاب کنید.\n"
        "۳. منتظر دانلود و ارسال فایل باشید.\n"
        "⚠️ حجم فایل‌های بالای ۴۸ مگابایت از طریق Pixeldrain ارسال می‌شوند."
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لینک و نمایش کیفیت‌های موجود"""
    link = update.message.text.strip()
    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("❌ لطفاً یک لینک معتبر ارسال کنید.")
        return

    # بررسی روزانه (در صورت نیاز)
    # ...

    msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات ویدئو...")
    try:
        # دریافت کیفیت‌ها با fallback به best در صورت خطا
        qualities = await asyncio.to_thread(get_available_qualities, link)
        if not qualities:
            await msg.edit_text("❌ هیچ کیفیتی برای این ویدئو پیدا نشد.")
            return

        # ساخت دکمه‌های کیفیت
        keyboard = []
        for label, qid in qualities.items():
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=f"video|{link}|{qid}")])
        # دکمه صدا
        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=f"audio|{link}|128")])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=f"audio|{link}|320")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await msg.edit_text("🎯 کیفیت مورد نظر را انتخاب کنید:", reply_markup=reply_markup)
        context.user_data['last_link'] = link

    except Exception as e:
        logger.error(f"Error in message_handler: {e}")
        await msg.edit_text("❌ خطا در دریافت اطلاعات ویدئو. ممکن است لینک نامعتبر باشد یا یوتیوب محدودیت ایجاد کرده باشد.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب کیفیت و اضافه کردن به صف"""
    query = update.callback_query
    await query.answer()

    data = query.data.split('|')
    if len(data) < 3:
        await query.edit_message_text("❌ داده نامعتبر.")
        return

    action, link, quality = data[0], data[1], data[2]

    # اضافه کردن به صف
    user_id = query.from_user.id
    await download_queue.put((user_id, link, quality, query.message.chat.id))

    await query.edit_message_text("✅ درخواست شما به صف افزوده شد. لطفاً منتظر بمانید...")
    # اگر worker فعال نیست، آن را شروع کن
    global is_worker_running
    if not is_worker_running:
        asyncio.create_task(queue_worker())

async def queue_worker():
    """پردازنده صف دانلود"""
    global is_worker_running
    if is_worker_running:
        return
    is_worker_running = True
    logger.info("Queue worker started")

    while not download_queue.empty():
        try:
            user_id, link, quality, chat_id = await download_queue.get()
            # ارسال پیام شروع دانلود
            await asyncio.sleep(0.1)  # برای جلوگیری از مسدود شدن

            # دانلود
            try:
                if quality.isdigit() or quality == 'best':
                    filename, thumb = await download_video(link, quality)
                    caption = "🎬 ویدئو دانلود شد!"
                else:
                    filename, thumb = await download_audio(link, quality)
                    caption = "🎵 فایل صوتی دانلود شد!"

                # ارسال فایل به کاربر (با مدیریت حجم)
                # ... کد ارسال فایل (با توجه به پروژه اصلی)
                await asyncio.sleep(0.5)

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Download error: {error_msg}")
                # اگر خطا مربوط به فرمت نبود، به کاربر اطلاع بده
                if "Requested format is not available" in error_msg:
                    # قبلاً در downloader fallback شده، ولی اگر باز هم خطا داد
                    await context.bot.send_message(chat_id, "❌ کیفیت مورد نظر در دسترس نیست. لطفاً کیفیت دیگری را انتخاب کنید.")
                else:
                    await context.bot.send_message(chat_id, f"❌ خطا در دانلود: {error_msg}")

        except Exception as e:
            logger.error(f"Worker loop error: {e}")

    is_worker_running = False
    logger.info("Queue worker stopped")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)

    if BOT_MODE == "webhook":
        if not WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL required in webhook mode")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
