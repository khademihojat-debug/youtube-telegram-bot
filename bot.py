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
from keyboards import download_keyboard

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

user_links = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user)

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Send me a YouTube link.",
    )
