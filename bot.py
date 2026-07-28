import os
import asyncio
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from downloader import get_available_qualities, download_video, download_audio, is_playlist
from database import init_db, get_daily_count, increment_daily_count, save_history
import pixeldrain
import shutil

# ========== تنظیمات ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

MAX_DAILY = int(os.environ.get("MAX_DAILY_DOWNLOADS", 15))
TELEGRAM_FILE_LIMIT = int(os.environ.get("TELEGRAM_FILE_LIMIT_MB", 50)) * 1024 * 1024  # 50 MB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Application.builder().token(BOT_TOKEN).build()
user_data_store = {}

# ========== دیتابیس ==========
init_db()

# ========== راهنما ==========
HELP_TEXT = """
🎬 **راهنمای ربات دانلود یوتیوب**

📌 **قابلیت‌ها:**
• دانلود ویدیو با کیفیت‌های مختلف (با صدا)
• دانلود MP3 با کیفیت ۱۲۸ و ۳۲۰
• پشتیبانی از لینک‌های **Shorts** و **پلی‌لیست**
• ارسال **تام‌نیل** همراه ویدیو
• نمایش درصد پیشرفت دانلود
• مدیریت حجم فایل (آپلود در Pixeldrain برای فایل‌های بزرگ)
• محدودیت روزانه ({} بار در روز)

📖 **چطور استفاده کنم؟**
۱. لینک ویدیو/پلی‌لیست را بفرستید.
۲. کیفیت مورد نظر را انتخاب کنید.
۳. منتظر دانلود و ارسال فایل باشید.

🔗 **مثال:**
`https://youtube.com/watch?v=...`
`https://youtube.com/playlist?list=...`
""".format(MAX_DAILY)

# ========== توابع کمکی ==========
def generate_uid(update: Update) -> str:
    return f"{update.effective_user.id}_{update.effective_message.message_id}"

async def send_large_file(bot, chat_id, file_path, caption, thumb=None):
    """ارسال فایل با مدیریت حجم (Pixeldrain برای فایل‌های بزرگ)"""
    file_size = os.path.getsize(file_path)
    if file_size <= TELEGRAM_FILE_LIMIT:
        # ارسال مستقیم
        with open(file_path, 'rb') as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=caption,
                filename=os.path.basename(file_path),
                thumbnail=open(thumb, 'rb') if thumb and os.path.exists(thumb) else None
            )
    else:
        # آپلود در Pixeldrain
        try:
            async with pixeldrain.Client() as client:
                # آپلود فایل
                upload = await client.upload_file(file_path)
                link = upload.get_url()
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"📁 **فایل بزرگ (>{TELEGRAM_FILE_LIMIT//1024//1024}MB)**\n"
                         f"لینک دانلود: {link}\n"
                         f"📂 نام فایل: `{os.path.basename(file_path)}`",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Pixeldrain upload failed: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ فایل بزرگ است و آپلود در Pixeldrain با خطا مواجه شد."
            )

