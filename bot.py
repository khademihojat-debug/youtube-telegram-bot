import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ---------------------- ENV VARIABLES ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # MUST be set manually in Railway

# ---------------------- LOGGING ----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

user_links = {}

# ---------------------- START COMMAND ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a YouTube link.")

# ---------------------- MESSAGE HANDLER ----------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message and update.message.text:
        text = update.message.text.strip()
    else:
        return

    if "youtube.com" not in text and "youtu.be" not in text:
        await update.message.reply_text("❌ Please send a valid YouTube link.")
        return

    user_links[update.effective_user.id] = text

    keyboard = [
        [
            InlineKeyboardButton("Download Video", callback_data="video"),
            InlineKeyboardButton("Download Audio", callback_data="audio")
        ]
    ]

    await update.message.reply_text(
        "Choose download type:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------- BUTTON HANDLER ----------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    link = user_links.get(user_id)

    if not link:
        await query.edit_message_text("❌ No link found. Send a YouTube link first.")
        return

    if query.data == "video":
