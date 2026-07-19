"""
Бизнес-логика казино: ставки на слот-машину Telegram (эмодзи 🎰).

Telegram сам анимирует слот и возвращает случайное значение от 1 до 64 —
бот только интерпретирует это значение, саму случайность генерирует
сервер Telegram (это исключает любые манипуляции с исходом на нашей стороне).

Как устроены значения слота:
value = 1 + d1 + 4*d2 + 16*d3, где d1/d2/d3 — символы трёх барабанов (0..3).
Все три барабана совпадают («выигрышная комбинация») ровно при
value = 1 + 21*d, т.е. при value in {1, 22, 43, 64}.
value == 64 соответствует комбинации 777 (джекпот).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User

MIN_BET = 100
COOLDOWN_SECONDS = 5 * 60  # 5 минут между ставками

REGULAR_MULTIPLIER = 8
JACKPOT_MULTIPLIER = 25

WINNING_VALUES = {1, 22, 43, 64}
JACKPOT_VALUE = 64


class CasinoError(Exception):
    """Ошибка бизнес-логики казино — текст готов для показа пользователю."""


def get_casino_cooldown_remaining(user: User) -> timedelta | None:
    if user.casino_last_bet_at is None:
        return None

    last_bet_at = user.casino_last_bet_at
    if last_bet_at.tzinfo is None:
        last_bet_at = last_bet_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_bet_at + timedelta(seconds=COOLDOWN_SECONDS)
    if now >= ready_at:
        return None
    return ready_at - now


def validate_bet(user: User, bet: int) -> None:
    if bet < MIN_BET:
        raise CasinoError(f"Минимальная ставка — {MIN_BET} 🪙.")
    if bet > user.balance:
        raise CasinoError(f"Недостаточно средств на балансе (доступно {user.balance} 🪙).")


def resolve_outcome(dice_value: int) -> tuple[bool, bool]:
    """Возвращает (выигрыш?, джекпот?) по значению слота Telegram (1..64)."""
    is_win = dice_value in WINNING_VALUES
    is_jackpot = dice_value == JACKPOT_VALUE
    return is_win, is_jackpot


@dataclass
class CasinoResult:
    bet: int
    is_win: bool
    is_jackpot: bool
    payout: int
    net: int  # payout - bet (может быть отрицательным при проигрыше)
    new_balance: int


async def place_bet(session: AsyncSession, user: User, bet: int, dice_value: int) -> CasinoResult:
    """
    Проводит ставку: списывает bet, начисляет выигрыш при удаче, обновляет
    кулдаун. Вызывающий код должен ЗАРАНЕЕ проверить validate_bet и кулдаун —
    эта функция сама их не проверяет (bet и dice_value уже считаются валидными).
    """
    is_win, is_jackpot = resolve_outcome(dice_value)

    user.balance -= bet

    payout = 0
    if is_win:
        multiplier = JACKPOT_MULTIPLIER if is_jackpot else REGULAR_MULTIPLIER
        payout = bet * multiplier
        user.balance += payout

    user.casino_last_bet_at = datetime.now(timezone.utc)
    await session.commit()

    return CasinoResult(
        bet=bet,
        is_win=is_win,
        is_jackpot=is_jackpot,
        payout=payout,
        net=payout - bet,
        new_balance=user.balance,
    )
