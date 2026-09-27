"""
Хендлеры прямых переводов монет: /pay (сумма) и /payall (весь баланс),
оба ответом на сообщение получателя.
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.achievement_service import award, format_unlock_text
from bot.services.payment_service import (
    MIN_PAYMENT,
    PaymentError,
    PaymentResult,
    transfer_all_coins,
    transfer_coins,
)

router = Router(name="payment")


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


async def _get_sender_and_receiver(message: Message, session: AsyncSession):
    """
    Общая проверка для /pay и /payall: сообщение должно быть ответом на
    чьё-то сообщение (получателя), и получатель не должен быть ботом.
    Возвращает (sender, receiver) либо (None, None), если уже отправлен
    ответ об ошибке и дальше продолжать не нужно.
    """
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        return None, None

    target_tg_user = message.reply_to_message.from_user
    if target_tg_user.is_bot:
        await message.answer("Ботам переводить деньги смысла нет 🙂")
        return None, None

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
    return sender, receiver


async def _announce_and_award(message: Message, session: AsyncSession, sender, receiver, result: PaymentResult):
    await message.answer(
        f"💸 {_mention(sender)} перевёл(а) {_mention(receiver)} {result.amount} 🪙."
    )
    if await award(session, sender, "generous_soul"):
        await message.answer(format_unlock_text("generous_soul"))


@router.message(Command("pay"))
async def cmd_pay(message: Message, command: CommandObject, session: AsyncSession):
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        await message.answer(
            f"Чтобы перевести деньги, ответь этой командой на сообщение получателя, "
            f"указав сумму, например: /pay 500\n(минимум — {MIN_PAYMENT} 🪙)\n\n"
            f"Хочешь отдать весь баланс сразу — используй /payall (без суммы)."
        )
        return

    if command.args is None or not command.args.strip():
        await message.answer(f"Укажи сумму перевода, например: /pay 500\n(минимум — {MIN_PAYMENT} 🪙)")
        return

    try:
        amount = int(command.args.strip())
    except ValueError:
        await message.answer("Сумма должна быть целым числом.")
        return

    sender, receiver = await _get_sender_and_receiver(message, session)
    if sender is None:
        return

    try:
        result = await transfer_coins(session, sender, receiver, amount)
    except PaymentError as e:
        await message.answer(str(e))
        return

    await _announce_and_award(message, session, sender, receiver, result)


@router.message(Command("payall"))
async def cmd_payall(message: Message, session: AsyncSession):
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        await message.answer(
            "Чтобы перевести весь баланс, ответь этой командой на сообщение получателя "
            "(сумму указывать не нужно — уйдёт всё, что у тебя есть)."
        )
        return

    sender, receiver = await _get_sender_and_receiver(message, session)
    if sender is None:
        return

    try:
        result = await transfer_all_coins(session, sender, receiver)
    except PaymentError as e:
        await message.answer(str(e))
        return

    await _announce_and_award(message, session, sender, receiver, result)
