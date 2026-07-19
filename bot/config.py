"""
Загрузка конфигурации проекта из переменных окружения (.env файл).
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Загружаем переменные из .env файла, который лежит в корне проекта
load_dotenv()


@dataclass
class Config:
    bot_token: str
    database_url: str


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN")
    database_url = os.getenv("DATABASE_URL")

    if not bot_token:
        raise ValueError(
            "BOT_TOKEN не найден. Проверь, что файл .env существует "
            "и в нём указан токен бота."
        )
    if not database_url:
        raise ValueError(
            "DATABASE_URL не найден. Проверь, что файл .env существует "
            "и в нём указана строка подключения к базе данных."
        )

    return Config(bot_token=bot_token, database_url=database_url)


config = load_config()
