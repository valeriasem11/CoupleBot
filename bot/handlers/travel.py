"""
Хендлер путешествий: /travel — выбор направления, оплата из семейного бюджета.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.keyboards.travel import TRAVEL_BUY_PREFIX, build_travel_keyboard
from bot.services.achievement_service import award_couple, format_unlock_text
from bot.services.relationship_service import get_active_relationship, get_partner
from bot.services.travel_service import (
    TravelError,
    format_timedelta,
    get_all_destinations,
    get_destination_by_id,
    get_travel_cooldown_remaining,
    take_trip,
)

router = Router(name="travel")


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


@router.message(Command("travel"))
async def cmd_travel(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    if relationship.status.value != "married":
        await message.answer("Путешествия доступны только в браке.")
        return

    remaining = get_travel_cooldown_remaining(relationship)
    if remaining is not None:
        await message.answer(
            f"Вы недавно уже путешествовали. Следующая поездка будет доступна "
            f"через {format_timedelta(remaining)}."
        )
        return

    destinations = await get_all_destinations(session)
    await message.answer(
        f"✈️ Куда отправимся?\n💰 Семейный бюджет: {relationship.family_budget} 🪙",
        reply_markup=build_travel_keyboard(destinations),
    )


@router.callback_query(F.data.startswith(TRAVEL_BUY_PREFIX))
async def on_travel_buy(callback: CallbackQuery, session: AsyncSession):
    destination_id = int(callback.data.removeprefix(TRAVEL_BUY_PREFIX))
    destination = await get_destination_by_id(session, destination_id)
    if destination is None:
        await callback.answer("Это направление больше не доступно.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await callback.answer("У тебя больше нет пары.", show_alert=True)
        return

    remaining = get_travel_cooldown_remaining(relationship)
    if remaining is not None:
        await callback.answer(
            f"Вы недавно уже путешествовали. Подождите {format_timedelta(remaining)}.",
            show_alert=True,
        )
        return

    try:
        result = await take_trip(session, relationship, destination)
    except TravelError as e:
        await callback.answer(str(e), show_alert=True)
        return

    partner = get_partner(relationship, user.id)
    await callback.message.edit_text(
        f"✈️ {_mention(user)} и {_mention(partner)} съездили в {destination.name}!\n\n"
        f"{destination.description}\n\n"
        f"❤️ Близость пары: +{result.affection_gained} (теперь {result.new_affection})\n"
        f"💰 Остаток семейного бюджета: {result.new_budget} 🪙"
    )

    newly_unlocked = await award_couple(session, (relationship.user1, relationship.user2), "traveler")
    if newly_unlocked:
        names = " и ".join(_mention(u) for u in newly_unlocked)
        await callback.message.answer(f"{names}\n{format_unlock_text('traveler')}")

    await callback.answer()
