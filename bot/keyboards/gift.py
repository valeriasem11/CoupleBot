"""
Клавиатура выбора подарка партнёру.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

GIFT_BUY_PREFIX = "gift_buy:"


def build_gift_keyboard(gifts) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{g.name} — {g.price} 🪙 (+{g.affection_reward} ❤️)",
                callback_data=f"{GIFT_BUY_PREFIX}{g.id}",
            )
        ]
        for g in gifts
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
