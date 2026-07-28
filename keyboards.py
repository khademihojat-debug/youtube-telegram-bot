from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_quality_keyboard(real_qualities=None):
    default_qualities = [360, 480, 720, 1080]
    allowed_qualities = [144, 240, 360, 480, 720, 1080, 1440, 2160]

    if real_qualities:
        usable = [q for q in allowed_qualities if q in set(int(x) for x in real_qualities)]
    else:
        usable = default_qualities

    rows = []
    current_row = []

    for quality in usable:
        current_row.append(
            InlineKeyboardButton(f"{quality}p", callback_data=f"q_{quality}")
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    rows.append(
        [
            InlineKeyboardButton("🎧 128kbps", callback_data="q_a128"),
            InlineKeyboardButton("🎧 320kbps", callback_data="q_a320"),
        ]
    )
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])

    return InlineKeyboardMarkup(rows)
