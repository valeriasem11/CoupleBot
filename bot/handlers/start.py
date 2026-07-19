"""
Хендлер команды /start — точка входа для нового пользователя.
"""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )

    await message.answer(
        f"Привет, {user.first_name}! 👋\n\n"
        f"Добро пожаловать в игру отношений.\n"
        f"Твой баланс: {user.balance} 🪙\n\n"
        f"Доступные команды:\n"
        f"/job — выбрать работу\n"
        f"/work — пойти на смену (раз в 6 часов)\n"
        f"/balance — посмотреть баланс\n\n"
        f"/propose — предложить отношения (ответом на сообщение)\n"
        f"/actions — взаимодействовать с партнёром\n"
        f"/couple — профиль пары\n"
        f"/marry — сделать предложение руки и сердца\n"
        f"/breakup — расстаться / развестись\n\n"
        f"/budget — семейный бюджет (только в браке)\n"
        f"/deposit — положить деньги в бюджет\n"
        f"/withdraw — снять деньги из бюджета\n"
        f"/shop — магазин: дом, машина и игрушки для детей\n\n"
        f"/loan — взять кредит (до 15 000 🪙)\n"
        f"/repay — погасить кредит\n\n"
        f"/casino (ставка) — казино на слот 🎰 (мин. 100 🪙, кулдаун 5 минут)\n\n"
        f"/have_child — попробовать зачать ребёнка (только в браке)\n"
        f"/name_child (имя) — дать имя новорождённому\n"
        f"/children — список детей и их карточки\n"
        f"/child_actions — взаимодействовать с ребёнком"
    )


@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """
    Служебная команда: показывает числовой ID текущего чата.
    Полезно, если нужно вручную прописать relationships.chat_id в базе
    (например, для пары, созданной до того, как бот начал сохранять его сам).
    """
    await message.answer(f"ID этого чата: <code>{message.chat.id}</code>")
