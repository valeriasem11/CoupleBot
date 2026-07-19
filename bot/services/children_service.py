"""
Бизнес-логика детей: зачатие, беременность, роды, присвоение имени.

Действия с ребёнком, угасание настроения и взросление — в следующем этапе.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import AgeStage, Child, ChildAction, ChildStatus, Gender, Relationship, RelationshipStatus, Toy

CONCEPTION_CHANCE = 0.20
CONCEPTION_COOLDOWN_AFTER_FAILURE = timedelta(hours=12)
CONCEPTION_COOLDOWN_AFTER_SUCCESS = timedelta(days=7)
PREGNANCY_DURATION = timedelta(days=3)

# Общий кулдаун между ЛЮБЫМИ действиями с одним и тем же ребёнком
CHILD_ACTION_COOLDOWN = timedelta(hours=6)
# Множитель награды, если у ребёнка есть черта, подходящая к действию
TRAIT_BONUS_MULTIPLIER = 1.2

# Взросление: сколько дней с рождения нужно на каждую стадию
AGE_STAGE_ORDER = [AgeStage.BABY, AgeStage.TODDLER, AgeStage.CHILD, AgeStage.TEEN]
DAYS_PER_AGE_STAGE = 7

# Угасание настроения без внимания
MOOD_DECAY_AMOUNT = 5
MOOD_DECAY_INTERVAL = timedelta(hours=6)
# Суммарное снижение угасания от игрушек не может превысить это значение —
# чтобы угасание никогда не обнулялось полностью
MAX_TOY_DECAY_REDUCTION = 0.7

# Случайные события: ~раз в 1-2 дня на ребёнка. Планировщик тикает каждые
# 5 минут, поэтому вероятность на один тик подобрана под средний интервал ~1.7 дня.
RANDOM_EVENT_CHANCE_PER_TICK = 0.002
RANDOM_EVENT_TEXTS = [
    "👶 {name} нарисовал(а) рисунок для родителей.",
    "👶 {name} собрал(а) домик из кубиков и гордо показывает его вам.",
    "👶 {name} спел(а) вам весёлую песенку.",
    "👶 {name} рассказал(а) смешную историю.",
]
EVENT_PRAISE_AFFECTION = 3
EVENT_GIFT_COST = 50
EVENT_GIFT_AFFECTION = 8
EVENT_GIFT_MOOD = 10

# Пул черт характера: (код, отображаемое название с эмодзи)
TRAIT_POOL = [
    ("cheerful", "😊 Весёлый"),
    ("kind", "🤝 Добрый"),
    ("curious", "🧠 Любознательный"),
    ("creative", "🎨 Творческий"),
    ("active", "⚽ Активный"),
    ("brave", "💪 Смелый"),
    ("musical", "🎵 Музыкальный"),
    ("caring", "🌱 Заботливый"),
]
TRAITS_PER_CHILD = 3

AGE_STAGE_LABELS = {
    AgeStage.BABY: "Младенец",
    AgeStage.TODDLER: "Малыш",
    AgeStage.CHILD: "Ребёнок",
    AgeStage.TEEN: "Подросток",
}


class ChildError(Exception):
    """Ошибка бизнес-логики детей — текст готов для показа пользователю."""


def trait_codes_to_labels(traits: str | None) -> list[str]:
    if not traits:
        return []
    codes = traits.split(",")
    lookup = dict(TRAIT_POOL)
    return [lookup.get(code, code) for code in codes]


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
# Зачатие
# ---------------------------------------------------------------------------


async def get_active_children_count(session: AsyncSession, relationship_id: int) -> int:
    """Считает детей, которые уже заняли место в доме (беременность + рождённые)."""
    result = await session.execute(
        select(Child).where(
            Child.relationship_id == relationship_id,
            Child.status.in_([ChildStatus.PREGNANT, ChildStatus.ALIVE]),
        )
    )
    return len(result.scalars().all())


def get_conception_cooldown_remaining(relationship: Relationship) -> timedelta | None:
    if relationship.last_conception_attempt_at is None:
        return None

    last_attempt = relationship.last_conception_attempt_at
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=timezone.utc)

    cooldown = (
        CONCEPTION_COOLDOWN_AFTER_SUCCESS
        if relationship.last_conception_was_success
        else CONCEPTION_COOLDOWN_AFTER_FAILURE
    )

    now = datetime.now(timezone.utc)
    ready_at = last_attempt + cooldown
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class ConceptionResult:
    success: bool
    child: Child | None


async def try_conceive(session: AsyncSession, relationship: Relationship) -> ConceptionResult:
    """
    Пробует зачать ребёнка. Проверки (брак, дом, свободное место, кулдаун)
    должны быть сделаны ЗАРАНЕЕ вызывающим кодом — эта функция только
    разыгрывает шанс и обновляет кулдаун попытки.
    """
    now = datetime.now(timezone.utc)
    success = random.random() < CONCEPTION_CHANCE

    relationship.last_conception_attempt_at = now
    relationship.last_conception_was_success = success

    child = None
    if success:
        child = Child(
            relationship_id=relationship.id,
            status=ChildStatus.PREGNANT,
            conceived_at=now,
            due_at=now + PREGNANCY_DURATION,
        )
        session.add(child)

    await session.commit()
    return ConceptionResult(success=success, child=child)


def ensure_can_try_conceive(relationship: Relationship, active_children_count: int) -> None:
    if relationship.status != RelationshipStatus.MARRIED:
        raise ChildError("Заводить детей можно только в браке.")
    if relationship.house is None:
        raise ChildError("Сначала нужно купить дом — загляните в /shop.")
    if active_children_count >= relationship.house.max_children:
        raise ChildError(
            f"В вашем доме («{relationship.house.name}») больше нет места для детей. "
            f"Купите дом побольше в /shop."
        )


# ---------------------------------------------------------------------------
# Роды (вызывается фоновым планировщиком)
# ---------------------------------------------------------------------------


async def get_due_pregnancies(session: AsyncSession) -> list[Child]:
    """Беременности, у которых подошёл срок родов. Использует фоновый планировщик."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Child).where(Child.status == ChildStatus.PREGNANT, Child.due_at <= now)
    )
    return list(result.scalars().all())


