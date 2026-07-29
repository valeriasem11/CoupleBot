"""
Хендлер анонимных сюрпризов/писем партнёру: /surprise (текст).
"""
import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.achievement_service import award, format_unlock_text
from bot.services.relationship_service import get_active_relationship, get_partner
from bot.services.surprise_service import (
    MAX_SURPRISE_LENGTH,
    format_timedelta,
    get_surprise_cooldown_remaining,
    send_surprise,
)

router = Router(name="surprise")


async def _get_user(message, session: AsyncSession):
    return await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


@router.message(Command("surprise"))
async def cmd_surprise(message: Message, command: CommandObject, session: AsyncSession):
    if command.args is None or not command.args.strip():
        await message.answer(
            "Напиши текст сюрприза, например: /surprise Ты лучшее, что у меня есть 💕\n"
            f"(максимум {MAX_SURPRISE_LENGTH} символов)"
        )
        return

    text = command.args.strip()
    if len(text) > MAX_SURPRISE_LENGTH:
        await message.answer(f"Слишком длинно — максимум {MAX_SURPRISE_LENGTH} символов.")
        return

    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    remaining = get_surprise_cooldown_remaining(user)
    if remaining is not None:
        await message.answer(
            f"Ты уже отправляла сюрприз недавно. Следующий будет доступен через "
            f"{format_timedelta(remaining)}."
        )
        return

    partner = get_partner(relationship, user.id)
    result = await send_surprise(session, relationship, user, text)

    # Экранируем текст пользователя — бот использует HTML-разметку, и без
    # экранирования случайные символы вроде "<" могли бы сломать сообщение
    # или дать пользователю случайно/намеренно вставить свою HTML-разметку.
    safe_text = html.escape(text)

    await message.answer(
        f"🎁 {_mention(partner)}, для тебя оставили анонимную записку:\n\n"
        f"«{safe_text}»\n\n"
        f"❤️ Близость пары: +{result.affection_gained} (теперь {result.new_affection})"
    )

    if await award(session, user, "secret_admirer"):
        await message.answer(format_unlock_text("secret_admirer"))
