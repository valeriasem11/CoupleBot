"""
Бизнес-логика общих случайных событий на весь чат (например, "фестиваль
в городе") — временный бонус к близости для всех пар в этом чате разом.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ChatEvent, Relationship, RelationshipStatus

# ~раз в 2-3 дня на чат. Планировщик тикает каждые 5 минут и проверяет
# каждый "живой" чат независимо, поэтому вероятность калибруется под тик:
# среднее время ожидания ~ 2.5 дня = 720 тиков по 5 минут -> 1/720.
EVENT_CHANCE_PER_TICK = 0.0014
EVENT_DURATION = timedelta(hours=2)
EVENT_BONUS_PERCENT = 20

EVENT_TITLES = [
    "🎉 В городе начался фестиваль! Все действия с партнёром дают +{bonus}% близости следующие 2 часа!",
    "💖 Полнолуние сближает влюблённых! Бонус к близости +{bonus}% на 2 часа!",
    "🌸 В городе цветёт сакура, романтическое настроение витает в воздухе — +{bonus}% к близости на 2 часа!",
    "🎆 Городской салют зажигает искры чувств! +{bonus}% к близости на 2 часа!",
    "☕ Уютный дождливый вечер располагает к нежности — +{bonus}% к близости на 2 часа!",
]


async def get_active_event(session: AsyncSession, chat_id: int) -> ChatEvent | None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(ChatEvent)
        .where(ChatEvent.chat_id == chat_id, ChatEvent.expires_at > now)
        .order_by(ChatEvent.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_bonus_percent(session: AsyncSession, chat_id: int) -> int:
    """Удобный помощник: сразу возвращает процент бонуса (0, если события нет)."""
    event = await get_active_event(session, chat_id)
    return event.affection_bonus_percent if event else 0


@dataclass
class NewChatEvent:
    chat_id: int
    title: str


async def roll_random_events(session: AsyncSession) -> list[NewChatEvent]:
    """
    Один "тик" планировщика: для каждого "живого" чата (где есть хотя бы
    одна активная/семейная пара и ещё нет действующего события) с небольшой
    вероятностью запускает новое событие. Возвращает список запущенных
    событий — саму рассылку делает scheduler.py.
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

    new_events: list[NewChatEvent] = []
    now = datetime.now(timezone.utc)

    for chat_id in chat_ids:
        existing = await get_active_event(session, chat_id)
        if existing is not None:
            continue

        if random.random() >= EVENT_CHANCE_PER_TICK:
            continue

        title_template = random.choice(EVENT_TITLES)
        title = title_template.format(bonus=EVENT_BONUS_PERCENT)

        session.add(
            ChatEvent(
                chat_id=chat_id,
                title=title,
                affection_bonus_percent=EVENT_BONUS_PERCENT,
                expires_at=now + EVENT_DURATION,
            )
        )
        new_events.append(NewChatEvent(chat_id=chat_id, title=title))

    if new_events:
        await session.commit()

    return new_events
