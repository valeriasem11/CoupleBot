"""
Точка входа: запуск бота через long polling.

Запуск: python -m bot.main (из корня проекта)
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import config
from bot.handlers import casino, child_actions, children, economy, relationships, shop, start, toys
from bot.services.scheduler import setup_scheduler
from bot.middlewares.db_session import DbSessionMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Список команд, который Telegram покажет во всплывающей подсказке
# при вводе "/" в чате.
BOT_COMMANDS = [
    BotCommand(command="start", description="Начать / зарегистрироваться"),
    BotCommand(command="job", description="Выбрать работу"),
    BotCommand(command="work", description="Пойти на смену (раз в 6 часов)"),
    BotCommand(command="balance", description="Посмотреть баланс"),
    BotCommand(command="propose", description="Предложить отношения (ответом на сообщение)"),
    BotCommand(command="actions", description="Взаимодействовать с партнёром"),
    BotCommand(command="couple", description="Профиль пары"),
    BotCommand(command="marry", description="Сделать предложение руки и сердца"),
    BotCommand(command="breakup", description="Расстаться / развестись"),
    BotCommand(command="budget", description="Посмотреть семейный бюджет"),
    BotCommand(command="deposit", description="Положить деньги в семейный бюджет"),
    BotCommand(command="withdraw", description="Снять деньги с семейного бюджета"),
    BotCommand(command="shop", description="Магазин: дом, машина, игрушки для детей"),
    BotCommand(command="loan", description="Взять кредит"),
    BotCommand(command="repay", description="Погасить кредит"),
    BotCommand(command="casino", description="Казино: ставка на слот 🎰"),
    BotCommand(command="have_child", description="Попробовать зачать ребёнка (в браке)"),
    BotCommand(command="name_child", description="Дать имя новорождённому"),
    BotCommand(command="children", description="Список детей и их карточки"),
    BotCommand(command="child_actions", description="Взаимодействовать с ребёнком"),
]


async def main():
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Подключаем middleware, которое даёт хендлерам доступ к сессии БД
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    # Регистрируем роутеры с хендлерами
    dp.include_router(start.router)
    dp.include_router(economy.router)
    dp.include_router(relationships.router)
    dp.include_router(shop.router)
    dp.include_router(casino.router)
    dp.include_router(children.router)
    dp.include_router(child_actions.router)
    dp.include_router(toys.router)

    # На всякий случай сбрасываем накопленные апдейты перед стартом polling
    await bot.delete_webhook(drop_pending_updates=True)

    # Регистрируем список команд, чтобы Telegram показывал подсказку при вводе "/"
    await bot.set_my_commands(BOT_COMMANDS)

    # Фоновый планировщик — проверяет, не пора ли кому-то родить, и т.п.
    scheduler = setup_scheduler(bot)
    scheduler.start()

    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
