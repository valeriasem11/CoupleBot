"""
Бизнес-логика достижений: список, выдача, просмотр прогресса.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, UserAchievement

# code -> (эмодзи, название, описание условия)
ACHIEVEMENTS: dict[str, tuple[str, str, str]] = {
    "first_relationship": ("💌", "Первая любовь", "Начали отношения впервые"),
    "married": ("💍", "Свадьба", "Поженились"),
    "broken_heart": ("💔", "Разбитое сердце", "Пережили расставание"),
    "romantic": ("🌹", "Романтик", "Достигли стадии «Влюблённость»"),
    "new_home": ("🏠", "Новосёл", "Купили первый дом"),
    "wheels": ("🚗", "На колёсах", "Купили первую машину"),
    "parent": ("👶", "Родитель", "Стали родителем"),
    "big_family": ("👨‍👩‍👧‍👦", "Многодетная семья", "3 и более детей одновременно"),
    "caring_parent": ("🧸", "Заботливый родитель", "Купили первую игрушку ребёнку"),
    "lucky": ("🎰", "Счастливчик", "Сорвали джекпот 777 в казино"),
    "credit_history": ("🏦", "Хорошая кредитная история", "Полностью погасили кредит"),
    "rich": ("💰", "Первая тысяча", "Накопили 1 000 🪙 на балансе"),
    "very_rich": ("💎", "Богач", "Накопили 10 000 🪙 на балансе"),
    "top_1": ("🏆", "Первое место", "Заняли #1 в рейтинге пар"),
    "pet_owner": ("🐾", "Хозяин питомца", "Завели питомца впервые"),
    "career_master": ("🎓", "Мастер своего дела", "Достигли максимального карьерного уровня"),
    "secret_admirer": ("🎁", "Тайный воздыхатель", "Отправили первый анонимный сюрприз"),
    "traveler": ("✈️", "Путешественник", "Съездили в первое совместное путешествие"),
}


@dataclass
class AchievementInfo:
    code: str
    emoji: str
    name: str
    description: str
    unlocked: bool


async def award(session: AsyncSession, user: User, code: str) -> bool:
    """
    Выдаёт достижение, если его ещё нет. Возвращает True, если оно было
    выдано именно сейчас (можно показать уведомление), False — если уже было.
    """
    if code not in ACHIEVEMENTS:
        raise ValueError(f"Неизвестный код достижения: {code}")

    result = await session.execute(
        select(UserAchievement).where(
            UserAchievement.user_id == user.id, UserAchievement.code == code
        )
    )
    if result.scalar_one_or_none() is not None:
        return False

    session.add(UserAchievement(user_id=user.id, code=code))
    await session.commit()
    return True


def format_unlock_text(code: str) -> str:
    emoji, name, description = ACHIEVEMENTS[code]
    return f"🎖️ Новое достижение!\n{emoji} {name} — {description}"


async def get_unlocked_codes(session: AsyncSession, user_id: int) -> set[str]:
    result = await session.execute(
        select(UserAchievement.code).where(UserAchievement.user_id == user_id)
    )
    return set(result.scalars().all())


async def get_all_achievements_status(session: AsyncSession, user_id: int) -> list[AchievementInfo]:
    unlocked = await get_unlocked_codes(session, user_id)
    return [
        AchievementInfo(
            code=code,
            emoji=emoji,
            name=name,
            description=description,
            unlocked=code in unlocked,
        )
        for code, (emoji, name, description) in ACHIEVEMENTS.items()
    ]


async def award_couple(session: AsyncSession, users, code: str) -> list[User]:
    """
    Выдаёт достижение сразу обоим партнёрам. Возвращает список тех, кому
    оно было выдано именно сейчас — чтобы отправить ОДНО общее уведомление
    на обоих, а не два отдельных подряд.
    """
    newly_unlocked = []
    for u in users:
        if await award(session, u, code):
            newly_unlocked.append(u)
    return newly_unlocked


async def check_balance_milestones(session: AsyncSession, user: User) -> list[str]:
    """
    Проверяет денежные вехи по текущему балансу пользователя.
    Возвращает список кодов, которые были выданы именно сейчас.
    """
    newly_unlocked = []
    if user.balance >= 1000 and await award(session, user, "rich"):
        newly_unlocked.append("rich")
    if user.balance >= 10000 and await award(session, user, "very_rich"):
        newly_unlocked.append("very_rich")
    return newly_unlocked
