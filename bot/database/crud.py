"""
Базовые функции работы с БД. По мере роста проекта разложим их
по разным сервисам (relationship_service.py, economy_service.py и т.д.),
но для старта держим всё в одном месте.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Job, User


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str,
    chat_id: int | None = None,
) -> User:
    """
    Возвращает существующего пользователя по telegram_id,
    либо создаёт нового, если он пишет боту впервые.

    chat_id — чат, откуда пришло текущее сообщение; сохраняется как
    "домашний чат" пользователя для личных уведомлений (например, про кредит).
    """
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            balance=0,
            chat_id=chat_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        # обновляем username/имя/домашний чат на случай, если что-то поменялось
        changed = False
        if user.username != username:
            user.username = username
            changed = True
        if user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if chat_id is not None and user.chat_id != chat_id:
            user.chat_id = chat_id
            changed = True
        if changed:
            await session.commit()

    return user


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    # username в Telegram нечувствителен к регистру, поэтому сравниваем через ilike
    result = await session.execute(
        select(User).where(User.username.ilike(username))
    )
    return result.scalar_one_or_none()


async def get_all_jobs(session: AsyncSession) -> list[Job]:
    result = await session.execute(select(Job).order_by(Job.id))
    return list(result.scalars().all())


async def get_job_by_id(session: AsyncSession, job_id: int) -> Job | None:
    result = await session.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def set_user_job(session: AsyncSession, user: User, job: Job) -> None:
    """Назначает пользователю выбранную работу."""
    user.job_id = job.id
    await session.commit()
