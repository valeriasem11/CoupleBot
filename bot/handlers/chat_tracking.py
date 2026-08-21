"""
Отслеживание чатов, в которые добавлен бот, + служебная команда /chats,
доступная ТОЛЬКО владельцу бота (по числовому Telegram ID).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.bot_chat_service import (
    get_all_chats,
    mark_chat_inactive,
    refresh_chat_status,
    refresh_chat_title,
    upsert_chat,
)

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
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    was_active = old_status in _ACTIVE_STATUSES
    is_active = new_status in _ACTIVE_STATUSES

    if is_active and not was_active:
        await upsert_chat(
            session,
            chat_id=event.chat.id,
            chat_title=event.chat.title,
            chat_type=event.chat.type,
            member_status=new_status,
        )
    elif was_active and not is_active:
        await mark_chat_inactive(session, event.chat.id, member_status=new_status)
    elif is_active and was_active:
        # например, повысили/понизили из админов — статус поменялся, но бот всё ещё в чате
        await upsert_chat(
            session,
            chat_id=event.chat.id,
            chat_title=event.chat.title,
            chat_type=event.chat.type,
            member_status=new_status,
        )


@router.message(Command("chats"))
async def cmd_chats(message: Message, session: AsyncSession):
    if message.from_user.id != OWNER_TELEGRAM_ID:
        return  # молча игнорируем — не выдаём даже факт существования команды

    chats = await get_all_chats(session, active_only=True)

    if not chats:
        await message.answer("Бот пока не добавлен ни в один чат.")
        return

    # Дозапрашиваем названия и статус для чатов, у которых их ещё нет
    # (делаем это ДО фильтрации по типу — иначе тип личных чатов так и
    # останется "unknown" и они не смогут отсеяться на следующем шаге)
    for chat in chats:
        if chat.chat_title is None:
            await refresh_chat_title(session, message.bot, chat)
        if chat.member_status == "unknown":
            await refresh_chat_status(session, message.bot, chat)

    # Показываем только настоящие групповые чаты — личные диалоги с ботом не в счёт
    group_chats = [c for c in chats if c.chat_type in ("group", "supergroup")]

    if not group_chats:
        await message.answer("Бот пока не добавлен ни в один групповой чат.")
        return

    header = f"🤖 Беседы, где известен бот ({len(group_chats)})"
    entries = []
    for chat in group_chats:
        title = chat.chat_title or f"Чат {chat.chat_id}"
        updated = chat.updated_at.strftime("%d.%m.%Y %H:%M")
        entries.append(
            f"✅ {title}\n"
            f"ID: <code>{chat.chat_id}</code> · статус: {chat.member_status} · обновлено: {updated}"
        )

    await message.answer(header + "\n\n" + "\n".join(entries))

    # Один-единственный commit в самом конце — после того, как все атрибуты
    # уже прочитаны и превращены в текст, "затирание" (expire) объектов
    # после commit() больше не может ничему помешать.
    await session.commit()
