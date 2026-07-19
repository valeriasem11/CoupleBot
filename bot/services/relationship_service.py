"""
Бизнес-логика системы отношений: предложения, действия, прогрессия стадий,
вступление в брак.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    ActionLog,
    Relationship,
    RelationshipAction,
    RelationshipStage,
    RelationshipStatus,
    User,
)


class RelationshipError(Exception):
    """Ошибка бизнес-логики — текст сразу годится для показа пользователю."""


# ---------------------------------------------------------------------------
# Получение текущего состояния
# ---------------------------------------------------------------------------


async def get_active_relationship(session: AsyncSession, user_id: int) -> Relationship | None:
    """Текущая активная (ACTIVE или MARRIED) пара пользователя, если есть."""
    result = await session.execute(
        select(Relationship).where(
            or_(Relationship.user1_id == user_id, Relationship.user2_id == user_id),
            Relationship.status.in_([RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED]),
        )
    )
    return result.scalars().first()


async def get_relationship_by_id(session: AsyncSession, relationship_id: int) -> Relationship | None:
    result = await session.execute(
        select(Relationship).where(Relationship.id == relationship_id)
    )
    return result.scalar_one_or_none()


def get_partner(relationship: Relationship, user_id: int) -> User:
    """Второй участник пары (не user_id)."""
    return relationship.user2 if relationship.user1_id == user_id else relationship.user1


# ---------------------------------------------------------------------------
# Предложение отношений
# ---------------------------------------------------------------------------


async def create_proposal(session: AsyncSession, proposer: User, target: User) -> Relationship:
    if proposer.id == target.id:
        raise RelationshipError("Нельзя предложить отношения самой(ому) себе 🙂")

    if await get_active_relationship(session, proposer.id) is not None:
        raise RelationshipError("У тебя уже есть партнёр — сначала нужно расстаться, чтобы начать новые отношения.")

    if await get_active_relationship(session, target.id) is not None:
        raise RelationshipError("У этого человека уже есть партнёр.")

    result = await session.execute(
        select(Relationship).where(
            or_(
                and_(Relationship.user1_id == proposer.id, Relationship.user2_id == target.id),
                and_(Relationship.user1_id == target.id, Relationship.user2_id == proposer.id),
            ),
            Relationship.status == RelationshipStatus.PENDING,
        )
    )
    if result.scalars().first() is not None:
        raise RelationshipError("Предложение уже отправлено и ожидает ответа.")

    relationship = Relationship(
        user1_id=proposer.id,
        user2_id=target.id,
        status=RelationshipStatus.PENDING,
    )
    session.add(relationship)
    await session.commit()
    await session.refresh(relationship)
    return relationship


async def accept_proposal(session: AsyncSession, relationship: Relationship, chat_id: int) -> None:
    first_stage = await _get_stage_by_order(session, 1)

    relationship.status = RelationshipStatus.ACTIVE
    relationship.stage_id = first_stage.id
    relationship.affection_points = 0
    relationship.started_at = datetime.now(timezone.utc)
    relationship.chat_id = chat_id
    await session.commit()


async def reject_proposal(session: AsyncSession, relationship: Relationship) -> None:
    relationship.status = RelationshipStatus.REJECTED
    await session.commit()


@dataclass
class EndRelationshipResult:
    was_married: bool
    budget_split_each: int


async def end_relationship(session: AsyncSession, relationship: Relationship) -> EndRelationshipResult:
    """
    Разрывает отношения (расставание или развод). Дом/машина/дети остаются
    привязаны к этой (теперь неактивной) записи отношений и становятся
    недоступны — новая пара у каждого из партнёров начнётся с нуля.

    Семейный бюджет (если был брак) делится поровну между личными балансами.
    """
    was_married = relationship.status == RelationshipStatus.MARRIED
    budget_split_each = 0

    if was_married and relationship.family_budget > 0:
        budget_split_each = relationship.family_budget // 2
        relationship.user1.balance += budget_split_each
        relationship.user2.balance += budget_split_each
        relationship.family_budget = 0

    relationship.status = RelationshipStatus.DIVORCED
    await session.commit()

    return EndRelationshipResult(was_married=was_married, budget_split_each=budget_split_each)


# ---------------------------------------------------------------------------
# Действия пары
# ---------------------------------------------------------------------------


async def get_available_actions(session: AsyncSession, relationship: Relationship) -> list[RelationshipAction]:
    """Действия, доступные на текущей стадии пары (по возрастанию требуемых очков)."""
    current_order = relationship.stage.order
    result = await session.execute(
        select(RelationshipAction)
        .where(RelationshipAction.min_stage_order <= current_order)
        .order_by(RelationshipAction.affection_reward)
    )
    return list(result.scalars().all())


async def get_action_by_code(session: AsyncSession, code: str) -> RelationshipAction | None:
    result = await session.execute(
        select(RelationshipAction).where(RelationshipAction.code == code)
    )
    return result.scalar_one_or_none()


async def get_relationship_cooldown_remaining(
    session: AsyncSession, relationship_id: int
) -> timedelta | None:
    """
    Общий кулдаун пары: возвращает оставшееся время до следующего доступного
    действия (любого), основанное на кулдауне ПОСЛЕДНЕГО выполненного действия —
    неважно, кем из двоих партнёров и какое именно действие было выполнено.
    """
    result = await session.execute(
        select(ActionLog.used_at, RelationshipAction.cooldown_seconds)
        .join(RelationshipAction, RelationshipAction.code == ActionLog.action_code)
        .where(ActionLog.relationship_id == relationship_id)
        .order_by(ActionLog.used_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None

    last_used_at, cooldown_seconds = row
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_used_at + timedelta(seconds=cooldown_seconds)
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class ActionResult:
    new_affection_points: int
    stage_advanced: bool
    new_stage: RelationshipStage | None
    ready_for_marriage: bool


async def perform_action(
    session: AsyncSession,
    relationship: Relationship,
    action: RelationshipAction,
    performer_id: int,
) -> ActionResult:
    """
    Выполняет действие: логирует его, начисляет очки близости,
    проверяет и применяет автоматическую прогрессию стадии (кроме брака).

    Кулдаун должен быть проверен ЗАРАНЕЕ вызывающим кодом через
    get_action_cooldown_remaining.
    """
    session.add(
        ActionLog(
            relationship_id=relationship.id,
            action_code=action.code,
            performed_by_user_id=performer_id,
        )
    )
    relationship.affection_points += action.affection_reward

    stage_advanced, new_stage, ready_for_marriage = await _advance_stage_if_needed(session, relationship)

    await session.commit()

    return ActionResult(
        new_affection_points=relationship.affection_points,
        stage_advanced=stage_advanced,
        new_stage=new_stage,
        ready_for_marriage=ready_for_marriage,
    )


async def _advance_stage_if_needed(
    session: AsyncSession, relationship: Relationship
) -> tuple[bool, RelationshipStage | None, bool]:
    """
    Продвигает пару по стадиям автоматически, пока хватает очков — но НИКОГДА
    не переводит в стадию брака (is_marriage=True) автоматически, для этого
    нужна отдельная команда /marry с подтверждением партнёра.

    Возвращает (перешли_ли_на_новую_стадию, новая_стадия_или_None, готовы_ли_к_браку).
    """
    advanced = False
    latest_stage = relationship.stage

    while True:
        next_stage = await _get_stage_by_order(session, latest_stage.order + 1)
        if next_stage is None or next_stage.is_marriage:
            break
        if relationship.affection_points < next_stage.min_affection_points:
            break

        relationship.stage_id = next_stage.id
        latest_stage = next_stage
        advanced = True

    marriage_stage = await _get_marriage_stage(session)
    ready_for_marriage = (
        marriage_stage is not None
        and latest_stage.order == marriage_stage.order - 1
        and relationship.affection_points >= marriage_stage.min_affection_points
    )

    return advanced, (latest_stage if advanced else None), ready_for_marriage


# ---------------------------------------------------------------------------
# Брак
# ---------------------------------------------------------------------------


async def can_marry(session: AsyncSession, relationship: Relationship) -> bool:
    marriage_stage = await _get_marriage_stage(session)
    if marriage_stage is None:
        return False
    return (
        relationship.status == RelationshipStatus.ACTIVE
        and relationship.stage.order == marriage_stage.order - 1
        and relationship.affection_points >= marriage_stage.min_affection_points
    )


async def marry(session: AsyncSession, relationship: Relationship) -> None:
    marriage_stage = await _get_marriage_stage(session)
    if marriage_stage is None:
        raise RelationshipError("Стадия брака не настроена в справочнике.")

    relationship.stage_id = marriage_stage.id
    relationship.status = RelationshipStatus.MARRIED
    relationship.married_at = datetime.now(timezone.utc)
    await session.commit()


# ---------------------------------------------------------------------------
# Вспомогательные функции по справочнику стадий
# ---------------------------------------------------------------------------


async def _get_stage_by_order(session: AsyncSession, order: int) -> RelationshipStage | None:
    result = await session.execute(
        select(RelationshipStage).where(RelationshipStage.order == order)
    )
    return result.scalar_one_or_none()


async def _get_marriage_stage(session: AsyncSession) -> RelationshipStage | None:
    result = await session.execute(
        select(RelationshipStage).where(RelationshipStage.is_marriage.is_(True))
    )
    return result.scalar_one_or_none()


def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days} д {hours} ч"
    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"
