"""
Бизнес-логика "Счастливого часа" — временно повышает выплаты по /work и
/casino для всего чата (в отличие от ChatEvent, который повышает близость).
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import HappyHour, Relationship, RelationshipStatus

# ~раз в сутки на чат. Планировщик тикает каждые 5 минут (288 раз в сутки),
# поэтому вероятность на один тик подобрана под средний интервал ~1 день.
HAPPY_HOUR_CHANCE_PER_TICK = 0.0035
HAPPY_HOUR_DURATION = timedelta(hours=1)
HAPPY_HOUR_BONUS_PERCENT = 50


async def get_active_happy_hour_bonus_percent(session: AsyncSession, chat_id: int) -> int:
    """Возвращает текущий бонус (0, если счастливый час сейчас не идёт)."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(HappyHour)
        .where(HappyHour.chat_id == chat_id, HappyHour.expires_at > now)
        .order_by(HappyHour.started_at.desc())
        .limit(1)
    )
    happy_hour = result.scalar_one_or_none()
    return happy_hour.bonus_percent if happy_hour else 0


@dataclass
class NewHappyHourEvent:
    chat_id: int
    title: str


async def roll_random_happy_hours(session: AsyncSession) -> list[NewHappyHourEvent]:
    """
    Один "тик" планировщика: для каждого "живого" чата (где есть хотя бы
    одна активная/семейная пара и сейчас не идёт счастливый час) с небольшой
    вероятностью запускает новый. Возвращает список запущенных — саму
    рассылку делает scheduler.py.
    """
    result = await session.execute(
        select(Relationship.chat_id)
        .where(
            Relationship.chat_id.is_not(None),
            Relationship.status.in_([RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED]),
        )
        .distinct()
    )
    chat_ids = [row[0] for row in result.all()]

    new_events: list[NewHappyHourEvent] = []
    now = datetime.now(timezone.utc)

    for chat_id in chat_ids:
        current_bonus = await get_active_happy_hour_bonus_percent(session, chat_id)
        if current_bonus > 0:
            continue  # уже идёт

        if random.random() >= HAPPY_HOUR_CHANCE_PER_TICK:
            continue

        title = (
            f"⏰ Счастливый час начался! Следующий час — все выплаты за "
            f"работу и казино +{HAPPY_HOUR_BONUS_PERCENT}%!"
        )

        session.add(
            HappyHour(
                chat_id=chat_id,
                bonus_percent=HAPPY_HOUR_BONUS_PERCENT,
                expires_at=now + HAPPY_HOUR_DURATION,
            )
        )
        new_events.append(NewHappyHourEvent(chat_id=chat_id, title=title))

    if new_events:
        await session.commit()

    return new_events
