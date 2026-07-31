import os
import time
import asyncio
import logging

# لاگینگ باید قبل از ایمپورت downloader.py فعال بشه، چون downloader.py موقع
# ایمپورت یه پیام INFO درباره‌ی نوشتن فایل کوکی چاپ می‌کنه.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# httpx لاگ می‌کنه URL کامل هر درخواست رو که شامل توکن ربات می‌شه — سطحش رو
# بالا می‌بریم تا توکن توی لاگ‌های سرور افشا نشه.
logging.getLogger("httpx").setLevel(logging.WARNING)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)
from downloader import get_available_qualities, download_video, download_audio, is_playlist
from database import (
    init_db,
    get_daily_count,
    try_acquire_download_slot,
    release_download_slot,
    save_history,
    is_vip,
    get_vip_expiry,
    grant_vip,
)

# ========== تنظیمات ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

MAX_DAILY = int(os.environ.get("MAX_DAILY_DOWNLOADS", 3))
TELEGRAM_FILE_LIMIT = int(os.environ.get("TELEGRAM_FILE_LIMIT_MB", 50)) * 1024 * 1024  # 50 MB

# ========== کنترل دسترسی ==========
_allowed_ids_raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {
    int(uid.strip()) for uid in _allowed_ids_raw.split(",") if uid.strip().isdigit()
} if _allowed_ids_raw else None

# آیدی‌های عددی کاربرهایی که دانلود نامحدود دارن (شما و دوستان‌تون)
_unlimited_ids_raw = os.environ.get("UNLIMITED_USER_IDS", "").strip()
UNLIMITED_USER_IDS = {
    int(uid.strip()) for uid in _unlimited_ids_raw.split(",") if uid.strip().isdigit()
}

MIN_SECONDS_BETWEEN_MESSAGES = float(os.environ.get("MIN_SECONDS_BETWEEN_MESSAGES", 2))
_last_action_time: dict[int, float] = {}


def is_user_allowed(user_id: int) -> bool:
    return ALLOWED_USER_IDS is None or user_id in ALLOWED_USER_IDS


def has_unlimited_access(user_id: int) -> bool:
    return user_id in UNLIMITED_USER_IDS or is_vip(user_id)


def is_rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    last = _last_action_time.get(user_id, 0)
    _last_action_time[user_id] = now
    return (now - last) < MIN_SECONDS_BETWEEN_MESSAGES


# ========== VIP و کسب درآمد ==========
VIP_PRICE_STARS = int(os.environ.get("VIP_PRICE_STARS", 50))
VIP_PRICE_RIAL = int(os.environ.get("VIP_PRICE_RIAL", 500000))
VIP_DURATION_DAYS = int(os.environ.get("VIP_DURATION_DAYS", 30))

AD_ENABLED = os.environ.get("AD_ENABLED", "true").lower() == "true"
AD_TEXT = os.environ.get(
    "AD_TEXT",
    "📢 این پیام یک تبلیغ نمونه است.\nبرای حذف تبلیغات، اشتراک VIP تهیه کنید: /vip"
)

# ========== پشتیبانی ==========
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "").strip()  # مثلاً "@your_support"

# ========== پرداخت کارت‌به‌کارت (تأیید دستی توسط ادمین) ==========
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0) or 0)  # آیدی عددی تلگرام شما
CARD_NUMBER = os.environ.get("CARD_NUMBER", "").strip()
CARD_HOLDER_NAME = os.environ.get("CARD_HOLDER_NAME", "").strip()

# کاربرهایی که الان منتظرن رسیدشون رو بفرستن (حافظه‌ی موقت، نه دیتابیس)
_awaiting_receipt: set[int] = set()


app = Application.builder().token(BOT_TOKEN).build()
user_data_store = {}

# ========== دیتابیس ==========
init_db()