async def give_birth(session: AsyncSession, child: Child) -> None:
    """Оформляет роды: случайный пол, случайные черты характера, начальное настроение."""
    now = datetime.now(timezone.utc)
    child.status = ChildStatus.ALIVE
    child.born_at = now
    child.gender = random.choice([Gender.MALE, Gender.FEMALE])
    trait_codes = random.sample([code for code, _ in TRAIT_POOL], TRAITS_PER_CHILD)
    child.traits = ",".join(trait_codes)
    child.mood = 100
    child.age_stage = AgeStage.BABY
    child.last_mood_decay_at = now
    await session.commit()


# ---------------------------------------------------------------------------
# Присвоение имени
# ---------------------------------------------------------------------------


async def name_child(session: AsyncSession, relationship: Relationship, name: str) -> Child:
    """Присваивает имя самому старшему из ещё безымянных рождённых детей пары."""
    result = await session.execute(
        select(Child)
        .where(
            Child.relationship_id == relationship.id,
            Child.status == ChildStatus.ALIVE,
            Child.name.is_(None),
        )
        .order_by(Child.born_at.asc())
        .limit(1)
    )
    child = result.scalar_one_or_none()
    if child is None:
        raise ChildError("У вас нет ещё не названных детей.")

    child.name = name
    await session.commit()
    return child


# ---------------------------------------------------------------------------
# Список детей пары
# ---------------------------------------------------------------------------


async def get_child_by_id(session: AsyncSession, child_id: int) -> Child | None:
    result = await session.execute(select(Child).where(Child.id == child_id))
    return result.scalar_one_or_none()


async def get_children(session: AsyncSession, relationship_id: int) -> list[Child]:
    result = await session.execute(
        select(Child)
        .where(Child.relationship_id == relationship_id)
        .order_by(Child.conceived_at.asc())
    )
    return list(result.scalars().all())


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


# ---------------------------------------------------------------------------
# Взросление и угасание настроения (вызывается фоновым планировщиком)
# ---------------------------------------------------------------------------


@dataclass
class GrowthEvent:
    chat_id: int
    child_name: str
    new_stage_label: str


@dataclass
class RemovalEvent:
    chat_id: int
    child_name: str


@dataclass
class RandomEvent:
    chat_id: int
    child_id: int
    text: str


