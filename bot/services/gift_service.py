"""
Бизнес-логика подарков партнёру. В отличие от /surprise — не анонимно
(в чате видно, кто подарил), оплата с личного баланса дарителя.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import GiftItem, Relationship, User

GIFT_COOLDOWN = timedelta(hours=3)


class GiftError(Exception):
    """Ошибка бизнес-логики подарков — текст готов для показа пользователю."""


async def get_all_gifts(session: AsyncSession) -> list[GiftItem]:
    result = await session.execute(select(GiftItem).order_by(GiftItem.order))
    return list(result.scalars().all())


async def get_gift_by_id(session: AsyncSession, gift_id: int) -> GiftItem | None:
    result = await session.execute(select(GiftItem).where(GiftItem.id == gift_id))
    return result.scalar_one_or_none()


def get_gift_cooldown_remaining(user: User) -> timedelta | None:
    if user.gift_last_sent_at is None:
        return None

    last_at = user.gift_last_sent_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_at + GIFT_COOLDOWN
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class GiftResult:
    affection_gained: int
    new_affection: int
    remaining_balance: int


async def send_gift(
    session: AsyncSession, relationship: Relationship, user: User, gift: GiftItem
) -> GiftResult:
    """
    Дарит подарок: списывает деньги с ЛИЧНОГО баланса дарителя, начисляет
    близость паре. Проверка кулдауна — на вызывающей стороне.
    """
    if user.balance < gift.price:
        raise GiftError(
            f"Недостаточно средств на балансе (нужно {gift.price} 🪙, доступно {user.balance} 🪙)."
        )

    user.balance -= gift.price
    user.gift_last_sent_at = datetime.now(timezone.utc)
    relationship.affection_points += gift.affection_reward

    await session.commit()

    return GiftResult(
        affection_gained=gift.affection_reward,
        new_affection=relationship.affection_points,
        remaining_balance=user.balance,
    )


def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"