# ========== راهنما ==========
HELP_TEXT = """
🎬 **راهنمای ربات دانلود**

📌 **قابلیت‌ها:**
• دانلود از یوتیوب، اینستاگرام و تیک‌تاک
• دانلود ویدیو با کیفیت‌های مختلف (با صدا)
• دانلود MP3 با کیفیت ۱۲۸ و ۳۲۰
• محدودیت روزانه ({} بار در روز — کاربران VIP نامحدود)

📖 **چطور استفاده کنم؟**
۱. لینک ویدیو را بفرستید (یوتیوب/اینستاگرام/تیک‌تاک)
۲. کیفیت مورد نظر را انتخاب کنید.
۳. منتظر دانلود و ارسال فایل باشید.

💎 **اشتراک VIP:**
با /vip می‌تونید محدودیت روزانه و تبلیغات رو حذف کنید (پرداخت با Stars یا کارت‌به‌کارت).

🆘 **پشتیبانی:** /support
""".format(MAX_DAILY)


# ========== توابع کمکی ==========
def generate_uid(update: Update) -> str:
    return f"{update.effective_user.id}_{update.effective_message.message_id}"


async def send_large_file(bot, chat_id, file_path, caption, thumb=None):
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


def build_status_text(user_id: int) -> str:
    if user_id in UNLIMITED_USER_IDS:
        return "📊 **وضعیت شما**\n\n♾️ دسترسی نامحدود دائمی دارید."

    if is_vip(user_id):
        expiry = get_vip_expiry(user_id)
        expiry_str = expiry.strftime("%Y-%m-%d") if expiry else "-"
        return (
            f"📊 **وضعیت شما**\n\n"
            f"💎 اشتراک VIP فعال (بدون محدودیت)\n"
            f"📅 انقضا: {expiry_str}"
        )

    count = get_daily_count(user_id)
    remain = max(0, MAX_DAILY - count)
    return (
        f"📊 **وضعیت دانلود امروز**\n\n"
        f"✅ استفاده شده: {count}\n"
        f"🔰 باقی‌مانده: {remain}\n"
        f"📌 سقف روزانه: {MAX_DAILY}\n\n"
        f"💎 برای حذف محدودیت: /vip"
    )


# ========== هندلرها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_user_allowed(user.id):
        logger.warning(f"Access denied for user_id={user.id} (username={user.username})")
        await update.message.reply_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return

    await update.message.reply_text(
        f"🎬 سلام {user.first_name}!\n"
        f"به ربات دانلود خوش آمدید.\n\n"
        f"📌 لینک یوتیوب، اینستاگرام یا تیک‌تاک را بفرستید تا دانلود کنم.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 راهنما", callback_data="help")],
            [InlineKeyboardButton("📊 وضعیت امروز", callback_data="status")],
            [InlineKeyboardButton("💎 خرید VIP", callback_data="vip_info")],
            [InlineKeyboardButton("🆘 پشتیبانی", callback_data="support")],
        ])
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return
    await update.message.reply_text(HELP_TEXT, parse_mode='Markdown')


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return
    await update.message.reply_text(build_status_text(user_id), parse_mode='Markdown')


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return

    text = f"🆘 برای پشتیبانی به {SUPPORT_USERNAME} پیام بدید." if SUPPORT_USERNAME else "🆘 پشتیبانی هنوز تنظیم نشده."
    await update.message.reply_text(text)


def _vip_payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ پرداخت با Stars ({VIP_PRICE_STARS})", callback_data="pay_stars")],
        [InlineKeyboardButton(f"💳 کارت‌به‌کارت ({VIP_PRICE_RIAL:,} ریال)", callback_data="pay_rial")],
    ])


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return

    if user_id in UNLIMITED_USER_IDS:
        await update.message.reply_text("♾️ شما از قبل دسترسی نامحدود دائمی دارید — نیازی به خرید VIP نیست.")
        return

    if is_vip(user_id):
        expiry = get_vip_expiry(user_id)
        expiry_str = expiry.strftime("%Y-%m-%d") if expiry else "-"
        await update.message.reply_text(f"💎 شما همین الان اشتراک VIP فعال دارید (تا {expiry_str}).")

    await update.message.reply_text(
        f"💎 **اشتراک VIP** ({VIP_DURATION_DAYS} روز)\n\nروش پرداخت رو انتخاب کنید:",
        reply_markup=_vip_payment_keyboard(),
        parse_mode='Markdown'
    )


