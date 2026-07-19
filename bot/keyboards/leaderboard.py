"""
Клавиатура рейтинга пар: переключение между категориями.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOP_CATEGORY_PREFIX = "top_cat:"

TOP_CATEGORIES = {
    "affection": "❤️ Близость",
    "wealth": "💰 Богатство",
    "children": "👶 Дети",
}


def build_top_keyboard(active_code: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for code, label in TOP_CATEGORIES.items():
        text = f"• {label} •" if code == active_code else label
        row.append(InlineKeyboardButton(text=text, callback_data=f"{TOP_CATEGORY_PREFIX}{code}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)
