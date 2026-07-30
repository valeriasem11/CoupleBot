"""
Бизнес-логика годовщин: круглые даты "вместе" и "в браке" — бот сам
замечает их и поздравляет с бонусом близости.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Relationship, RelationshipStatus

# день -> бонус к близости
MILESTONE_BONUSES = {
    7: 10,
    30: 30,
    100: 75,
    365: 200,
    1000: 400,
}


def pluralize_days(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "дней"
    last_digit = n % 10
    if last_digit == 1:
        return "день"
    if 2 <= last_digit <= 4:
        return "дня"
    return "дней"


@dataclass
class AnniversaryEvent:
    chat_id: int
    title: str


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


async def process_anniversaries_tick(session: AsyncSession) -> list[AnniversaryEvent]:
    """
    Один "тик" планировщика: проверяет все активные/семейные пары на круглые
    даты (совместно и отдельно — в браке) и начисляет бонус близости.
    Каждая дата отмечается только один раз (см. last_*_anniversary).
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(Relationship).where(
            Relationship.chat_id.is_not(None),
            Relationship.status.in_([RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED]),
        )
    )
    relationships = result.scalars().all()

    events: list[AnniversaryEvent] = []
    changed = False

    for relationship in relationships:
        names = f"{_mention(relationship.user1)} и {_mention(relationship.user2)}"

        if relationship.started_at is not None:
            started_at = relationship.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            days_together = (now - started_at).days

            bonus = MILESTONE_BONUSES.get(days_together)
            if bonus is not None and relationship.last_together_anniversary != days_together:
                relationship.affection_points += bonus
                relationship.last_together_anniversary = days_together
                changed = True
                word = pluralize_days(days_together)
                events.append(
                    AnniversaryEvent(
                        chat_id=relationship.chat_id,
                        title=(
                            f"🎂 Годовщина! {names} — уже {days_together} {word} вместе!\n"
                            f"❤️ Бонус близости: +{bonus}"
                        ),
                    )
                )

        if relationship.status == RelationshipStatus.MARRIED and relationship.married_at is not None:
            married_at = relationship.married_at
            if married_at.tzinfo is None:
                married_at = married_at.replace(tzinfo=timezone.utc)
            days_married = (now - married_at).days

            bonus = MILESTONE_BONUSES.get(days_married)
            if bonus is not None and relationship.last_married_anniversary != days_married:
                relationship.affection_points += bonus
                relationship.last_married_anniversary = days_married
                changed = True
                word = pluralize_days(days_married)
                events.append(
                    AnniversaryEvent(
                        chat_id=relationship.chat_id,
                        title=(
                            f"💍 Годовщина свадьбы! {names} — уже {days_married} {word} в браке!\n"
                            f"❤️ Бонус близости: +{bonus}"
                        ),
                    )
                )

    if changed:
        await session.commit()

    return events
