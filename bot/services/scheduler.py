"""
Фоновый планировщик задач.

Сейчас отвечает только за проверку "не пора ли родить" — раз в несколько минут
сканирует беременности, чей срок подошёл, оформляет роды и сам пишет об этом
в чат пары (используя сохранённый relationship.chat_id).

В следующих этапах сюда добавятся: угасание настроения ребёнка со временем,
автоматическое взросление, случайные события ("нарисовал(а) рисунок").
"""
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.database.engine import async_session_maker
from bot.keyboards.children import build_event_keyboard
from bot.services.children_service import get_due_pregnancies, give_birth, process_children_tick
from bot.services.economy_service import process_loans_tick

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MINUTES = 5


async def _check_pregnancies(bot: Bot) -> None:
    async with async_session_maker() as session:
        due_children = await get_due_pregnancies(session)

        for child in due_children:
            relationship = child.relationship_
            await give_birth(session, child)

            if relationship.chat_id is None:
                logger.warning(
                    "Ребёнок id=%s родился, но у пары id=%s нет сохранённого chat_id — "
                    "уведомление не отправлено.",
                    child.id,
                    relationship.id,
                )
                continue

            gender_word = "мальчик" if child.gender.value == "male" else "девочка"
            text = (
                f"🎉 Поздравляем! У вас родился(-лась) ребёнок ({gender_word})!\n\n"
                f"Дайте ему имя командой: /name_child (имя)"
            )
            try:
                await bot.send_message(relationship.chat_id, text)
            except Exception:
                logger.exception(
                    "Не удалось отправить уведомление о рождении ребёнка id=%s", child.id
                )


async def _process_children_growth_and_mood(bot: Bot) -> None:
    async with async_session_maker() as session:
        growth_events, removal_events, random_events = await process_children_tick(session)

        for event in growth_events:
            text = f"🎉 {event.child_name} подрос(-ла)! Новая стадия: {event.new_stage_label}"
            try:
                await bot.send_message(event.chat_id, text)
            except Exception:
                logger.exception("Не удалось отправить уведомление о взрослении ребёнка")

        for event in removal_events:
            text = (
                f"💔 Настроение ребёнка ({event.child_name}) упало до нуля — "
                f"его забрали в детский дом. Уделяйте детям больше внимания в /child_actions."
            )
            try:
                await bot.send_message(event.chat_id, text)
            except Exception:
                logger.exception("Не удалось отправить уведомление о потере ребёнка")

        for event in random_events:
            try:
                await bot.send_message(
                    event.chat_id, event.text, reply_markup=build_event_keyboard(event.child_id)
                )
            except Exception:
                logger.exception("Не удалось отправить случайное событие")


async def _process_loans(bot: Bot) -> None:
    async with async_session_maker() as session:
        events = await process_loans_tick(session)

        for event in events:
            text = (
                f"💳 {event.user_name}, напоминаем о непогашенном кредите!\n"
                f"За просрочку долг вырос на 5% и теперь составляет {event.new_debt} 🪙.\n\n"
                f"Погасить: /repay (сумма)"
            )
            try:
                await bot.send_message(event.chat_id, text)
            except Exception:
                logger.exception("Не удалось отправить напоминание о кредите")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _check_pregnancies,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[bot],
        id="check_pregnancies",
    )
    scheduler.add_job(
        _process_children_growth_and_mood,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[bot],
        id="process_children_growth_and_mood",
    )
    scheduler.add_job(
        _process_loans,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[bot],
        id="process_loans",
    )
    return scheduler
