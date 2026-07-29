"""
Бизнес-логика анонимных сюрпризов/писем партнёру.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Relationship, User

SURPRISE_COOLDOWN = timedelta(hours=6)
SURPRISE_AFFECTION_REWARD = 10
MAX_SURPRISE_LENGTH = 300


class SurpriseError(Exception):
    """Ошибка бизнес-логики сюрпризов — текст готов для показа пользователю."""


def get_surprise_cooldown_remaining(user: User) -> timedelta | None:
    if user.surprise_last_sent_at is None:
        return None

    last_at = user.surprise_last_sent_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_at + SURPRISE_COOLDOWN
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class SurpriseResult:
    affection_gained: int
    new_affection: int


async def send_surprise(
    session: AsyncSession, relationship: Relationship, user: User, text: str
) -> SurpriseResult:
    """
    Отправляет анонимный сюрприз: начисляет близость паре и обновляет
    личный кулдаун отправителя. Проверка текста/кулдауна — на вызывающей стороне.
    """
    relationship.affection_points += SURPRISE_AFFECTION_REWARD
    user.surprise_last_sent_at = datetime.now(timezone.utc)

    await session.commit()

    return SurpriseResult(
        affection_gained=SURPRISE_AFFECTION_REWARD,
        new_affection=relationship.affection_points,
    )


def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"
