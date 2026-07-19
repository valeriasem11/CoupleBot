"""
Хендлеры семейного бюджета и магазина (дом, машина).
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.database.models import ChildStatus
from bot.keyboards.children import build_pick_child_for_toy_keyboard
from bot.keyboards.shop import (
    BUY_CAR_PREFIX,
    BUY_HOUSE_PREFIX,
    SHOP_CARS_PREFIX,
    SHOP_HOUSES_PREFIX,
    SHOP_MENU_PREFIX,
    SHOP_TOYS_PREFIX,
    build_cars_keyboard,
    build_houses_keyboard,
    build_shop_menu_keyboard,
)
from bot.services.children_service import get_children
from bot.handlers.toys import send_toy_shop_for_child
from bot.services.family_service import (
    FamilyError,
    buy_car,
    buy_house,
    deposit_to_family_budget,
    get_all_cars,
    get_all_houses,
    get_car_by_id,
    get_house_by_id,
    withdraw_from_family_budget,
)
from bot.services.relationship_service import get_active_relationship, get_partner

router = Router(name="shop")


async def _get_user(message_or_callback, session: AsyncSession):
    from_user = message_or_callback.from_user
    chat = getattr(message_or_callback, "message", message_or_callback).chat
    return await get_or_create_user(
        session=session,
        telegram_id=from_user.id,
        username=from_user.username,
        first_name=from_user.first_name,
        chat_id=chat.id,
    )


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


def _parse_amount(command: CommandObject) -> int | None:
    """Парсит целое положительное число из аргумента команды. None, если некорректно."""
    if command.args is None:
        return None
    try:
        amount = int(command.args.strip())
    except ValueError:
        return None
    if amount <= 0:
        return None
    return amount


# ---------------------------------------------------------------------------
# /budget — посмотреть семейный бюджет
# ---------------------------------------------------------------------------


@router.message(Command("budget"))
async def cmd_budget(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    if relationship.status.value != "married":
        await message.answer("Семейный бюджет появляется только в браке. Сейчас его ещё нет.")
        return

    await message.answer(
        f"💰 Семейный бюджет: {relationship.family_budget} 🪙\n\n"
        f"Пополнить: /deposit (сумма)\n"
        f"Снять: /withdraw (сумма)\n"
        f"Магазин: /shop"
    )


@router.message(Command("deposit"))
async def cmd_deposit(message: Message, command: CommandObject, session: AsyncSession):
    amount = _parse_amount(command)
    if amount is None:
        await message.answer("Укажи сумму числом, например: /deposit 1000")
        return

    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    try:
        await deposit_to_family_budget(session, relationship, user, amount)
    except FamilyError as e:
        await message.answer(str(e))
        return

    await message.answer(
        f"✅ {_mention(user)} положил(а) {amount} 🪙 в семейный бюджет.\n"
        f"Баланс семьи: {relationship.family_budget} 🪙"
    )


@router.message(Command("withdraw"))
async def cmd_withdraw(message: Message, command: CommandObject, session: AsyncSession):
    amount = _parse_amount(command)
    if amount is None:
        await message.answer("Укажи сумму числом, например: /withdraw 1000")
        return

    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    try:
        await withdraw_from_family_budget(session, relationship, user, amount)
    except FamilyError as e:
        await message.answer(str(e))
        return

    await message.answer(
        f"✅ {_mention(user)} забрал(а) {amount} 🪙 из семейного бюджета.\n"
        f"Баланс семьи: {relationship.family_budget} 🪙"
    )


# ---------------------------------------------------------------------------
# /shop — магазин домов и машин
# ---------------------------------------------------------------------------


@router.message(Command("shop"))
async def cmd_shop(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    if relationship.status.value != "married":
        await message.answer("Магазин доступен только в браке.")
        return

    await message.answer(
        f"💰 Семейный бюджет: {relationship.family_budget} 🪙\n\n"
        f"Что хотите купить?",
        reply_markup=build_shop_menu_keyboard(),
    )


@router.callback_query(F.data == SHOP_MENU_PREFIX)
async def on_shop_menu_back(callback: CallbackQuery, session: AsyncSession):
    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    budget = relationship.family_budget if relationship else 0

    await callback.message.edit_text(
        f"💰 Семейный бюджет: {budget} 🪙\n\n"
        f"Что хотите купить?",
        reply_markup=build_shop_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == SHOP_TOYS_PREFIX)
async def on_shop_toys(callback: CallbackQuery, session: AsyncSession):
    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None or relationship.status.value != "married":
        await callback.answer("Магазин игрушек доступен только в браке.", show_alert=True)
        return

    all_children = await get_children(session, relationship.id)
    alive_children = [c for c in all_children if c.status == ChildStatus.ALIVE]

    if not alive_children:
        await callback.answer("У вашей пары пока нет детей.", show_alert=True)
        return

    if len(alive_children) == 1:
        await send_toy_shop_for_child(callback, alive_children[0], session, edit=True)
        await callback.answer()
        return

    await callback.message.edit_text(
        "Для кого покупаем игрушку?",
        reply_markup=build_pick_child_for_toy_keyboard(alive_children),
    )
    await callback.answer()


@router.callback_query(F.data == SHOP_HOUSES_PREFIX)
async def on_shop_houses(callback: CallbackQuery, session: AsyncSession):
    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    houses = await get_all_houses(session)
    current_house_id = relationship.house_id if relationship else None
    await callback.message.edit_text(
        "🏠 Дома на продажу (при покупке нового старый заменяется без компенсации):",
        reply_markup=build_houses_keyboard(houses, current_house_id),
    )
    await callback.answer()


@router.callback_query(F.data == SHOP_CARS_PREFIX)
async def on_shop_cars(callback: CallbackQuery, session: AsyncSession):
    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    cars = await get_all_cars(session)
    current_car_id = relationship.car_id if relationship else None
    await callback.message.edit_text(
        "🚗 Машины на продажу (при покупке новой старая заменяется без компенсации):",
        reply_markup=build_cars_keyboard(cars, current_car_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(BUY_HOUSE_PREFIX))
async def on_buy_house(callback: CallbackQuery, session: AsyncSession):
    house_id = int(callback.data.removeprefix(BUY_HOUSE_PREFIX))
    house = await get_house_by_id(session, house_id)
    if house is None:
        await callback.answer("Этот дом больше не продаётся.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await callback.answer("У тебя больше нет пары.", show_alert=True)
        return

    had_house_before = relationship.house_id is not None

    try:
        await buy_house(session, relationship, house)
    except FamilyError as e:
        await callback.answer(str(e), show_alert=True)
        return

    partner = get_partner(relationship, user.id)
    verb = "переехали в новый дом" if had_house_before else "купили дом"
    await callback.message.edit_text(
        f"🎉 {_mention(user)} и {_mention(partner)} {verb}: {house.name}!\n\n"
        f"Остаток семейного бюджета: {relationship.family_budget} 🪙"
    )
    await callback.answer()


@router.callback_query(F.data.startswith(BUY_CAR_PREFIX))
async def on_buy_car(callback: CallbackQuery, session: AsyncSession):
    car_id = int(callback.data.removeprefix(BUY_CAR_PREFIX))
    car = await get_car_by_id(session, car_id)
    if car is None:
        await callback.answer("Эта машина больше не продаётся.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await callback.answer("У тебя больше нет пары.", show_alert=True)
        return

    had_car_before = relationship.car_id is not None

    try:
        await buy_car(session, relationship, car)
    except FamilyError as e:
        await callback.answer(str(e), show_alert=True)
        return

    partner = get_partner(relationship, user.id)
    verb = "сменили машину на" if had_car_before else "купили машину"
    await callback.message.edit_text(
        f"🎉 {_mention(user)} и {_mention(partner)} {verb}: {car.name}!\n\n"
        f"Остаток семейного бюджета: {relationship.family_budget} 🪙"
    )
    await callback.answer()
