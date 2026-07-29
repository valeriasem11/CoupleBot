"""
Клавиатуры питомцев: выбор вида при покупке, выбор действия.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PET_BUY_PREFIX = "pet_buy:"
PET_ACTION_PREFIX = "pet_action:"


def build_pet_species_keyboard(species_list) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{s.name} — {s.price} 🪙", callback_data=f"{PET_BUY_PREFIX}{s.id}"
            )
        ]
        for s in species_list
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_pet_actions_keyboard(actions: dict) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for code, action in actions.items():
        row.append(
            InlineKeyboardButton(
                text=f"{action['emoji']} {action['name']}",
                callback_data=f"{PET_ACTION_PREFIX}{code}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)
