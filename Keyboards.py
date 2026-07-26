from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def download_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🎬 Video", callback_data="video"),
            InlineKeyboardButton("🎵 MP3", callback_data="audio"),
        ]
    ]

    return InlineKeyboardMarkup(keyboard)
