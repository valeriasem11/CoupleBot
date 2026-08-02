"""
Отслеживание чатов, в которые добавлен бот, + служебная команда /chats,
доступная ТОЛЬКО владельцу бота (по числовому Telegram ID).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.bot_chat_service import get_all_chats, mark_chat_inactive, upsert_chat

router = Router(name="chat_tracking")

# Числовой Telegram ID владельца бота — только он может использовать /chats.
# Это не секретная информация (просто ID, не токен), поэтому хранится прямо в коде.
OWNER_TELEGRAM_ID = 828533150

# Статусы участника чата, которые считаются "бот реально в чате"
_ACTIVE_STATUSES = {"member", "administrator", "creator"}


@router.my_chat_member()
async def on_bot_membership_changed(event: ChatMemberUpdated, session: AsyncSession):
    """
    Срабатывает при любом изменении статуса бота в чате: добавили, удалили,
    выгнали, повысили до админа и т.д. Обновляет учёт чатов соответственно.
    """
    was_active = event.old_chat_member.status in _ACTIVE_STATUSES
    is_active = event.new_chat_member.status in _ACTIVE_STATUSES

    if is_active and not was_active:
        await upsert_chat(
            session,
            chat_id=event.chat.id,
            chat_title=event.chat.title,
            chat_type=event.chat.type,
        )
    elif was_active and not is_active:
        await mark_chat_inactive(session, event.chat.id)


@router.message(Command("chats"))
async def cmd_chats(message: Message, session: AsyncSession):
    if message.from_user.id != OWNER_TELEGRAM_ID:
        return  # молча игнорируем — не выдаём даже факт существования команды

    chats = await get_all_chats(session, active_only=True)

    if not chats:
        await message.answer("Бот пока не добавлен ни в один чат.")
        return

    lines = [f"📋 Чатов с ботом: {len(chats)}", ""]
    for chat in chats:
        title = chat.chat_title or "(без названия)"
        lines.append(f"• {title} — {chat.chat_id} ({chat.chat_type})")

    await message.answer("\n".join(lines))
