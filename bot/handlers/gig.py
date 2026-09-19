"""
Хендлер ежедневных подработок: /gig
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.achievement_service import award, format_unlock_text
from bot.services.gig_service import GigError, perform_gig

router = Router(name="gig")

# С какой серии дней подряд выдаётся достижение
HANDYMAN_STREAK_THRESHOLD = 7


@router.message(Command("gig"))
async def cmd_gig(message: Message, session: AsyncSession):
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )

    try:
        result = await perform_gig(session, user)
    except GigError as e:
        await message.answer(str(e))
        return

    bonus_line = f" (+{result.bonus_percent}% за серию дней подряд)" if result.bonus_percent > 0 else ""
    text = (
        f"🧰 Подработка дня: {result.gig_emoji} {result.gig_name}\n\n"
        f"💰 Заработано: +{result.total_amount} 🪙{bonus_line}\n"
        f"🔥 Серия дней подряд: {result.streak}"
    )
    await message.answer(text)

    if result.streak >= HANDYMAN_STREAK_THRESHOLD:
        if await award(session, user, "handyman"):
            await message.answer(format_unlock_text("handyman"))
