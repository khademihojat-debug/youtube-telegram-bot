import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from downloader import get_available_qualities, download_video, download_audio, is_playlist
from database import (
    init_db,
    get_daily_count,
    try_acquire_download_slot,
    release_download_slot,
    save_history,
)

# ========== تنظیمات ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

MAX_DAILY = int(os.environ.get("MAX_DAILY_DOWNLOADS", 15))
TELEGRAM_FILE_LIMIT = int(os.environ.get("TELEGRAM_FILE_LIMIT_MB", 50)) * 1024 * 1024  # 50 MB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# httpx لاگ می‌کنه URL کامل هر درخواست رو که شامل توکن ربات می‌شه (مثلاً
# https://api.telegram.org/bot<TOKEN>/getUpdates). سطحش رو بالا می‌بریم تا
# توکن توی لاگ‌های سرور افشا نشه؛ خطاهای واقعی httpx همچنان نمایش داده می‌شن.
logging.getLogger("httpx").setLevel(logging.WARNING)

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
• پشتیبانی از لینک‌های **Shorts**
• ارسال **تام‌نیل** همراه ویدیو
• نمایش درصد پیشرفت دانلود
• مدیریت حجم فایل (آپلود در Pixeldrain برای فایل‌های بزرگ)
• محدودیت روزانه ({} بار در روز)

📖 **چطور استفاده کنم؟**
۱. لینک ویدیو را بفرستید.
۲. کیفیت مورد نظر را انتخاب کنید.
۳. منتظر دانلود و ارسال فایل باشید.

ℹ️ **نکته:**
دانلود کامل پلی‌لیست هنوز پیاده‌سازی نشده است.

