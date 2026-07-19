"""
Клавиатуры для действий с детьми: выбор ребёнка (если их несколько), выбор действия.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.models import Child, ChildAction
from bot.keyboards.shop import SHOP_MENU_PREFIX

PICK_CHILD_PREFIX = "pick_child:"
CHILD_ACTION_PREFIX = "child_action:"
PICK_CHILD_TOY_PREFIX = "pick_child_toy:"
BUY_TOY_PREFIX = "buy_toy:"
EVENT_PRAISE_PREFIX = "event_praise:"
EVENT_GIFT_PREFIX = "event_gift:"


def build_pick_child_keyboard(children: list[Child]) -> InlineKeyboardMarkup:
    buttons = []
    for child in children:
        label = child.name or "Без имени"
        emoji = "👦" if child.gender and child.gender.value == "male" else "👧"
        buttons.append(
            [InlineKeyboardButton(text=f"{emoji} {label}", callback_data=f"{PICK_CHILD_PREFIX}{child.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_child_actions_keyboard(child_id: int, actions: list[ChildAction]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for action in actions:
        row.append(
            InlineKeyboardButton(
                text=action.name, callback_data=f"{CHILD_ACTION_PREFIX}{child_id}:{action.code}"
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_pick_child_for_toy_keyboard(children: list[Child]) -> InlineKeyboardMarkup:
    buttons = []
    for child in children:
        label = child.name or "Без имени"
        emoji = "👦" if child.gender and child.gender.value == "male" else "👧"
        buttons.append(
            [InlineKeyboardButton(text=f"{emoji} {label}", callback_data=f"{PICK_CHILD_TOY_PREFIX}{child.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_toy_shop_keyboard(child_id: int, toys: list, owned_codes: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for toy in toys:
        mark = "✅ " if toy.code in owned_codes else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{toy.name} — {toy.price} 🪙 (-{int(toy.mood_decay_reduction * 100)}% угасания)",
                    callback_data=f"{BUY_TOY_PREFIX}{child_id}:{toy.id}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=SHOP_MENU_PREFIX)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_event_keyboard(child_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️ Похвалить", callback_data=f"{EVENT_PRAISE_PREFIX}{child_id}"),
                InlineKeyboardButton(text="🎁 Подарить подарок", callback_data=f"{EVENT_GIFT_PREFIX}{child_id}"),
            ]
        ]
    )
