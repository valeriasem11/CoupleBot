"""
Middleware, который на каждое входящее сообщение/callback открывает
сессию SQLAlchemy и передаёт её в хендлер через аргумент `session`.

Благодаря этому в хендлерах не нужно вручную открывать/закрывать сессию —
она уже готова к использованию.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.database.engine import async_session_maker


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session_maker() as session:
            data["session"] = session
            return await handler(event, data)
