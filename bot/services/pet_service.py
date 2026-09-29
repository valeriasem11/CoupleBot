"""
Бизнес-логика питомцев: покупка, действия, угасание настроения.

В отличие от детей — доступен без брака, покупается с личного баланса
того, кто заводит, без стадий взросления и без риска остаться без денег
у партнёра (списывается только с инициатора покупки).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Pet, PetSpecies, Relationship, RelationshipStatus, User

PET_ACTION_COOLDOWN = timedelta(hours=6)

# Угасание настроения питомца — вдвое медленнее, чем у детей (там -5 / 6ч)
MOOD_DECAY_AMOUNT = 5
MOOD_DECAY_INTERVAL = timedelta(hours=12)

# Возврат сбежавшего питомца
POSTER_SEARCH_WAIT = timedelta(hours=12)  # бесплатный вариант — "расклеить объявления"
POSTER_SEARCH_CHANCE = 0.6
POSTER_SEARCH_RETURN_MOOD = 30
PAID_SEARCH_COST = 300  # платный вариант — мгновенно, но за деньги
PAID_SEARCH_RETURN_MOOD = 50
MISSING_ABANDON_TIMEOUT = timedelta(hours=24)  # если вообще никто не выбрал способ поиска

PET_SEARCH_POSTER_PREFIX = "pet_search_poster:"
PET_SEARCH_PAID_PREFIX = "pet_search_paid:"

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


async def get_pets(session: AsyncSession, relationship_id: int) -> list[Pet]:
    """Все питомцы пары, в порядке появления (первый заведённый — первый в списке)."""
    result = await session.execute(
        select(Pet).where(Pet.relationship_id == relationship_id).order_by(Pet.adopted_at)
    )
    return list(result.scalars().all())


def get_pet_limit(relationship: Relationship) -> int:
    """
    Сколько питомцев можно завести этой паре. Без дома (или пока просто
    не в браке) — всегда 1. С домом — по вместимости дома (max_pets).
    """
    if relationship.house is not None:
        return relationship.house.max_pets
    return 1


async def adopt_pet(
    session: AsyncSession, relationship: Relationship, user: User, species: PetSpecies
) -> Pet:
    """Заводит питомца — списывает деньги с ЛИЧНОГО баланса инициатора."""
    if relationship.status not in (RelationshipStatus.ACTIVE, RelationshipStatus.MARRIED):
        raise PetError("Заводить питомца можно, только когда вы вместе.")

    existing_pets = await get_pets(session, relationship.id)
    limit = get_pet_limit(relationship)

    if len(existing_pets) >= limit:
        if relationship.house is None:
            raise PetError(
                f"У вашей пары уже есть питомец. Без дома можно завести только одного — "
                f"купите дом в /shop, чтобы заводить больше."
            )
        raise PetError(
            f"У вашей пары уже максимум питомцев для текущего дома ({limit}). "
            f"Нужен дом побольше — загляните в /shop."
        )

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


async def rename_pet(session: AsyncSession, pet: Pet, name: str) -> Pet:
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


# ---------------------------------------------------------------------------
# Возврат сбежавшего питомца
# ---------------------------------------------------------------------------


async def get_pet_by_id(session: AsyncSession, pet_id: int) -> Pet | None:
    result = await session.execute(select(Pet).where(Pet.id == pet_id))
    return result.scalar_one_or_none()


async def choose_poster_search(session: AsyncSession, pet: Pet) -> None:
    """
    Бесплатный вариант — "расклеить объявления". Сам результат не решается
    сразу, а разыгрывается позже планировщиком (см. process_missing_pets_tick),
    когда пройдёт POSTER_SEARCH_WAIT.
    """
    if not pet.is_missing:
        raise PetError("Этот питомец сейчас не пропадал.")
    if pet.search_method is not None:
        raise PetError("Вы уже выбрали способ поиска — просто подождите вестей.")

    pet.search_method = "poster"
    await session.commit()


async def pay_for_search(session: AsyncSession, pet: Pet, user: User) -> int:
    """
    Платный вариант — нанять поисковика. Решается мгновенно и всегда
    успешно (списывается PAID_SEARCH_COST с личного баланса user).
    Возвращает новое настроение питомца.
    """
    if not pet.is_missing:
        raise PetError("Этот питомец сейчас не пропадал.")
    if user.balance < PAID_SEARCH_COST:
        raise PetError(
            f"Недостаточно средств (нужно {PAID_SEARCH_COST} 🪙, доступно {user.balance} 🪙)."
        )

    user.balance -= PAID_SEARCH_COST
    pet.is_missing = False
    pet.search_method = None
    pet.missing_since = None
    pet.mood = PAID_SEARCH_RETURN_MOOD

    await session.commit()
    return pet.mood


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
    pet_id: int
    pet_name: str


async def process_pets_tick(session: AsyncSession) -> list[PetRunAwayEvent]:
    """
    Один "тик" планировщика: угасание настроения у всех питомцев.
    При падении до 0 — питомец "пропадает" (is_missing=True), но НЕ удаляется
    сразу: хозяева получат сообщение с выбором, как попробовать его вернуть
    (см. choose_poster_search / pay_for_search и process_missing_pets_tick).
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(select(Pet).where(Pet.is_missing.is_(False)))
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
                pet.is_missing = True
                pet.missing_since = now
                if relationship.chat_id is not None:
                    events.append(
                        PetRunAwayEvent(chat_id=relationship.chat_id, pet_id=pet.id, pet_name=pet.name)
                    )

    await session.commit()
    return events