🔗 **مثال:**
`https://youtube.com/watch?v=...`
`https://youtube.com/shorts/...`
""".format(MAX_DAILY)


# ========== توابع کمکی ==========
def generate_uid(update: Update) -> str:
    return f"{update.effective_user.id}_{update.effective_message.message_id}"


async def send_large_file(bot, chat_id, file_path, caption, thumb=None):
    """ارسال فایل با مدیریت حجم (Pixeldrain برای فایل‌های بزرگ)"""
    file_size = os.path.getsize(file_path)
    if file_size <= TELEGRAM_FILE_LIMIT:
        thumb_file = None
        try:
            with open(file_path, 'rb') as media_file:
                if thumb and os.path.exists(thumb):
                    thumb_file = open(thumb, 'rb')
                await bot.send_document(
                    chat_id=chat_id,
                    document=media_file,
                    caption=caption,
                    filename=os.path.basename(file_path),
                    thumbnail=thumb_file,
                )
        finally:
            if thumb_file:
                thumb_file.close()
    else:
        try:
            import pixeldrain
            upload = await asyncio.to_thread(pixeldrain.upload_file, file_path)
            link = upload.get_url() if hasattr(upload, "get_url") else str(upload)

            await bot.send_message(
                chat_id=chat_id,
                text=f"📁 **فایل بزرگ (>{TELEGRAM_FILE_LIMIT//1024//1024}MB)**\n"
                     f"لینک دانلود: {link}\n"
                     f"📂 نام فایل: `{os.path.basename(file_path)}`",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Pixeldrain upload failed: {e}")
            raise RuntimeError("فایل بزرگ است و آپلود در Pixeldrain با خطا مواجه شد.") from e


async def safe_delete_message(message):
    try:
        await message.delete()
    except Exception:
        pass


async def safe_remove_file(path: str | None):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f"cleanup failed for {path}: {e}")


# ========== هندلرها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎬 سلام {user.first_name}!\n"
        f"به ربات دانلود یوتیوب خوش آمدید.\n\n"
        f"📌 لینک ویدیو را بفرستید تا دانلود کنم.",
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
    remain = max(0, MAX_DAILY - count)
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

    count = get_daily_count(user_id)
    if count >= MAX_DAILY:
        await update.message.reply_text(
            f"❌ **محدودیت روزانه شما تمام شده!**\n"
            f"شما امروز {MAX_DAILY} بار دانلود کرده‌اید.\n"
            f"از فردا دوباره امتحان کنید.",
            parse_mode='Markdown'
        )
        return

    is_pl = is_playlist(link)
    msg = await update.message.reply_text(
        f"⏳ در حال دریافت اطلاعات {'پلی‌لیست' if is_pl else 'ویدیو'}...\n"
        f"⏱️ لطفاً صبر کنید."
    )

    if is_pl:
        await msg.edit_text(
            "📋 دانلود کامل پلی‌لیست هنوز پیاده‌سازی نشده است.\n"
            "فعلاً لینک یک ویدیو یا Shorts بفرستید."
        )
        return

    try:
        qualities = await asyncio.to_thread(get_available_qualities, link)
        if not qualities:
            await msg.edit_text("❌ هیچ کیفیتی برای این ویدیو پیدا نشد.")
            return

        uid = generate_uid(update)
        user_data_store[uid] = {"link": link, "is_playlist": False}

        keyboard = []
        for label, qid in qualities.items():
            keyboard.append([InlineKeyboardButton(f"📹 {label}", callback_data=f"v|{uid}|{qid}")])

        keyboard.append([InlineKeyboardButton("🎵 MP3 128kbps", callback_data=f"a|{uid}|128")])
        keyboard.append([InlineKeyboardButton("🎵 MP3 320kbps", callback_data=f"a|{uid}|320")])

        await msg.edit_text(
            "🎯 **کیفیت مورد نظر را انتخاب کنید:**",
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
        remain = max(0, MAX_DAILY - count)
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
        if len(parts) < 2:
            await query.edit_message_text("❌ داده نامعتبر.")
            return

        action, uid = parts[0], parts[1]
        if uid not in user_data_store:
            await query.edit_message_text("❌ لینک منقضی شده. دوباره لینک را ارسال کنید.")
            return

        if action == "pl":
            await query.edit_message_text("📋 دانلود کامل پلی‌لیست هنوز پیاده‌سازی نشده است.")
            return

        if len(parts) < 3:
            await query.edit_message_text("❌ داده نامعتبر.")
            return

        link = user_data_store[uid]["link"]
        quality = parts[2]

        ok, current_count = try_acquire_download_slot(query.from_user.id, MAX_DAILY)
        if not ok:
            await query.edit_message_text(
                f"❌ **محدودیت روزانه شما تمام شده!**\n"
                f"شما امروز {current_count} بار دانلود کرده‌اید.\n"
                f"از فردا دوباره امتحان کنید.",
                parse_mode='Markdown'
            )
            return

        reserved_slot = True
        filename = None
        thumb = None
        progress_msg = None
        sent_successfully = False

        await query.edit_message_text("⏳ در حال آماده‌سازی دانلود...")
        progress_msg = await query.message.reply_text("⏳ 0% دانلود...")

        loop = asyncio.get_running_loop()

        async def _render_progress(percent: int):
            if progress_msg is None:
                return
            try:
                await progress_msg.edit_text(f"⏳ {percent}% دانلود...")
            except Exception:
                pass

        def update_progress(percent: int):
            try:
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(_render_progress(percent))
                )
            except Exception:
                pass

        try:
            if action == "v":
                filename, thumb = await download_video(link, quality, update_progress)
                caption = "🎬 ویدیو دانلود شد!"
            elif action == "a":
                filename = await download_audio(link, quality, update_progress)
                thumb = None
                caption = "🎵 فایل صوتی دانلود شد!"
            else:
                await query.edit_message_text("❌ عملیات نامعتبر.")
                return

            await safe_delete_message(progress_msg)
            progress_msg = None

            await send_large_file(
                context.bot,
                query.message.chat_id,
                filename,
                caption,
                thumb
            )
            sent_successfully = True

            try:
                save_history(query.from_user.id, link, quality, os.path.basename(filename))
            except Exception as e:
                logger.warning(f"save_history failed: {e}")

            await query.edit_message_text("✅ دانلود کامل شد!")

        except Exception as e:
            logger.error(f"download error: {e}")
            if reserved_slot and not sent_successfully:
                try:
                    release_download_slot(query.from_user.id)
                    reserved_slot = False
                except Exception as release_error:
                    logger.warning(f"release_download_slot failed: {release_error}")
            await query.edit_message_text(f"❌ خطا در دانلود: {str(e)[:100]}")
        finally:
            await safe_delete_message(progress_msg)
            await safe_remove_file(filename)
            await safe_remove_file(thumb)
            user_data_store.pop(uid, None)

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
