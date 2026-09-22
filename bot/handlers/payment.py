"""
Хендлер прямых переводов монет: /pay (сумма), ответом на сообщение получателя.
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.achievement_service import award, format_unlock_text
from bot.services.payment_service import MIN_PAYMENT, PaymentError, transfer_coins

router = Router(name="payment")


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


@router.message(Command("pay"))
async def cmd_pay(message: Message, command: CommandObject, session: AsyncSession):
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        await message.answer(
            f"Чтобы перевести деньги, ответь этой командой на сообщение получателя, "
            f"указав сумму, например: /pay 500\n(минимум — {MIN_PAYMENT} 🪙)"
        )
        return

    target_tg_user = message.reply_to_message.from_user
    if target_tg_user.is_bot:
        await message.answer("Ботам переводить деньги смысла нет 🙂")
        return

    if command.args is None or not command.args.strip():
        await message.answer(f"Укажи сумму перевода, например: /pay 500\n(минимум — {MIN_PAYMENT} 🪙)")
        return

    try:
        amount = int(command.args.strip())
    except ValueError:
        await message.answer("Сумма должна быть целым числом.")
        return

    sender = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )
    receiver = await get_or_create_user(
        session=session,
        telegram_id=target_tg_user.id,
        username=target_tg_user.username,
        first_name=target_tg_user.first_name,
        chat_id=message.chat.id,
    )

    try:
        result = await transfer_coins(session, sender, receiver, amount)
    except PaymentError as e:
        await message.answer(str(e))
        return

    await message.answer(
        f"💸 {_mention(sender)} перевёл(а) {_mention(receiver)} {result.amount} 🪙."
    )

    if await award(session, sender, "generous_soul"):
        await message.answer(format_unlock_text("generous_soul"))
