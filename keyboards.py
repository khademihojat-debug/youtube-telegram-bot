from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_quality_keyboard(real_qualities):
    AVAILABLE = [144, 240, 360, 480, 720, 1080]

    buttons = []
    for q in AVAILABLE:
        if q in real_qualities:
            buttons.append([
                InlineKeyboardButton(f"{q}p", callback_data=f"v_{q}")
            ])

    return InlineKeyboardMarkup(buttons)
