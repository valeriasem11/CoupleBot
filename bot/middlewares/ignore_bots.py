"""
Middleware, которое полностью игнорирует любые сообщения и колбэки,
присланные не человеком, а ДРУГИМ ботом — наш бот не должен реагировать
на команды/кнопки от посторонних ботов в том же чате.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class IgnoreBotsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)

        if from_user is not None and from_user.is_bot:
            return  # молча обрываем цепочку — дальше в хендлеры не передаём

        return await handler(event, data)
