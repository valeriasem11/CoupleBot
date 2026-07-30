"""
Клавиатура выбора направления для путешествия.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TRAVEL_BUY_PREFIX = "travel_buy:"


def build_travel_keyboard(destinations) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{d.name} — {d.price} 🪙 (+{d.affection_reward} ❤️)",
                callback_data=f"{TRAVEL_BUY_PREFIX}{d.id}",
            )
        ]
        for d in destinations
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
