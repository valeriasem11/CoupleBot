"""
Хендлер казино: ставка на слот-машину Telegram (🎰).
"""
import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.casino_service import (
    MIN_BET,
    CasinoError,
    get_casino_cooldown_remaining,
    place_bet,
    validate_bet,
)

router = Router(name="casino")

# Сколько секунд ждать перед тем, как раскрыть результат — примерно
# соответствует длительности анимации слота в клиенте Telegram.
ANIMATION_DELAY_SECONDS = 2.5


def _format_timedelta(delta) -> str:
    total_seconds = int(delta.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    if minutes > 0:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"


@router.message(Command("casino"))
async def cmd_casino(message: Message, command: CommandObject, session: AsyncSession):
    if command.args is None:
        await message.answer(
            f"Укажи сумму ставки, например: /casino {MIN_BET}\n"
            f"Минимальная ставка — {MIN_BET} 🪙."
        )
        return

    try:
        bet = int(command.args.strip())
    except ValueError:
        await message.answer("Ставка должна быть целым числом.")
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )

    if user.loan_amount > 0:
        await message.answer(
            f"Сначала верни кредит ({user.loan_amount} 🪙) — в казино с долгами не пускают. "
            f"Погасить: /repay (сумма)."
        )
        return

    remaining = get_casino_cooldown_remaining(user)
    if remaining is not None:
        await message.answer(
            f"Казино отдыхает — следующая ставка будет доступна через "
            f"{_format_timedelta(remaining)}."
        )
        return

    try:
        validate_bet(user, bet)
    except CasinoError as e:
        await message.answer(str(e))
        return

    dice_message = await message.answer_dice(emoji="🎰")
    dice_value = dice_message.dice.value

    # Небольшая пауза, чтобы результат текстом появился уже после того,
    # как анимация слота отыграла в клиенте у пользователя.
    await asyncio.sleep(ANIMATION_DELAY_SECONDS)

    result = await place_bet(session, user, bet, dice_value)

    if result.is_jackpot:
        text = (
            f"🎆 ДЖЕКПОТ 777! 🎆\n"
            f"Ставка {result.bet} 🪙 × {result.payout // result.bet} = {result.payout} 🪙\n\n"
            f"Баланс: {result.new_balance} 🪙"
        )
    elif result.is_win:
        text = (
            f"🎉 Выигрыш!\n"
            f"Ставка {result.bet} 🪙 × {result.payout // result.bet} = {result.payout} 🪙\n\n"
            f"Баланс: {result.new_balance} 🪙"
        )
    else:
        text = (
            f"😔 Не повезло. Ставка {result.bet} 🪙 сгорела.\n\n"
            f"Баланс: {result.new_balance} 🪙"
        )

    await message.answer(text)