def _compute_target_age_stage(born_at: datetime, now: datetime) -> AgeStage:
    if born_at.tzinfo is None:
        born_at = born_at.replace(tzinfo=timezone.utc)
    days = (now - born_at).days
    index = min(days // DAYS_PER_AGE_STAGE, len(AGE_STAGE_ORDER) - 1)
    return AGE_STAGE_ORDER[index]


def _toy_decay_reduction(owned_toys: str | None, toy_reduction_map: dict[str, float]) -> float:
    if not owned_toys:
        return 0.0
    total = sum(toy_reduction_map.get(code, 0.0) for code in owned_toys.split(","))
    return min(total, MAX_TOY_DECAY_REDUCTION)


async def process_children_tick(
    session: AsyncSession,
) -> tuple[list[GrowthEvent], list[RemovalEvent], list[RandomEvent]]:
    """
    Один "тик" фонового планировщика: для всех живых детей проверяет взросление,
    угасание настроения (с учётом игрушек; при 0 — ребёнка забирают в детский
    дом), и с небольшой вероятностью генерирует случайное событие.

    Возвращает события для отправки уведомлений в чат — сама рассылка сообщений
    делается на уровне планировщика (bot.services.scheduler), не здесь.
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(select(Child).where(Child.status == ChildStatus.ALIVE))
    children = list(result.scalars().all())

    toy_result = await session.execute(select(Toy.code, Toy.mood_decay_reduction))
    toy_reduction_map = dict(toy_result.all())

    growth_events: list[GrowthEvent] = []
    removal_events: list[RemovalEvent] = []
    random_events: list[RandomEvent] = []

    for child in children:
        display_name = child.name or "Ваш ребёнок"
        relationship = child.relationship_
        removed = False

        # 1. Взросление
        target_stage = _compute_target_age_stage(child.born_at, now)
        if target_stage != child.age_stage:
            child.age_stage = target_stage
            if relationship.chat_id is not None:
                growth_events.append(
                    GrowthEvent(
                        chat_id=relationship.chat_id,
                        child_name=display_name,
                        new_stage_label=AGE_STAGE_LABELS[target_stage],
                    )
                )

        # 2. Угасание настроения (игрушки снижают скорость угасания)
        last_decay = child.last_mood_decay_at or child.born_at
        if last_decay.tzinfo is None:
            last_decay = last_decay.replace(tzinfo=timezone.utc)

        elapsed = now - last_decay
        periods = int(elapsed.total_seconds() // MOOD_DECAY_INTERVAL.total_seconds())

        if periods >= 1:
            reduction = _toy_decay_reduction(child.owned_toys, toy_reduction_map)
            amount_per_period = max(1, round(MOOD_DECAY_AMOUNT * (1 - reduction)))

            child.mood = max(0, child.mood - amount_per_period * periods)
            child.last_mood_decay_at = last_decay + periods * MOOD_DECAY_INTERVAL

            if child.mood <= 0:
                if relationship.chat_id is not None:
                    removal_events.append(
                        RemovalEvent(chat_id=relationship.chat_id, child_name=display_name)
                    )
                await session.delete(child)
                removed = True

        # 3. Случайное событие (не для тех, кого только что забрали)
        if not removed and relationship.chat_id is not None and random.random() < RANDOM_EVENT_CHANCE_PER_TICK:
            text = random.choice(RANDOM_EVENT_TEXTS).format(name=display_name)
            random_events.append(
                RandomEvent(chat_id=relationship.chat_id, child_id=child.id, text=text)
            )

    await session.commit()
    return growth_events, removal_events, random_events


# ---------------------------------------------------------------------------
# Действия с ребёнком
# ---------------------------------------------------------------------------


async def get_available_child_actions(session: AsyncSession, child: Child) -> list[ChildAction]:
    result = await session.execute(
        select(ChildAction)
        .where(ChildAction.stage == child.age_stage)
        .order_by(ChildAction.affection_reward)
    )
    return list(result.scalars().all())


async def get_child_action_by_code(session: AsyncSession, code: str) -> ChildAction | None:
    result = await session.execute(select(ChildAction).where(ChildAction.code == code))
    return result.scalar_one_or_none()


def get_child_action_cooldown_remaining(child: Child) -> timedelta | None:
    if child.last_interaction_at is None:
        return None

    last_at = child.last_interaction_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_at + CHILD_ACTION_COOLDOWN
    if now >= ready_at:
        return None
    return ready_at - now


@dataclass
class ChildActionResult:
    affection_gained: int
    mood_gained: int
    trait_bonus_applied: bool
    new_mood: int


async def perform_child_action(
    session: AsyncSession,
    relationship: Relationship,
    child: Child,
    action: ChildAction,
) -> ChildActionResult:
    """
    Выполняет действие с ребёнком: начисляет близость паре и настроение
    ребёнку (с бонусом, если подходит черта характера), обновляет кулдаун.

    Кулдаун должен быть проверен ЗАРАНЕЕ вызывающим кодом через
    get_child_action_cooldown_remaining.
    """
    child_traits = (child.traits or "").split(",")
    trait_bonus_applied = bool(action.bonus_trait) and action.bonus_trait in child_traits

    multiplier = TRAIT_BONUS_MULTIPLIER if trait_bonus_applied else 1.0
    affection_gained = round(action.affection_reward * multiplier)
    mood_gained = round(action.mood_reward * multiplier)

    relationship.affection_points += affection_gained
    child.mood = min(100, child.mood + mood_gained)
    now = datetime.now(timezone.utc)
    child.last_interaction_at = now
    child.last_mood_decay_at = now  # внимание сбрасывает отсчёт до следующего угасания

    await session.commit()

    return ChildActionResult(
        affection_gained=affection_gained,
        mood_gained=mood_gained,
        trait_bonus_applied=trait_bonus_applied,
        new_mood=child.mood,
    )


# ---------------------------------------------------------------------------
# Реакция на случайное событие: похвалить или подарить подарок
# ---------------------------------------------------------------------------


async def praise_child(session: AsyncSession, relationship: Relationship) -> int:
    """Похвалить — бесплатно, небольшая близость. Возвращает начисленную близость."""
    relationship.affection_points += EVENT_PRAISE_AFFECTION
    await session.commit()
    return EVENT_PRAISE_AFFECTION


async def gift_child(session: AsyncSession, relationship: Relationship, child: Child) -> None:
    """Подарить подарок — стоит денег из семейного бюджета, даёт больше близости и настроения."""
    if relationship.family_budget < EVENT_GIFT_COST:
        raise ChildError(
            f"Недостаточно средств в семейном бюджете (нужно {EVENT_GIFT_COST} 🪙, "
            f"доступно {relationship.family_budget} 🪙)."
        )

    relationship.family_budget -= EVENT_GIFT_COST
    relationship.affection_points += EVENT_GIFT_AFFECTION
    child.mood = min(100, child.mood + EVENT_GIFT_MOOD)
    await session.commit()


# ---------------------------------------------------------------------------
# Магазин игрушек
# ---------------------------------------------------------------------------


async def get_all_toys(session: AsyncSession) -> list[Toy]:
    result = await session.execute(select(Toy).order_by(Toy.order))
    return list(result.scalars().all())


async def get_toy_by_id(session: AsyncSession, toy_id: int) -> Toy | None:
    result = await session.execute(select(Toy).where(Toy.id == toy_id))
    return result.scalar_one_or_none()


async def buy_toy(session: AsyncSession, relationship: Relationship, child: Child, toy: Toy) -> None:
    if relationship.status != RelationshipStatus.MARRIED:
        raise ChildError("Магазин игрушек доступен только в браке.")

    owned = (child.owned_toys or "").split(",") if child.owned_toys else []
    if toy.code in owned:
        raise ChildError(f"Эта игрушка у {child.name or 'ребёнка'} уже есть.")

    if relationship.family_budget < toy.price:
        raise ChildError(
            f"Недостаточно средств в семейном бюджете (нужно {toy.price} 🪙, "
            f"доступно {relationship.family_budget} 🪙)."
        )

    relationship.family_budget -= toy.price
    owned.append(toy.code)
    child.owned_toys = ",".join(owned)
    await session.commit()


def toy_codes_to_labels(owned_toys: str | None) -> list[str]:
    if not owned_toys:
        return []
    result = []
    lookup = {t["code"]: t["name"] for t in _toy_lookup_source()}
    for code in owned_toys.split(","):
        result.append(lookup.get(code, code))
    return result


def _toy_lookup_source():
    from bot.database.seed import TOYS  # локальный импорт, чтобы избежать циклической зависимости
    return TOYS
