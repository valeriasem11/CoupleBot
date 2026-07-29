"""
Бизнес-логика питомцев: покупка, действия, угасание настроения.

В отличие от детей — доступен без брака, покупается с личного баланса
того, кто заводит, без стадий взросления и без риска остаться без денег
у партнёра (списывается только с инициатора покупки).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Pet, PetSpecies, Relationship, RelationshipStatus, User

PET_ACTION_COOLDOWN = timedelta(hours=6)

# Угасание настроения питомца — вдвое медленнее, чем у детей (там -5 / 6ч)
MOOD_DECAY_AMOUNT = 5
MOOD_DECAY_INTERVAL = timedelta(hours=12)

# Действия с питомцем — единый набор, без деления по возрасту (питомец не растёт)
PET_ACTIONS = {
    "feed": {"emoji": "🍖", "name": "Покормить", "affection_reward": 3, "mood_reward": 15},
    "play": {"emoji": "🎾", "name": "Поиграть", "affection_reward": 3, "mood_reward": 15},
    "pet": {"emoji": "🖐️", "name": "Погладить", "affection_reward": 3, "mood_reward": 15},
}


class PetError(Exception):
    """Ошибка бизнес-логики питомцев — текст готов для показа пользователю."""


def mood_label(mood: int) -> str:
    if mood >= 80:
        return "Отличное"
    if mood >= 50:
        return "Хорошее"
    if mood >= 20:
        return "Так себе"
    if mood >= 1:
        return "Плохое"
    return "Критическое"


# ---------------------------------------------------------------------------
# Справочник видов
# ---------------------------------------------------------------------------


async def get_all_species(session: AsyncSession) -> list[PetSpecies]:
    result = await session.execute(select(PetSpecies).order_by(PetSpecies.order))
    return list(result.scalars().all())


async def get_species_by_id(session: AsyncSession, species_id: int) -> PetSpecies | None:
    result = await session.execute(select(PetSpecies).where(PetSpecies.id == species_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Питомец пары
# ---------------------------------------------------------------------------


async def get_pet(session: AsyncSession, relationship_id: int) -> Pet | None:
    result = await session.execute(select(Pet).where(Pet.relationship_id == relationship_id))
    return result.scalar_one_or_none()


async def adopt_pet(
    session: AsyncSession, relationship: Relationship, user: User, species: PetSpecies
) -> Pet:
    """Заводит питомца — списывает деньги с ЛИЧНОГО баланса инициатора."""
    if relationship.status not in (RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED):
        raise PetError("Заводить питомца можно, только когда вы вместе.")

    existing = await get_pet(session, relationship.id)
    if existing is not None:
        raise PetError(f"У вашей пары уже есть питомец — {existing.name}. Сначала позаботьтесь о нём!")

    if user.balance < species.price:
        raise PetError(
            f"Недостаточно средств на балансе (нужно {species.price} 🪙, доступно {user.balance} 🪙)."
        )

    user.balance -= species.price
    now = datetime.now(timezone.utc)
    pet = Pet(
        relationship_id=relationship.id,
        species_id=species.id,
        name=species.name.split(" ", 1)[-1] if " " in species.name else species.name,
        mood=100,
        last_mood_decay_at=now,
    )
    session.add(pet)
    await session.commit()
    await session.refresh(pet)
    return pet


async def rename_pet(session: AsyncSession, relationship_id: int, name: str) -> Pet:
    pet = await get_pet(session, relationship_id)
    if pet is None:
        raise PetError("У вашей пары пока нет питомца.")
    pet.name = name
    await session.commit()
    return pet


def get_pet_action_cooldown_remaining(pet: Pet) -> timedelta | None:
    if pet.last_interaction_at is None:
        return None

    last_at = pet.last_interaction_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_at + PET_ACTION_COOLDOWN
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class PetActionResult:
    affection_gained: int
    mood_gained: int
    new_mood: int


async def perform_pet_action(
    session: AsyncSession, relationship: Relationship, pet: Pet, action_code: str
) -> PetActionResult:
    action = PET_ACTIONS[action_code]

    relationship.affection_points += action["affection_reward"]
    pet.mood = min(100, pet.mood + action["mood_reward"])
    now = datetime.now(timezone.utc)
    pet.last_interaction_at = now
    pet.last_mood_decay_at = now  # внимание сбрасывает отсчёт до угасания

    await session.commit()

    return PetActionResult(
        affection_gained=action["affection_reward"],
        mood_gained=action["mood_reward"],
        new_mood=pet.mood,
    )


# ---------------------------------------------------------------------------
# Угасание настроения (вызывается фоновым планировщиком)
# ---------------------------------------------------------------------------


@dataclass
class PetRunAwayEvent:
    chat_id: int
    pet_name: str


async def process_pets_tick(session: AsyncSession) -> list[PetRunAwayEvent]:
    """
    Один "тик" планировщика: угасание настроения у всех питомцев.
    При падении до 0 — питомец убегает (запись удаляется).
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(select(Pet))
    pets = list(result.scalars().all())

    events: list[PetRunAwayEvent] = []

    for pet in pets:
        last_decay = pet.last_mood_decay_at or pet.adopted_at
        if last_decay.tzinfo is None:
            last_decay = last_decay.replace(tzinfo=timezone.utc)

        elapsed = now - last_decay
        periods = int(elapsed.total_seconds() // MOOD_DECAY_INTERVAL.total_seconds())

        if periods >= 1:
            pet.mood = max(0, pet.mood - MOOD_DECAY_AMOUNT * periods)
            pet.last_mood_decay_at = last_decay + periods * MOOD_DECAY_INTERVAL

            if pet.mood <= 0:
                relationship = pet.relationship_
                if relationship.chat_id is not None:
                    events.append(PetRunAwayEvent(chat_id=relationship.chat_id, pet_name=pet.name))
                await session.delete(pet)

    await session.commit()
    return events


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
