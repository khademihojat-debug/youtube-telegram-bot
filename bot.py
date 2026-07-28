from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

from downloader import (
    get_available_qualities,
    download_video,
    send_file_or_link
)

from keyboards import build_quality_keyboard

import os
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ---------------------------
# هندلر پیام‌های یوتیوب
# ---------------------------

async def handle_youtube(update, context):
    link = update.message.text.strip()

    # پیام اولیه
    await update.message.reply_text("🔍 در حال بررسی کیفیت‌های موجود...")

    # گرفتن کیفیت‌های واقعی
    real_qualities = get_available_qualities(link)

    if not real_qualities:
        await update.message.reply_text("❌ هیچ کیفیتی برای این ویدیو پیدا نشد.")
        return

    # ساخت دکمه‌ها بر اساس کیفیت‌های واقعی
    keyboard = build_quality_keyboard(real_qualities)

    await update.message.reply_text(
        "🎥 لطفاً کیفیت مورد نظر را انتخاب کن:",
        reply_markup=keyboard
    )

# ---------------------------
# هندلر دکمه‌ها
# ---------------------------

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("v_"):
        quality = int(data.split("_")[1])
        link = query.message.reply_to_message.text.strip()

        await query.message.reply_text(f"⏳ در حال دانلود {quality}p ...")

        file_path, thumb = await download_video(link, quality)

        await send_file_or_link(query, file_path, str(quality))

# ---------------------------
# اجرای ربات
# ---------------------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # هر پیام متنی → بررسی لینک یوتیوب
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube))

    # هندلر دکمه‌ها
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
