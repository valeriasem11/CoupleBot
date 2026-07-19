"""
Хендлер команды /start — точка входа для нового пользователя.
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.keyboards.menu import (
    MENU_BACK,
    MENU_CATEGORY_PREFIX,
    build_category_back_keyboard,
    build_menu_keyboard,
    format_category_text,
)

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
        f"Выбери категорию, чтобы посмотреть команды:",
        reply_markup=build_menu_keyboard(),
    )


@router.callback_query(F.data.startswith(MENU_CATEGORY_PREFIX))
async def on_menu_category(callback: CallbackQuery):
    code = callback.data.removeprefix(MENU_CATEGORY_PREFIX)
    await callback.message.edit_text(
        format_category_text(code),
        reply_markup=build_category_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == MENU_BACK)
async def on_menu_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выбери категорию, чтобы посмотреть команды:",
        reply_markup=build_menu_keyboard(),
    )
    await callback.answer()


@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """
    Служебная команда: показывает числовой ID текущего чата.
    Полезно, если нужно вручную прописать relationships.chat_id в базе
    (например, для пары, созданной до того, как бот начал сохранять его сам).
    """
    await message.answer(f"ID этого чата: <code>{message.chat.id}</code>")
