"""
Хендлер рейтинга пар: /top, переключение категорий (близость/богатство/дети).
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.leaderboard import TOP_CATEGORIES, TOP_CATEGORY_PREFIX, build_top_keyboard
from bot.services.achievement_service import award, format_unlock_text
from bot.services.leaderboard_service import get_top_by_affection, get_top_by_children, get_top_by_wealth

router = Router(name="leaderboard")

MEDALS = ["🥇", "🥈", "🥉"]

GETTERS = {
    "affection": get_top_by_affection,
    "wealth": get_top_by_wealth,
    "children": get_top_by_children,
}

UNITS = {
    "affection": "❤️",
    "wealth": "🪙",
    "children": "",
}


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


async def _render_leaderboard(
    chat_id: int, code: str, session: AsyncSession
) -> tuple[str, list]:
    """Возвращает (текст, список пользователей, только что получивших достижение #1)."""
    entries = await GETTERS[code](session, chat_id)
    label = TOP_CATEGORIES[code]
    unit = UNITS[code]

    if not entries:
        return f"{label}\n\nПока здесь пусто — ни одной пары в этой категории.", []

    lines = [label, ""]
    for i, entry in enumerate(entries):
        rel = entry.relationship
        place = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
        names = f"{_mention(rel.user1)} и {_mention(rel.user2)}"
        value_str = f"{entry.value} {unit}".strip()
        lines.append(f"{place} {names} — {value_str}")

    newly_unlocked = []
    top_relationship = entries[0].relationship
    for partner_user in (top_relationship.user1, top_relationship.user2):
        if await award(session, partner_user, "top_1"):
            newly_unlocked.append(partner_user)

    return "\n".join(lines), newly_unlocked


@router.message(Command("top"))
async def cmd_top(message: Message, session: AsyncSession):
    text, newly_unlocked = await _render_leaderboard(message.chat.id, "affection", session)
    await message.answer(text, reply_markup=build_top_keyboard("affection"))
    for user in newly_unlocked:
        await message.answer(f"{_mention(user)}\n{format_unlock_text('top_1')}")


@router.callback_query(F.data.startswith(TOP_CATEGORY_PREFIX))
async def on_top_category(callback: CallbackQuery, session: AsyncSession):
    code = callback.data.removeprefix(TOP_CATEGORY_PREFIX)
    text, newly_unlocked = await _render_leaderboard(callback.message.chat.id, code, session)
    await callback.message.edit_text(text, reply_markup=build_top_keyboard(code))
    for user in newly_unlocked:
        await callback.message.answer(f"{_mention(user)}\n{format_unlock_text('top_1')}")
    await callback.answer()
