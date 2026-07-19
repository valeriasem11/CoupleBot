"""
Настройка асинхронного подключения к PostgreSQL через SQLAlchemy.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import config

# echo=False — если хочешь видеть в консоли все SQL-запросы, которые
# делает SQLAlchemy (полезно для отладки), поставь True
engine = create_async_engine(config.database_url, echo=False)

# Фабрика сессий. Через неё будем открывать сессию на каждый запрос к БД.
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncSession:
    """
    Простой помощник для получения сессии там, где не используется
    dependency injection (например, в отдельных скриптах).

    В хендлерах бота сессию удобнее получать через middleware —
    это добавим на следующем этапе.
    """
    async with async_session_maker() as session:
        yield session
