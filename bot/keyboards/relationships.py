"""
Клавиатуры системы отношений: подтверждение предложения/брака, выбор действия.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.models import RelationshipAction

BREAKUP_CONFIRM_PREFIX = "breakup_confirm:"
BREAKUP_CANCEL_PREFIX = "breakup_cancel:"


def build_breakup_confirm_keyboard(relationship_id: int, initiator_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💔 Да, разорвать",
                    callback_data=f"{BREAKUP_CONFIRM_PREFIX}{relationship_id}:{initiator_user_id}",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"{BREAKUP_CANCEL_PREFIX}{relationship_id}:{initiator_user_id}",
                ),
            ]
        ]
    )


PROPOSAL_ACCEPT_PREFIX = "rel_accept:"
PROPOSAL_REJECT_PREFIX = "rel_reject:"

MARRY_ACCEPT_PREFIX = "marry_accept:"
MARRY_REJECT_PREFIX = "marry_reject:"

ACTION_PREFIX = "rel_action:"


def build_proposal_keyboard(relationship_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💖 Принять", callback_data=f"{PROPOSAL_ACCEPT_PREFIX}{relationship_id}"
                ),
                InlineKeyboardButton(
                    text="💔 Отклонить", callback_data=f"{PROPOSAL_REJECT_PREFIX}{relationship_id}"
                ),
            ]
        ]
    )


def build_marry_keyboard(relationship_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💍 Согласна(ен)", callback_data=f"{MARRY_ACCEPT_PREFIX}{relationship_id}"
                ),
                InlineKeyboardButton(
                    text="😔 Не готова(ов)", callback_data=f"{MARRY_REJECT_PREFIX}{relationship_id}"
                ),
            ]
        ]
    )


def build_actions_keyboard(actions: list[RelationshipAction]) -> InlineKeyboardMarkup:
    """Кнопки действий по две в ряд."""
    buttons = []
    row = []
    for action in actions:
        row.append(
            InlineKeyboardButton(text=action.name, callback_data=f"{ACTION_PREFIX}{action.code}")
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)
