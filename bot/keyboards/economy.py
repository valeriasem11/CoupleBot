"""
Клавиатуры, связанные с экономикой: выбор работы.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.models import Job

# Префикс для callback_data, чтобы отличать эти кнопки от других в боте
JOB_CALLBACK_PREFIX = "choose_job:"


def build_jobs_keyboard(jobs: list[Job]) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком работ, по одной кнопке в ряд.
    """
    buttons = [
        [InlineKeyboardButton(text=job.name, callback_data=f"{JOB_CALLBACK_PREFIX}{job.id}")]
        for job in jobs
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
