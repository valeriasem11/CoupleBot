"""
Хендлер подарков партнёру: /gift — выбор подарка, оплата с личного баланса.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.keyboards.gift import GIFT_BUY_PREFIX, build_gift_keyboard
from bot.services.achievement_service import award, format_unlock_text
from bot.services.gift_service import (
    GiftError,
    format_timedelta,
    get_all_gifts,
    get_gift_by_id,
    get_gift_cooldown_remaining,
    send_gift,
)
from bot.services.relationship_service import get_active_relationship, get_partner

router = Router(name="gift")


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


@router.message(Command("gift"))
async def cmd_gift(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    remaining = get_gift_cooldown_remaining(user)
    if remaining is not None:
        await message.answer(
            f"Ты уже недавно дарила подарок. Следующий будет доступен через "
            f"{format_timedelta(remaining)}."
        )
        return

    gifts = await get_all_gifts(session)
    await message.answer(
        f"🛍️ Что подаришь партнёру?\n💰 Твой баланс: {user.balance} 🪙",
        reply_markup=build_gift_keyboard(gifts),
    )


@router.callback_query(F.data.startswith(GIFT_BUY_PREFIX))
async def on_gift_buy(callback: CallbackQuery, session: AsyncSession):
    gift_id = int(callback.data.removeprefix(GIFT_BUY_PREFIX))
    gift = await get_gift_by_id(session, gift_id)
    if gift is None:
        await callback.answer("Этот подарок больше не доступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await callback.answer("У тебя больше нет пары.", show_alert=True)
        return

    remaining = get_gift_cooldown_remaining(user)
    if remaining is not None:
        await callback.answer(
            f"Ты уже недавно дарила подарок. Подожди {format_timedelta(remaining)}.",
            show_alert=True,
        )
        return

    try:
        result = await send_gift(session, relationship, user, gift)
    except GiftError as e:
        await callback.answer(str(e), show_alert=True)
        return

    partner = get_partner(relationship, user.id)
    await callback.message.edit_text(
        f"🎁 {_mention(user)} подарил(а) {_mention(partner)}: {gift.name}!\n\n"
        f"❤️ Близость пары: +{result.affection_gained} (теперь {result.new_affection})\n"
        f"💰 Твой остаток баланса: {result.remaining_balance} 🪙"
    )

    if await award(session, user, "generous_partner"):
        await callback.message.answer(format_unlock_text("generous_partner"))

    await callback.answer()
