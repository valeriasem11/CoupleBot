"""
Бизнес-логика рейтинга пар (/top) — в рамках одной беседы (chat_id).
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Child, ChildStatus, Relationship, RelationshipStatus, User

TOP_LIMIT = 10


@dataclass
class LeaderboardEntry:
    relationship: Relationship
    value: int


async def get_top_by_affection(session: AsyncSession, chat_id: int) -> list[LeaderboardEntry]:
    result = await session.execute(
        select(Relationship)
        .where(
            Relationship.chat_id == chat_id,
            Relationship.status.in_([RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED]),
        )
        .order_by(Relationship.affection_points.desc())
        .limit(TOP_LIMIT)
    )
    relationships = result.scalars().all()
    return [LeaderboardEntry(relationship=r, value=r.affection_points) for r in relationships]


async def get_top_by_wealth(session: AsyncSession, chat_id: int) -> list[LeaderboardEntry]:
    """Богатство = личные балансы обоих партнёров + семейный бюджет (если есть)."""
    result = await session.execute(
        select(Relationship)
        .where(
            Relationship.chat_id == chat_id,
            Relationship.status.in_([RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED]),
        )
    )
    relationships = result.scalars().all()

    entries = [
        LeaderboardEntry(
            relationship=r,
            value=r.user1.balance + r.user2.balance + r.family_budget,
        )
        for r in relationships
    ]
    entries.sort(key=lambda e: e.value, reverse=True)
    return entries[:TOP_LIMIT]


async def get_top_by_children(session: AsyncSession, chat_id: int) -> list[LeaderboardEntry]:
    result = await session.execute(
        select(
            Relationship,
            func.count(Child.id).label("children_count"),
        )
        .join(Child, Child.relationship_id == Relationship.id, isouter=True)
        .where(
            Relationship.chat_id == chat_id,
            Relationship.status == RelationshipStatus.MARRIED,
        )
        .where((Child.status == ChildStatus.ALIVE) | (Child.status.is_(None)))
        .group_by(Relationship.id)
        .order_by(func.count(Child.id).desc())
        .limit(TOP_LIMIT)
    )
    rows = result.all()
    return [LeaderboardEntry(relationship=r, value=count) for r, count in rows]
