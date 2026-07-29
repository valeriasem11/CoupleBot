"""
Бизнес-логика карьерного роста: уровень зависит от количества отработанных
смен на ТЕКУЩЕЙ работе (сбрасывается при смене работы).
"""
from dataclasses import dataclass

# (порог смен, звание, множитель к базовой ЗП)
CAREER_LEVELS = [
    (0, "Новичок", 1.0),
    (10, "Специалист", 1.2),
    (25, "Старший специалист", 1.4),
    (50, "Эксперт", 1.6),
    (100, "Мастер своего дела", 2.0),
]


@dataclass
class CareerLevel:
    title: str
    multiplier: float
    shifts_worked: int
    shifts_to_next: int | None  # None — уже максимальный уровень
    next_title: str | None


def get_career_level(shifts_worked: int) -> CareerLevel:
    current_index = 0
    for i, (threshold, _, _) in enumerate(CAREER_LEVELS):
        if shifts_worked >= threshold:
            current_index = i

    threshold, title, multiplier = CAREER_LEVELS[current_index]

    if current_index + 1 < len(CAREER_LEVELS):
        next_threshold, next_title, _ = CAREER_LEVELS[current_index + 1]
        shifts_to_next = next_threshold - shifts_worked
    else:
        next_title = None
        shifts_to_next = None

    return CareerLevel(
        title=title,
        multiplier=multiplier,
        shifts_worked=shifts_worked,
        shifts_to_next=shifts_to_next,
        next_title=next_title,
    )


def is_max_level(shifts_worked: int) -> bool:
    return shifts_worked >= CAREER_LEVELS[-1][0]


def level_up_happened(shifts_before: int, shifts_after: int) -> str | None:
    """
    Если между "до" и "после" пересечён порог нового уровня — возвращает
    название нового звания, иначе None.
    """
    level_before = get_career_level(shifts_before)
    level_after = get_career_level(shifts_after)
    if level_after.title != level_before.title:
        return level_after.title
    return None
