"""
Бизнес-логика семейного бюджета и магазина (дом, машина).

Все операции доступны только для пар в браке (RelationshipStatus.MARRIED) —
семейный бюджет как отдельный кошелёк появляется именно со свадьбы.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Car, House, Relationship, RelationshipStatus, User


class FamilyError(Exception):
    """Ошибка бизнес-логики семейного бюджета/магазина — текст готов для показа пользователю."""


def _ensure_married(relationship: Relationship) -> None:
    if relationship.status != RelationshipStatus.MARRIED:
        raise FamilyError("Семейный бюджет и магазин доступны только в браке.")


# ---------------------------------------------------------------------------
# Семейный бюджет: пополнение и снятие
# ---------------------------------------------------------------------------


async def deposit_to_family_budget(
    session: AsyncSession, relationship: Relationship, user: User, amount: int
) -> None:
    _ensure_married(relationship)

    if amount <= 0:
        raise FamilyError("Сумма должна быть больше нуля.")
    if user.balance < amount:
        raise FamilyError(f"Недостаточно средств на личном балансе (доступно {user.balance} 🪙).")

    user.balance -= amount
    relationship.family_budget += amount
    await session.commit()


async def withdraw_from_family_budget(
    session: AsyncSession, relationship: Relationship, user: User, amount: int
) -> None:
    _ensure_married(relationship)

    if amount <= 0:
        raise FamilyError("Сумма должна быть больше нуля.")
    if relationship.family_budget < amount:
        raise FamilyError(f"Недостаточно средств в семейном бюджете (доступно {relationship.family_budget} 🪙).")

    relationship.family_budget -= amount
    user.balance += amount
    await session.commit()


# ---------------------------------------------------------------------------
# Магазин: дома
# ---------------------------------------------------------------------------


async def get_all_houses(session: AsyncSession) -> list[House]:
    result = await session.execute(select(House).order_by(House.order))
    return list(result.scalars().all())


async def get_house_by_id(session: AsyncSession, house_id: int) -> House | None:
    result = await session.execute(select(House).where(House.id == house_id))
    return result.scalar_one_or_none()


async def buy_house(session: AsyncSession, relationship: Relationship, house: House) -> None:
    _ensure_married(relationship)

    if relationship.house_id == house.id:
        raise FamilyError("У вашей пары уже есть именно этот дом.")
    if relationship.family_budget < house.price:
        raise FamilyError(
            f"Недостаточно средств в семейном бюджете. Нужно {house.price} 🪙, "
            f"доступно {relationship.family_budget} 🪙."
        )

    # Старый дом (если был) просто заменяется — без компенсации за него.
    relationship.family_budget -= house.price
    relationship.house_id = house.id
    await session.commit()


# ---------------------------------------------------------------------------
# Магазин: машины
# ---------------------------------------------------------------------------


async def get_all_cars(session: AsyncSession) -> list[Car]:
    result = await session.execute(select(Car).order_by(Car.order))
    return list(result.scalars().all())


async def get_car_by_id(session: AsyncSession, car_id: int) -> Car | None:
    result = await session.execute(select(Car).where(Car.id == car_id))
    return result.scalar_one_or_none()


async def buy_car(session: AsyncSession, relationship: Relationship, car: Car) -> None:
    _ensure_married(relationship)

    if relationship.car_id == car.id:
        raise FamilyError("У вашей пары уже есть именно эта машина.")
    if relationship.family_budget < car.price:
        raise FamilyError(
            f"Недостаточно средств в семейном бюджете. Нужно {car.price} 🪙, "
            f"доступно {relationship.family_budget} 🪙."
        )

    # Старая машина (если была) просто заменяется — без компенсации за неё.
    relationship.family_budget -= car.price
    relationship.car_id = car.id
    await session.commit()
