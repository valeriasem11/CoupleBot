"""
Бизнес-логика экономики: расчёт заработка на работе, проверка кулдауна.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Job, User
from bot.services.career_service import get_career_level
from bot.services.happy_hour_service import get_active_happy_hour_bonus_percent

# Вероятности исходов при вызове /work.
# Сумма должна быть равна 1.0 — обычная смена добирает всё, что осталось.
TIP_CHANCE = 0.40  # шанс на чаевые
BONUS_CHANCE = 0.10  # шанс на премию (реже, чем чаевые)

# Диапазоны бонуса в процентах от базовой ЗП
TIP_PERCENT_RANGE = (10, 15)
BONUS_PERCENT_RANGE = (50, 100)

# Случайная находка — небольшой шанс на доп. бонус сверх обычной награды
RANDOM_FIND_CHANCE = 0.08
RANDOM_FIND_RANGE = (50, 200)

# Streak за ежедневный /work: день подряд -> разовая награда (выдаётся один
# раз за каждое достижение планки В ТЕКУЩЕЙ серии; если серия прервалась
# и набралась заново — награда выдаётся снова)
WORK_STREAK_THRESHOLDS = {3: 300, 7: 700, 14: 1500, 21: 2500}
WORK_STREAK_ACHIEVEMENT_THRESHOLD = 21


class WorkOutcome(str, Enum):
    PLAIN = "plain"  # обычная смена, без бонуса
    TIP = "tip"  # чаевые
    BONUS = "bonus"  # премия


@dataclass
class WorkResult:
    outcome: WorkOutcome
    base_salary: int
    bonus_amount: int
    total: int
    career_title: str
    leveled_up_to: str | None  # если на этой смене произошло повышение — новое звание
    happy_hour_bonus_percent: int  # 0, если счастливый час сейчас не идёт
    random_find_amount: int  # 0, если находка не выпала
    streak_days: int  # текущая серия дней подряд с /work
    streak_bonus: int  # 0, если на этой смене не была достигнута ни одна планка


def calculate_work_result(base_salary: int) -> tuple[WorkOutcome, int, int]:
    """
    Разыгрывает исход смены: обычная / чаевые / премия,
    и считает итоговую сумму заработка (от уже умноженной на карьеру базы).
    """
    roll = random.random()

    if roll < BONUS_CHANCE:
        outcome = WorkOutcome.BONUS
        percent = random.uniform(*BONUS_PERCENT_RANGE)
    elif roll < BONUS_CHANCE + TIP_CHANCE:
        outcome = WorkOutcome.TIP
        percent = random.uniform(*TIP_PERCENT_RANGE)
    else:
        outcome = WorkOutcome.PLAIN
        percent = 0

    bonus_amount = round(base_salary * percent / 100)
    total = base_salary + bonus_amount

    return outcome, bonus_amount, total


def get_work_cooldown_remaining(user: User, job: Job) -> timedelta | None:
    """
    Возвращает оставшееся время до конца кулдауна, либо None,
    если можно работать прямо сейчас.
    """
    if user.job_last_used_at is None:
        return None

    # job_last_used_at хранится с таймзоной (DateTime(timezone=True)),
    # поэтому сравниваем тоже в UTC. На случай, если драйвер БД вернёт
    # наивный datetime (без таймзоны), подстраховываемся.
    last_used_at = user.job_last_used_at
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ready_at = last_used_at + timedelta(seconds=job.cooldown_seconds)

    if now >= ready_at:
        return None

    return ready_at - now


def _update_work_streak(user: User) -> tuple[int, int]:
    """
    Обновляет серию дней подряд с /work (по календарным суткам UTC — если
    сегодня уже отмечались, серия не трогается повторно, раз в день можно
    сходить на смену несколько раз благодаря карьере/чаевым).

    Возвращает (текущая_серия, бонус_если_только_что_заработан).
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    last_date = None
    if user.last_work_streak_date is not None:
        last_dt = user.last_work_streak_date
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        last_date = last_dt.date()

    if last_date == today:
        return user.work_streak_days, 0  # уже отмечались сегодня — серия не меняется

    if last_date is not None and (today - last_date).days == 1:
        user.work_streak_days += 1
    else:
        user.work_streak_days = 1  # серия прервалась (или это самый первый /work) — начинаем заново

    user.last_work_streak_date = now

    bonus = WORK_STREAK_THRESHOLDS.get(user.work_streak_days, 0)
    return user.work_streak_days, bonus


def format_timedelta(delta: timedelta) -> str:
    """Форматирует оставшееся время кулдауна в читаемый вид (часы/минуты)."""
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


