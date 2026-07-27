from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_quality_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("360p", callback_data="q_360"),
            InlineKeyboardButton("480p", callback_data="q_480"),
        ],
        [
            InlineKeyboardButton("720p", callback_data="q_720"),
            InlineKeyboardButton("1080p", callback_data="q_1080"),
        ],
        [
            InlineKeyboardButton("4K", callback_data="q_2160"),
        ],
        [
            InlineKeyboardButton("🎧 128kbps", callback_data="q_a128"),
            InlineKeyboardButton("🎧 320kbps", callback_data="q_a320"),
        ],
        [
            InlineKeyboardButton("❌ لغو", callback_data="cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
