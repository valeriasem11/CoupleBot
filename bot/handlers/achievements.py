"""
Хендлер команды /achievements — список достижений и прогресс их разблокировки.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.achievement_service import get_all_achievements_status

router = Router(name="achievements")


@router.message(Command("achievements"))
async def cmd_achievements(message: Message, session: AsyncSession):
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )

    achievements = await get_all_achievements_status(session, user.id)
    unlocked_count = sum(1 for a in achievements if a.unlocked)

    lines = [f"🎖️ Достижения ({unlocked_count}/{len(achievements)})", ""]
    for a in achievements:
        if a.unlocked:
            lines.append(f"{a.emoji} {a.name} — {a.description}")
        else:
            lines.append(f"🔒 ??? — {a.description}")

    await message.answer("\n".join(lines))
