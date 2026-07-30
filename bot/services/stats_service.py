"""
Бизнес-логика личной статистики (/stats) — собирает воедино данные
из разных частей игры за всё время существования аккаунта.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.services.achievement_service import ACHIEVEMENTS, get_unlocked_codes
from bot.services.relationship_service import count_past_breakups, get_active_relationship


@dataclass
class UserStats:
    days_since_registration: int
    balance: int
    lifetime_earned: int
    lifetime_work_count: int
    achievements_unlocked: int
    achievements_total: int
    past_breakups: int
    currently_in_relationship: bool


async def get_user_stats(session: AsyncSession, user: User) -> UserStats:
    now = datetime.now(timezone.utc)
    created_at = user.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    days_since_registration = (now - created_at).days

    unlocked_codes = await get_unlocked_codes(session, user.id)
    past_breakups = await count_past_breakups(session, user.id)
    current_relationship = await get_active_relationship(session, user.id)

    return UserStats(
        days_since_registration=days_since_registration,
        balance=user.balance,
        lifetime_earned=user.lifetime_earned,
        lifetime_work_count=user.lifetime_work_count,
        achievements_unlocked=len(unlocked_codes),
        achievements_total=len(ACHIEVEMENTS),
        past_breakups=past_breakups,
        currently_in_relationship=current_relationship is not None,
    )
