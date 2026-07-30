"""
Хендлер команды /stats — личная статистика игрока за всё время.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.stats_service import get_user_stats

router = Router(name="stats")


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession):
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )

    stats = await get_user_stats(session, user)

    relationship_line = "💞 Сейчас в отношениях" if stats.currently_in_relationship else "💔 Сейчас свободен(на)"

    lines = [
        f"📊 Статистика {user.first_name}",
        "",
        f"📅 В игре: {stats.days_since_registration} дн.",
        "",
        f"🪙 Баланс сейчас: {stats.balance} 🪙",
        f"💰 Заработано за всё время: {stats.lifetime_earned} 🪙",
        f"💼 Смен отработано за всё время: {stats.lifetime_work_count}",
        "",
        f"🎖️ Достижения: {stats.achievements_unlocked}/{stats.achievements_total}",
        "",
        relationship_line,
        f"💔 Расставаний/разводов пережито: {stats.past_breakups}",
    ]

    await message.answer("\n".join(lines))
