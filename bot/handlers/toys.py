"""
Callback-хендлеры магазина игрушек: выбор ребёнка (если их несколько) и покупка.
Точка входа — кнопка "🧸 Игрушки" в /shop (см. handlers/shop.py).
"""
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.database.models import ChildStatus
from bot.keyboards.children import (
    BUY_TOY_PREFIX,
    PICK_CHILD_TOY_PREFIX,
    build_toy_shop_keyboard,
)
from bot.services.children_service import ChildError, buy_toy, get_all_toys, get_child_by_id
from bot.services.relationship_service import get_active_relationship

router = Router(name="toys")


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


async def send_toy_shop_for_child(target, child, session: AsyncSession, edit: bool):
    toys = await get_all_toys(session)
    owned = child.owned_toys.split(",") if child.owned_toys else []
    label = child.name or "Без имени"

    text = (
        f"🧸 Магазин игрушек для {label}\n\n"
        f"Игрушки снижают скорость угасания настроения (эффект складывается, "
        f"максимум -70%)."
    )
    keyboard = build_toy_shop_keyboard(child.id, toys, owned)

    if edit:
        await target.message.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(PICK_CHILD_TOY_PREFIX))
async def on_pick_child_for_toy(callback: CallbackQuery, session: AsyncSession):
    child_id = int(callback.data.removeprefix(PICK_CHILD_TOY_PREFIX))
    child = await get_child_by_id(session, child_id)

    if child is None or child.status != ChildStatus.ALIVE:
        await callback.answer("Этот ребёнок недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    await send_toy_shop_for_child(callback, child, session, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith(BUY_TOY_PREFIX))
async def on_buy_toy(callback: CallbackQuery, session: AsyncSession):
    payload = callback.data.removeprefix(BUY_TOY_PREFIX)
    child_id_str, toy_id_str = payload.split(":")
    child_id, toy_id = int(child_id_str), int(toy_id_str)

    child = await get_child_by_id(session, child_id)
    if child is None or child.status != ChildStatus.ALIVE:
        await callback.answer("Этот ребёнок недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    toys = await get_all_toys(session)
    toy = next((t for t in toys if t.id == toy_id), None)
    if toy is None:
        await callback.answer("Эта игрушка больше не продаётся.", show_alert=True)
        return

    try:
        await buy_toy(session, relationship, child, toy)
    except ChildError as e:
        await callback.answer(str(e), show_alert=True)
        return

    label = child.name or "Без имени"
    await callback.message.edit_text(
        f"🎉 Купили {toy.name} для {label}!\n\n"
        f"Остаток семейного бюджета: {relationship.family_budget} 🪙"
    )
    await callback.answer()
