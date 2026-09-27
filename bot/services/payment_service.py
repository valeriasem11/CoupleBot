"""
Бизнес-логика прямых переводов монет между игроками — в отличие от /gift,
без привязки к отношениям, без флейвора, просто перевод денег кому угодно.
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User

MIN_PAYMENT = 10


class PaymentError(Exception):
    """Ошибка бизнес-логики перевода — текст готов для показа пользователю."""


@dataclass
class PaymentResult:
    amount: int
    sender_new_balance: int
    receiver_new_balance: int


async def transfer_coins(
    session: AsyncSession, sender: User, receiver: User, amount: int
) -> PaymentResult:
    """
    Переводит монеты от sender к receiver. Деньги просто переходят от
    одного баланса к другому — новых денег в системе не появляется.
    """
    if sender.id == receiver.id:
        raise PaymentError("Нельзя перевести деньги самой(ому) себе 🙂")
    if amount < MIN_PAYMENT:
        raise PaymentError(f"Минимальная сумма перевода — {MIN_PAYMENT} 🪙.")
    if amount > sender.balance:
        raise PaymentError(f"Недостаточно средств на балансе (доступно {sender.balance} 🪙).")

    sender.balance -= amount
    receiver.balance += amount

    await session.commit()

    return PaymentResult(
        amount=amount,
        sender_new_balance=sender.balance,
        receiver_new_balance=receiver.balance,
    )


async def transfer_all_coins(session: AsyncSession, sender: User, receiver: User) -> PaymentResult:
    """
    Переводит ВЕСЬ баланс отправителя целиком (для /payall) — в отличие от
    transfer_coins, не требует минимальной суммы (раз человек явно хочет
    отдать всё, что у него есть, а не какую-то конкретную сумму).
    """
    if sender.id == receiver.id:
        raise PaymentError("Нельзя перевести деньги самой(ому) себе 🙂")
    if sender.balance <= 0:
        raise PaymentError("У тебя нечего переводить — баланс уже пуст.")

    amount = sender.balance
    sender.balance = 0
    receiver.balance += amount

    await session.commit()

    return PaymentResult(
        amount=amount,
        sender_new_balance=sender.balance,
        receiver_new_balance=receiver.balance,
    )