async def perform_work(session: AsyncSession, user: User, job: Job) -> WorkResult:
    """
    Выполняет смену: начисляет деньги пользователю (с учётом карьерного
    множителя и, если сейчас идёт, счастливого часа), с шансом добавляет
    случайную находку, обновляет серию дней подряд с /work (с разовым
    бонусом за 3/7/14/21 день), увеличивает счётчик смен и обновляет
    время последнего использования работы.

    Вызывающий код должен ЗАРАНЕЕ проверить кулдаун через
    get_work_cooldown_remaining — эта функция сама его не проверяет.
    """
    shifts_before = user.job_shifts_worked
    level_before = get_career_level(shifts_before)

    effective_salary = round(job.salary * level_before.multiplier)

    happy_hour_bonus_percent = 0
    if user.chat_id is not None:
        happy_hour_bonus_percent = await get_active_happy_hour_bonus_percent(session, user.chat_id)
    if happy_hour_bonus_percent > 0:
        effective_salary = round(effective_salary * (1 + happy_hour_bonus_percent / 100))

    outcome, bonus_amount, total = calculate_work_result(effective_salary)

    random_find_amount = 0
    if random.random() < RANDOM_FIND_CHANCE:
        random_find_amount = random.randint(*RANDOM_FIND_RANGE)
        total += random_find_amount

    streak_days, streak_bonus = _update_work_streak(user)

    total_credited = total + streak_bonus

    user.balance += total_credited
    user.lifetime_earned += total_credited
    user.lifetime_work_count += 1
    user.job_last_used_at = datetime.now(timezone.utc)
    user.job_shifts_worked += 1

    level_after = get_career_level(user.job_shifts_worked)
    leveled_up_to = level_after.title if level_after.title != level_before.title else None

    await session.commit()

    return WorkResult(
        outcome=outcome,
        base_salary=effective_salary,
        bonus_amount=bonus_amount,
        total=total,
        career_title=level_after.title,
        leveled_up_to=leveled_up_to,
        happy_hour_bonus_percent=happy_hour_bonus_percent,
        random_find_amount=random_find_amount,
        streak_days=streak_days,
        streak_bonus=streak_bonus,
    )


# ---------------------------------------------------------------------------
# Кредит
# ---------------------------------------------------------------------------

MAX_LOAN_AMOUNT = 15000
LOAN_INTEREST_RATE = 0.25  # +25% переплата при оформлении
LOAN_GROWTH_INTERVAL = timedelta(days=3)
LOAN_GROWTH_RATE = 0.05  # +5% к долгу за каждый такой период без платежей


class LoanError(Exception):
    """Ошибка бизнес-логики кредита — текст готов для показа пользователю."""


async def take_loan(session: AsyncSession, user: User, amount: int) -> int:
    """
    Оформляет кредит: начисляет сумму на баланс, записывает долг с переплатой.
    Возвращает итоговую сумму долга (с переплатой), которую нужно будет вернуть.
    """
    if amount <= 0:
        raise LoanError("Сумма кредита должна быть больше нуля.")
    if amount > MAX_LOAN_AMOUNT:
        raise LoanError(f"Максимальная сумма кредита — {MAX_LOAN_AMOUNT} 🪙.")
    if user.loan_amount > 0:
        raise LoanError(
            f"У тебя уже есть непогашенный кредит ({user.loan_amount} 🪙). "
            f"Сначала верни его через /repay."
        )

    debt = round(amount * (1 + LOAN_INTEREST_RATE))

    user.balance += amount
    user.loan_amount = debt
    user.loan_last_charge_at = datetime.now(timezone.utc)

    await session.commit()
    return debt


async def repay_loan(session: AsyncSession, user: User, amount: int) -> int:
    """
    Гасит кредит на указанную сумму (не больше, чем реально должен и чем есть
    на балансе). Возвращает сумму, которая была реально списана.
    """
    if amount <= 0:
        raise LoanError("Сумма погашения должна быть больше нуля.")
    if user.loan_amount <= 0:
        raise LoanError("У тебя нет непогашенного кредита.")
    if amount > user.balance:
        raise LoanError(f"Недостаточно средств на балансе (доступно {user.balance} 🪙).")

    actual_repay = min(amount, user.loan_amount)

    user.balance -= actual_repay
    user.loan_amount -= actual_repay
    if user.loan_amount > 0:
        user.loan_last_charge_at = datetime.now(timezone.utc)  # платёж даёт свежую отсрочку

    await session.commit()
    return actual_repay


# ---------------------------------------------------------------------------
# Рост долга и напоминания (вызывается фоновым планировщиком)
# ---------------------------------------------------------------------------


@dataclass
class LoanReminderEvent:
    chat_id: int
    user_name: str
    new_debt: int
    grew: bool  # True, если долг только что вырос (а не просто напоминание без изменений)


async def process_loans_tick(session: AsyncSession) -> list[LoanReminderEvent]:
    """
    Один "тик" планировщика: для всех должников с долгом > 0 проверяет,
    не пора ли начислить +5% (раз в 3 дня без платежей), и готовит
    напоминание. Возвращает события — саму рассылку делает scheduler.py.
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(select(User).where(User.loan_amount > 0))
    debtors = list(result.scalars().all())

    events: list[LoanReminderEvent] = []

    for user in debtors:
        if user.chat_id is None:
            continue

        last_charge = user.loan_last_charge_at
        if last_charge is None:
            continue
        if last_charge.tzinfo is None:
            last_charge = last_charge.replace(tzinfo=timezone.utc)

        elapsed = now - last_charge
        periods = int(elapsed.total_seconds() // LOAN_GROWTH_INTERVAL.total_seconds())

        if periods >= 1:
            user.loan_amount = round(user.loan_amount * ((1 + LOAN_GROWTH_RATE) ** periods))
            user.loan_last_charge_at = last_charge + periods * LOAN_GROWTH_INTERVAL
            events.append(
                LoanReminderEvent(
                    chat_id=user.chat_id,
                    user_name=user.first_name,
                    new_debt=user.loan_amount,
                    grew=True,
                )
            )

    await session.commit()
    return events
