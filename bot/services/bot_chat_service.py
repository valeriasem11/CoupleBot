"""
Бизнес-логика учёта чатов, в которые добавлен бот.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import BotChat


async def upsert_chat(
    session: AsyncSession, chat_id: int, chat_title: str | None, chat_type: str, member_status: str
) -> None:
    """Отмечает чат как активный (бот в нём есть) — создаёт запись или обновляет существующую."""
    result = await session.execute(select(BotChat).where(BotChat.chat_id == chat_id))
    chat = result.scalar_one_or_none()

    if chat is None:
        session.add(
            BotChat(
                chat_id=chat_id,
                chat_title=chat_title,
                chat_type=chat_type,
                member_status=member_status,
                is_active=True,
            )
        )
    else:
        chat.chat_title = chat_title
        chat.chat_type = chat_type
        chat.member_status = member_status
        chat.is_active = True

    await session.commit()


async def mark_chat_inactive(session: AsyncSession, chat_id: int, member_status: str) -> None:
    """Отмечает чат как неактивный (бота удалили/он вышел) — запись не удаляется."""
    result = await session.execute(select(BotChat).where(BotChat.chat_id == chat_id))
    chat = result.scalar_one_or_none()
    if chat is not None:
        chat.is_active = False
        chat.member_status = member_status
        await session.commit()


async def refresh_chat_title(session: AsyncSession, bot, chat: BotChat) -> None:
    """
    Если название чата неизвестно (например, восстановлено из старых данных
    без названия) — пробует "дозапросить" его у Telegram через Bot API.
    Молча ничего не делает, если это не получилось (бота могли уже удалить).
    """
    if chat.chat_title is not None:
        return
    try:
        tg_chat = await bot.get_chat(chat.chat_id)
        chat.chat_title = tg_chat.title or tg_chat.full_name or chat.chat_title
        chat.chat_type = tg_chat.type
        await session.commit()
    except Exception:
        pass  # бот мог быть удалён из чата, доступ пропал и т.п. — не критично


async def refresh_chat_status(session: AsyncSession, bot, chat: BotChat) -> None:
    """
    Если статус бота в чате неизвестен (запись пришла из "довосстановления"
    старых данных, а не от живого события смены статуса) — дозапрашивает
    его напрямую у Telegram.
    """
    if chat.member_status != "unknown":
        return
    try:
        member = await bot.get_chat_member(chat.chat_id, bot.id)
        chat.member_status = member.status
        await session.commit()
    except Exception:
        pass  # бот мог быть удалён из чата, доступ пропал и т.п. — не критично


async def get_all_chats(session: AsyncSession, active_only: bool = True) -> list[BotChat]:
    query = select(BotChat).order_by(BotChat.added_at.desc())
    if active_only:
        query = query.where(BotChat.is_active.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def backfill_known_chats(session: AsyncSession) -> None:
    """
    Разово (но безопасно при каждом запуске — просто ничего не сделает
    повторно) подтягивает chat_id, уже сохранённые у пар и пользователей
    ДО появления этой функции — чтобы /chats не был пустым для старых чатов,
    в которые бота никто не добавлял и не удалял заново после обновления.
    """
    from bot.database.models import Relationship, User  # локальный импорт — во избежание цикличности

    result1 = await session.execute(
        select(Relationship.chat_id).where(Relationship.chat_id.is_not(None)).distinct()
    )
    result2 = await session.execute(
        select(User.chat_id).where(User.chat_id.is_not(None)).distinct()
    )
    chat_ids = {row[0] for row in result1.all()} | {row[0] for row in result2.all()}

    if not chat_ids:
        return

    existing_result = await session.execute(select(BotChat.chat_id))
    already_known = {row[0] for row in existing_result.all()}

    new_ids = chat_ids - already_known
    for chat_id in new_ids:
        session.add(BotChat(chat_id=chat_id, chat_title=None, chat_type="unknown", is_active=True))

    if new_ids:
        await session.commit()