# ========== هندلرها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎬 سلام {user.first_name}!\n"
        f"به ربات دانلود یوتیوب خوش آمدید.\n\n"
        f"📌 لینک ویدیو یا پلی‌لیست را بفرستید تا دانلود کنم.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 راهنما", callback_data="help")],
            [InlineKeyboardButton("📊 وضعیت امروز", callback_data="status")]
        ])
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = get_daily_count(user_id)
    remain = MAX_DAILY - count
    await update.message.reply_text(
        f"📊 **وضعیت دانلود امروز**\n\n"
        f"✅ استفاده شده: {count}\n"
        f"🔰 باقی‌مانده: {remain}\n"
        f"📌 سقف روزانه: {MAX_DAILY}",
        parse_mode='Markdown'
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text.strip()

    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("❌ لطفاً یک لینک معتبر ارسال کنید.")
        return

    # بررسی محدودیت روزانه
    count = get_daily_count(user_id)
    if count >= MAX_DAILY:
        await update.message.reply_text(
            f"❌ **محدودیت روزانه شما تمام شده!**\n"
            f"شما امروز {MAX_DAILY} بار دانلود کرده‌اید.\n"
            f"از فردا دوباره امتحان کنید.",
            parse_mode='Markdown'
        )
        return

    # بررسی پلی‌لیست
    is_pl = is_playlist(link)

    msg = await update.message.reply_text(
        f"⏳ در حال دریافت اطلاعات {'پلی‌لیست' if is_pl else 'ویدیو'}...\n"
        f"⏱️ لطفاً صبر کنید."
    )

    try:
        qualities = await asyncio.to_thread(get_available_qualities, link)
        if not qualities:
            await msg.edit_text("❌ هیچ کیفیتی برای این ویدیو پیدا نشد.")
            return

        uid = generate_uid(update)
        user_data_store[uid] = {"link": link, "is_playlist": is_pl}

        keyboard = []
        for label, qid in qualities.items():
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=f"v|{uid}|{qid}")])

        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=f"a|{uid}|128")])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=f"a|{uid}|320")])

        if is_pl:
            keyboard.append([InlineKeyboardButton("📋 دانلود همه (پلی‌لیست)", callback_data=f"pl|{uid}")])

        await msg.edit_text(
            f"🎯 **کیفیت مورد نظر را انتخاب کنید:**\n"
            f"{'📋 این یک پلی‌لیست است.' if is_pl else ''}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"message_handler error: {e}")
        await msg.edit_text(f"❌ خطا: {str(e)[:100]}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        await query.edit_message_text(HELP_TEXT, parse_mode='Markdown')
        return

    if query.data == "status":
        user_id = query.from_user.id
        count = get_daily_count(user_id)
        remain = MAX_DAILY - count
        await query.edit_message_text(
            f"📊 **وضعیت دانلود امروز**\n\n"
            f"✅ استفاده شده: {count}\n"
            f"🔰 باقی‌مانده: {remain}\n"
            f"📌 سقف روزانه: {MAX_DAILY}",
            parse_mode='Markdown'
        )
        return

    try:
        parts = query.data.split('|')
        if len(parts) < 3:
            await query.edit_message_text("❌ داده نامعتبر.")
            return

        action, uid = parts[0], parts[1]
        if uid not in user_data_store:
            await query.edit_message_text("❌ لینک منقضی شده. دوباره لینک را ارسال کنید.")
            return

        link = user_data_store[uid]["link"]
        is_pl = user_data_store[uid].get("is_playlist", False)

        quality = parts[2] if len(parts) > 2 else None

        # اگر پلی‌لیست و دانلود همه
        if action == "pl":
            await query.edit_message_text("⏳ در حال دانلود پلی‌لیست... این کار ممکن است زمان‌بر باشد.")
            # TODO: پیاده‌سازی دانلود پلی‌لیست
            await query.edit_message_text("📋 قابلیت دانلود پلی‌لیست در حال توسعه است.")
            return

        # دانلود ویدیو یا صدا
        await query.edit_message_text("⏳ در حال آماده‌سازی دانلود...")

        progress_msg = await query.message.reply_text("⏳ 0% دانلود...")

        async def update_progress(percent):
            try:
                await progress_msg.edit_text(f"⏳ {percent}% دانلود...")
            except:
                pass

        try:
            if action == "v":
                filename, thumb = await download_video(link, quality, update_progress)
                caption = "🎬 ویدیو دانلود شد!"
            else:  # audio
                filename = await download_audio(link, quality, update_progress)
                thumb = None
                caption = "🎵 فایل صوتی دانلود شد!"

            await progress_msg.delete()

            # ذخیره تاریخچه
            save_history(query.from_user.id, link, quality, os.path.basename(filename))

            # افزایش شمارش روزانه
            increment_daily_count(query.from_user.id)

            # ارسال فایل (با مدیریت حجم)
            await send_large_file(
                context.bot,
                query.message.chat_id,
                filename,
                caption,
                thumb
            )

            # پاک کردن فایل‌ها
            if os.path.exists(filename):
                os.remove(filename)
            if thumb and os.path.exists(thumb):
                os.remove(thumb)

            if uid in user_data_store:
                del user_data_store[uid]

            await query.edit_message_text("✅ دانلود کامل شد!")

        except Exception as e:
            logger.error(f"download error: {e}")
            await query.edit_message_text(f"❌ خطا در دانلود: {str(e)[:100]}")

    except Exception as e:
        logger.error(f"callback parse error: {e}")
        await query.edit_message_text("❌ خطا در پردازش.")

# ========== ثبت هندلرها ==========
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("status", status_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(CallbackQueryHandler(callback_handler))

# ========== اجرا ==========
if __name__ == "__main__":
    app.run_polling()
