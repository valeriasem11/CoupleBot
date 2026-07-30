"""
Бизнес-логика путешествий: покупка поездки из семейного бюджета (только в браке).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Relationship, RelationshipStatus, TravelDestination

TRAVEL_COOLDOWN = timedelta(hours=24)


class TravelError(Exception):
    """Ошибка бизнес-логики путешествий — текст готов для показа пользователю."""


async def get_all_destinations(session: AsyncSession) -> list[TravelDestination]:
    result = await session.execute(select(TravelDestination).order_by(TravelDestination.order))
    return list(result.scalars().all())


async def get_destination_by_id(session: AsyncSession, destination_id: int) -> TravelDestination | None:
    result = await session.execute(
        select(TravelDestination).where(TravelDestination.id == destination_id)
    )
    return result.scalar_one_or_none()


def get_travel_cooldown_remaining(relationship: Relationship) -> timedelta | None:
    if relationship.last_travel_at is None:
        return None

    last_at = relationship.last_travel_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_at + TRAVEL_COOLDOWN
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class TripResult:
    affection_gained: int
    new_affection: int
    new_budget: int


async def take_trip(
    session: AsyncSession, relationship: Relationship, destination: TravelDestination
) -> TripResult:
    if relationship.status != RelationshipStatus.MARRIED:
        raise TravelError("Путешествия доступны только в браке.")

    if relationship.family_budget < destination.price:
        raise TravelError(
            f"Недостаточно средств в семейном бюджете (нужно {destination.price} 🪙, "
            f"доступно {relationship.family_budget} 🪙)."
        )

    relationship.family_budget -= destination.price
    relationship.affection_points += destination.affection_reward
    relationship.last_travel_at = datetime.now(timezone.utc)

    await session.commit()

    return TripResult(
        affection_gained=destination.affection_reward,
        new_affection=relationship.affection_points,
        new_budget=relationship.family_budget,
    )


def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"