async def send_stars_invoice(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="اشتراک VIP",
        description=f"حذف محدودیت روزانه دانلود و تبلیغات به مدت {VIP_DURATION_DAYS} روز",
        payload=f"vip_{user_id}_{int(time.time())}",
        provider_token="",  # برای Telegram Stars همیشه خالیه
        currency="XTR",
        prices=[LabeledPrice(f"VIP {VIP_DURATION_DAYS} روزه", VIP_PRICE_STARS)],
    )


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expiry = grant_vip(user_id, VIP_DURATION_DAYS)
    logger.info(f"VIP granted (Stars) to user_id={user_id} until {expiry}")
    await update.message.reply_text(
        f"✅ پرداخت موفق بود!\n"
        f"💎 اشتراک VIP شما تا {expiry.strftime('%Y-%m-%d')} فعال شد."
    )


async def start_card_payment(query, context: ContextTypes.DEFAULT_TYPE):
    if not CARD_NUMBER:
        await query.message.reply_text("❌ پرداخت کارت‌به‌کارت هنوز تنظیم نشده — با پشتیبانی تماس بگیرید.")
        return

    user_id = query.from_user.id
    _awaiting_receipt.add(user_id)

    await query.message.reply_text(
        f"💳 **پرداخت کارت‌به‌کارت**\n\n"
        f"مبلغ: **{VIP_PRICE_RIAL:,} ریال**\n"
        f"شماره کارت: `{CARD_NUMBER}`\n"
        f"به نام: {CARD_HOLDER_NAME or '-'}\n\n"
        f"بعد از واریز، لطفاً **عکس رسید** رو همین‌جا بفرستید تا VIP‌تون فعال بشه.",
        parse_mode='Markdown'
    )


