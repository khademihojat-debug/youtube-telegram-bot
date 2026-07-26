import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN
from database import init_db, add_user
from downloader import download_video, download_audio
from keyboards import download_keyboard

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

user_links = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user)

    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if "youtube.com" not in text and "youtu.be" not in text:
        await update.message.reply_text(
            "❌ Please send a valid YouTube link."
        )
        return

    user_links[update.effective_user.id] = text

    await update.message.reply_text(
        "Choose download type:",
        reply_markup=download_keyboard()
    )

    async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )

    print("Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()

    url = user_links.get(query.from_user.id)

    if not url:
        await query.message.reply_text("❌ Link not found.")
        return

    await query.message.reply_text("⏳ Downloading...")

    try:
        if query.data == "video":
            result = download_video(url)

            with open(result["file"], "rb") as video:
                await query.message.reply_video(
                    video=video,
                    caption=result["title"]
                )

        elif query.data == "audio":
            result = download_audio(url)

            with open(result["file"], "rb") as audio:
                await query.message.reply_audio(
                    audio=audio,
                    title=result["title"]
                )

    except Exception as e:
        await query.message.reply_text(f"❌ Error:\n{e}")

    await update.message.reply_text(
        "👋 Welcome!\n\nSend me a YouTube link."
    )