@dataclass
class PetFoundEvent:
    chat_id: int
    pet_name: str


@dataclass
class PetLostForeverEvent:
    chat_id: int
    pet_name: str
    abandoned: bool  # True, если никто вообще не выбрал способ поиска


async def process_missing_pets_tick(
    session: AsyncSession,
) -> tuple[list[PetFoundEvent], list[PetLostForeverEvent]]:
    """
    Один "тик" планировщика для пропавших питомцев:
    - если выбраны "объявления" и прошло POSTER_SEARCH_WAIT — разыгрывает шанс;
    - если ничего не выбрали за MISSING_ABANDON_TIMEOUT — питомец теряется навсегда.
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(select(Pet).where(Pet.is_missing.is_(True)))
    missing_pets = list(result.scalars().all())

    found_events: list[PetFoundEvent] = []
    lost_events: list[PetLostForeverEvent] = []
    changed = False

    for pet in missing_pets:
        missing_since = pet.missing_since
        if missing_since is None:
            continue
        if missing_since.tzinfo is None:
            missing_since = missing_since.replace(tzinfo=timezone.utc)
        elapsed = now - missing_since

        relationship = pet.relationship_
        chat_id = relationship.chat_id if relationship else None

        if pet.search_method == "poster" and elapsed >= POSTER_SEARCH_WAIT:
            changed = True
            if random.random() < POSTER_SEARCH_CHANCE:
                pet.is_missing = False
                pet.search_method = None
                pet.missing_since = None
                pet.mood = POSTER_SEARCH_RETURN_MOOD
                if chat_id is not None:
                    found_events.append(PetFoundEvent(chat_id=chat_id, pet_name=pet.name))
            else:
                if chat_id is not None:
                    lost_events.append(
                        PetLostForeverEvent(chat_id=chat_id, pet_name=pet.name, abandoned=False)
                    )
                await session.delete(pet)

        elif pet.search_method is None and elapsed >= MISSING_ABANDON_TIMEOUT:
            changed = True
            if chat_id is not None:
                lost_events.append(
                    PetLostForeverEvent(chat_id=chat_id, pet_name=pet.name, abandoned=True)
                )
            await session.delete(pet)

    if changed:
        await session.commit()

    return found_events, lost_events


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