async def receipt_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in _awaiting_receipt:
        return  # این عکس ربطی به رسید پرداخت نداره — نادیده می‌گیریم

    if not ADMIN_ID:
        await update.message.reply_text("❌ سیستم تأیید پرداخت هنوز تنظیم نشده — با پشتیبانی تماس بگیرید.")
        return

    _awaiting_receipt.discard(user_id)

    photo = update.message.photo[-1]  # بزرگ‌ترین سایز
    username = update.effective_user.username
    username_str = f"@{username}" if username else "(بدون یوزرنیم)"

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo.file_id,
            caption=(
                f"🧾 رسید پرداخت جدید\n"
                f"👤 کاربر: {username_str} (`{user_id}`)\n"
                f"💰 مبلغ: {VIP_PRICE_RIAL:,} ریال"
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ تأیید و فعال‌سازی VIP", callback_data=f"approve_vip|{user_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_vip|{user_id}"),
            ]])
        )
        await update.message.reply_text("📨 رسید شما برای بررسی ارسال شد. بعد از تأیید، VIP فعال می‌شه.")
    except Exception as e:
        logger.error(f"failed to forward receipt to admin: {e}")
        await update.message.reply_text("❌ خطا در ارسال رسید. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_allowed(user_id):
        logger.warning(f"Access denied for user_id={user_id}")
        await update.message.reply_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return

    if is_rate_limited(user_id):
        await update.message.reply_text("⏳ لطفاً کمی صبر کنید و دوباره امتحان کنید.")
        return

    link = update.message.text.strip()

    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("❌ لطفاً یک لینک معتبر ارسال کنید.")
        return

    allowed_domains = (
        "youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com",
        "instagram.com", "instagr.am",
        "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    )
    if not any(domain in link for domain in allowed_domains):
        await update.message.reply_text("❌ فقط لینک‌های یوتیوب، اینستاگرام و تیک‌تاک پشتیبانی می‌شن.")
        return

    user_has_unlimited = has_unlimited_access(user_id)

    if not user_has_unlimited:
        count = get_daily_count(user_id)
        if count >= MAX_DAILY:
            await update.message.reply_text(
                f"❌ **محدودیت روزانه شما تمام شده!**\n"
                f"شما امروز {MAX_DAILY} بار دانلود کرده‌اید.\n"
                f"از فردا دوباره امتحان کنید یا با /vip نامحدود بشید.",
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
            "فعلاً لینک یک ویدیو/پست/Reel/Short بفرستید."
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

    # ---- تأیید/رد رسید توسط ادمین — قبل از چک whitelist عادی، چون فقط ادمین
    # باید بتونه این دکمه‌ها رو بزنه ----
    if query.data.startswith("approve_vip|") or query.data.startswith("reject_vip|"):
        if not ADMIN_ID or query.from_user.id != ADMIN_ID:
            await query.answer("⛔️ فقط ادمین می‌تونه این کار رو انجام بده.", show_alert=True)
            return

        action, target_id_str = query.data.split("|", 1)
        target_id = int(target_id_str)

        if action == "approve_vip":
            expiry = grant_vip(target_id, VIP_DURATION_DAYS)
            logger.info(f"VIP granted (card) to user_id={target_id} until {expiry}")
            await query.edit_message_caption(caption=query.message.caption + "\n\n✅ تأیید شد")
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"✅ پرداخت شما تأیید شد!\n💎 اشتراک VIP تا {expiry.strftime('%Y-%m-%d')} فعال شد."
                )
            except Exception as e:
                logger.warning(f"failed to notify user {target_id} of VIP approval: {e}")
        else:
            await query.edit_message_caption(caption=query.message.caption + "\n\n❌ رد شد")
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="❌ متأسفانه رسید پرداخت شما تأیید نشد. با پشتیبانی تماس بگیرید."
                )
            except Exception as e:
                logger.warning(f"failed to notify user {target_id} of VIP rejection: {e}")
        return

    if not is_user_allowed(query.from_user.id):
        logger.warning(f"Access denied for user_id={query.from_user.id} (callback)")
        await query.edit_message_text("⛔️ شما مجاز به استفاده از این ربات نیستید.")
        return

    if query.data == "help":
        await query.edit_message_text(HELP_TEXT, parse_mode='Markdown')
        return

    if query.data == "status":
        await query.edit_message_text(build_status_text(query.from_user.id), parse_mode='Markdown')
        return

    if query.data == "support":
        text = f"🆘 برای پشتیبانی به {SUPPORT_USERNAME} پیام بدید." if SUPPORT_USERNAME else "🆘 پشتیبانی هنوز تنظیم نشده."
        await query.message.reply_text(text)
        return

    if query.data == "vip_info":
        await query.message.reply_text(
            f"💎 **اشتراک VIP** ({VIP_DURATION_DAYS} روز)\n\nروش پرداخت رو انتخاب کنید:",
            reply_markup=_vip_payment_keyboard(),
            parse_mode='Markdown'
        )
        return

    if query.data == "pay_stars":
        await send_stars_invoice(query.message.chat_id, query.from_user.id, context)
        return

    if query.data == "pay_rial":
        await start_card_payment(query, context)
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
        user_id = query.from_user.id
        user_has_unlimited = has_unlimited_access(user_id)

        reserved_slot = False
        if not user_has_unlimited:
            ok, current_count = try_acquire_download_slot(user_id, MAX_DAILY)
            if not ok:
                await query.edit_message_text(
                    f"❌ **محدودیت روزانه شما تمام شده!**\n"
                    f"شما امروز {current_count} بار دانلود کرده‌اید.\n"
                    f"از فردا دوباره امتحان کنید یا با /vip نامحدود بشید.",
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
                caption = "🎬 دانلود شد!"
            elif action == "a":
                filename = await download_audio(link, quality, update_progress)
                thumb = None
                caption = "🎵 فایل صوتی دانلود شد!"
            else:
                await query.edit_message_text("❌ عملیات نامعتبر.")
                return

            await safe_delete_message(progress_msg)
            progress_msg = None

            if AD_ENABLED and not user_has_unlimited:
                try:
                    await context.bot.send_message(chat_id=query.message.chat_id, text=AD_TEXT)
                except Exception as e:
                    logger.warning(f"failed to send ad: {e}")

            await send_large_file(
                context.bot,
                query.message.chat_id,
                filename,
                caption,
                thumb
            )
            sent_successfully = True

            try:
                save_history(user_id, link, quality, os.path.basename(filename))
            except Exception as e:
                logger.warning(f"save_history failed: {e}")

            await query.edit_message_text("✅ دانلود کامل شد!")

        except Exception as e:
            logger.error(f"download error: {e}")
            if reserved_slot and not sent_successfully:
                try:
                    release_download_slot(user_id)
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
app.add_handler(CommandHandler("support", support_command))
app.add_handler(CommandHandler("vip", vip_command))
app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
app.add_handler(MessageHandler(filters.PHOTO, receipt_photo_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(CallbackQueryHandler(callback_handler))

# ========== اجرا ==========
if __name__ == "__main__":
    app.run_polling()
