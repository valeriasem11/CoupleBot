"""
Бизнес-логика ежедневных подработок: раз в сутки случайная подработка
с фиксированной (в диапазоне) наградой + растущий бонус за серию дней подряд.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.database.models import User

# emoji, название, базовая награда (диапазон 100-300 🪙 в целом по всему списку)
GIGS = [
    {"emoji": "🐕", "name": "Выгулял(а) соседскую собаку", "amount": 120},
    {"emoji": "📦", "name": "Разнёс(ла) листовки по подъездам", "amount": 100},
    {"emoji": "🌿", "name": "Полил(а) цветы у бабушки, пока та в отпуске", "amount": 110},
    {"emoji": "🚗", "name": "Помыл(а) машину соседа", "amount": 150},
    {"emoji": "📸", "name": "Сфотографировал(а) чью-то свадьбу", "amount": 280},
    {"emoji": "🎂", "name": "Испёк(ла) торт на заказ", "amount": 200},
    {"emoji": "🧹", "name": "Убрался(-ась) в подъезде", "amount": 130},
    {"emoji": "🛠️", "name": "Починил(а) кран у соседей", "amount": 190},
    {"emoji": "📚", "name": "Позанимался(-ась) репетиторством", "amount": 260},
    {"emoji": "🎨", "name": "Нарисовал(а) логотип для местного магазина", "amount": 240},
    {"emoji": "🐈", "name": "Присмотрел(а) за котом соседей на выходные", "amount": 140},
    {"emoji": "🧺", "name": "Разгрузил(а) машину с продуктами", "amount": 160},
    {"emoji": "🎭", "name": "Подработал(а) аниматором на детском празднике", "amount": 300},
    {"emoji": "💻", "name": "Настроил(а) компьютер соседу", "amount": 220},
    {"emoji": "🚲", "name": "Доставил(а) заказ на велосипеде", "amount": 170},
]

STREAK_BONUS_PER_DAY = 10  # % за каждый день серии сверх первого
STREAK_BONUS_CAP = 100  # максимум +100% (после 11-го дня подряд бонус больше не растёт)


class GigError(Exception):
    """Ошибка бизнес-логики подработок — текст готов для показа пользователю."""


@dataclass
class GigResult:
    gig_emoji: str
    gig_name: str
    base_amount: int
    bonus_percent: int
    total_amount: int
    streak: int
    new_balance: int


async def perform_gig(session, user: User) -> GigResult:
    """
    Выполняет случайную подработку дня. Бросает GigError, если сегодня уже
    выполнялась. Серия дней подряд считается по календарным суткам (UTC):
    если предыдущая подработка была ровно вчера — серия растёт, если раньше —
    сбрасывается на 1.
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    if user.last_gig_completed_at is not None:
        last_at = user.last_gig_completed_at
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        last_date = last_at.date()

        if last_date == today:
            raise GigError("Подработка на сегодня уже выполнена — приходи завтра 🙂")

        if (today - last_date).days == 1:
            user.gig_streak += 1
        else:
            user.gig_streak = 1  # серия прервалась — начинаем заново
    else:
        user.gig_streak = 1  # первая подработка вообще

    gig = random.choice(GIGS)
    bonus_percent = min((user.gig_streak - 1) * STREAK_BONUS_PER_DAY, STREAK_BONUS_CAP)
    total_amount = round(gig["amount"] * (1 + bonus_percent / 100))

    user.balance += total_amount
    user.last_gig_completed_at = now

    await session.commit()

    return GigResult(
        gig_emoji=gig["emoji"],
        gig_name=gig["name"],
        base_amount=gig["amount"],
        bonus_percent=bonus_percent,
        total_amount=total_amount,
        streak=user.gig_streak,
        new_balance=user.balance,
    )
