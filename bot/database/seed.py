"""
Скрипт для заполнения справочников стартовыми данными:
работы, дома, стадии отношений, действия.

Запуск: python -m bot.database.seed (из корня проекта, после миграций)

Значения тут — просто отправная точка для тестирования, баланс
игры (цены, зарплаты, кулдауны) будем донастраивать позже.
"""
import asyncio

from sqlalchemy import select

from bot.database.engine import async_session_maker
from bot.database.models import AgeStage, Car, ChildAction, House, Job, RelationshipAction, RelationshipStage, Toy


# Все работы косметические — одинаковая базовая ЗП и кулдаун у всех,
# отличаются только названием/эмодзи. Игрок выбирает по вкусу, а не по выгоде.
JOB_BASE_SALARY = 250
JOB_COOLDOWN_SECONDS = 6 * 3600  # 6 часов — чтобы бот не спамил в чате

JOBS = [
    {"code": "barista", "name": "☕ Бариста", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "courier", "name": "🍕 Курьер", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "seller", "name": "🛒 Продавец", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "hairdresser", "name": "💇 Парикмахер", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "cook", "name": "🍳 Повар", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "programmer", "name": "🖥️ Программист", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "designer", "name": "🎨 Дизайнер", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
    {"code": "photographer", "name": "📸 Фотограф", "salary": JOB_BASE_SALARY, "cooldown_seconds": JOB_COOLDOWN_SECONDS},
]

HOUSES = [
    {"code": "studio", "name": "🏠 Студия", "price": 5000, "max_children": 0, "order": 1},
    {"code": "small_house", "name": "🏡 Небольшой дом", "price": 12000, "max_children": 1, "order": 2},
    {"code": "townhouse", "name": "🏘 Таунхаус", "price": 25000, "max_children": 2, "order": 3},
    {"code": "cottage", "name": "🌳 Загородный коттедж", "price": 45000, "max_children": 3, "order": 4},
    {"code": "mansion", "name": "🏛 Роскошный особняк", "price": 80000, "max_children": 4, "order": 5},
    {"code": "villa", "name": "🏰 Семейная вилла", "price": 150000, "max_children": 5, "order": 6},
]

CARS = [
    {"code": "lada_granta", "name": "🚗 LADA Granta", "price": 4000, "order": 1},
    {"code": "kia_rio", "name": "🚙 Kia Rio", "price": 9000, "order": 2},
    {"code": "toyota_camry", "name": "🚘 Toyota Camry", "price": 18000, "order": 3},
    {"code": "bmw_5_series", "name": "🚕 BMW 5 Series", "price": 35000, "order": 4},
    {"code": "mercedes_g_class", "name": "🛻 Mercedes-Benz G-Class", "price": 70000, "order": 5},
    {"code": "lamborghini_huracan", "name": "🏎 Lamborghini Huracán", "price": 130000, "order": 6},
]

RELATIONSHIP_STAGES = [
    {"code": "sympathy", "name": "🥰 Симпатия", "order": 1, "min_affection_points": 0, "is_marriage": False},
    {"code": "dating", "name": "❤️ Отношения", "order": 2, "min_affection_points": 150, "is_marriage": False},
    {"code": "love", "name": "💞 Влюблённость", "order": 3, "min_affection_points": 500, "is_marriage": False},
    {"code": "engaged", "name": "💍 Помолвка", "order": 4, "min_affection_points": 1200, "is_marriage": False},
    {"code": "married", "name": "👰 Брак", "order": 5, "min_affection_points": 2500, "is_marriage": True},
]

# min_stage_order — с какой стадии (по полю order у RelationshipStage) действие становится
# доступно. Стадия "Отношения" (order=2) своих действий не имеет — ей продолжают служить
# действия "Симпатии" (min_stage_order=1), просто пара уже накопила больше очков к этому моменту.
#
# log_verb — глагольная фраза в прошедшем времени для лога вида
# "{эмодзи} | @инициатор {log_verb} @партнёр (+N ❤️)". Используется нейтральная форма
# рода "(а)"/"(-ась)", т.к. пол участников не запрашивается при регистрации.
RELATIONSHIP_ACTIONS = [
    # Симпатия (доступны с order >= 1, т.е. и на "Отношениях" тоже)
    {"code": "smile", "name": "😊 Улыбнуться", "emoji": "😊", "log_verb": "улыбнулся(-ась)", "min_stage_order": 1, "cooldown_seconds": 3600, "affection_reward": 3},
    {"code": "wink", "name": "😉 Подмигнуть", "emoji": "😉", "log_verb": "подмигнул(а)", "min_stage_order": 1, "cooldown_seconds": 7200, "affection_reward": 5},
    {"code": "compliment", "name": "💬 Сделать комплимент", "emoji": "💬", "log_verb": "сделал(а) комплимент", "min_stage_order": 1, "cooldown_seconds": 7200, "affection_reward": 8},
    {"code": "flowers", "name": "💐 Подарить цветы", "emoji": "💐", "log_verb": "подарил(а) цветы", "min_stage_order": 1, "cooldown_seconds": 10800, "affection_reward": 12},
    {"code": "invite_food", "name": "☕️ Пригласить покушать", "emoji": "☕️", "log_verb": "пригласил(а) покушать", "min_stage_order": 1, "cooldown_seconds": 14400, "affection_reward": 15},
    {"code": "send_track", "name": "🎵 Отправить любимый трек", "emoji": "🎵", "log_verb": "отправил(а) любимый трек", "min_stage_order": 1, "cooldown_seconds": 18000, "affection_reward": 19},

    # Отношения (order >= 2)
    {"code": "hug", "name": "🤗 Обнять", "emoji": "🤗", "log_verb": "обнял(а)", "min_stage_order": 2, "cooldown_seconds": 7200, "affection_reward": 10},
    {"code": "walk_together", "name": "🚶 Погулять вместе", "emoji": "🚶", "log_verb": "погулял(а) вместе с", "min_stage_order": 2, "cooldown_seconds": 10800, "affection_reward": 14},
    {"code": "watch_movie", "name": "🍿 Посмотреть фильм", "emoji": "🍿", "log_verb": "посмотрел(а) фильм с", "min_stage_order": 2, "cooldown_seconds": 14400, "affection_reward": 17},
    {"code": "cafe", "name": "🍰 Сходить в кафе", "emoji": "🍰", "log_verb": "сходил(а) в кафе с", "min_stage_order": 2, "cooldown_seconds": 18000, "affection_reward": 21},
    {"code": "selfie", "name": "📸 Сделать селфи", "emoji": "📸", "log_verb": "сделал(а) селфи с", "min_stage_order": 2, "cooldown_seconds": 21600, "affection_reward": 25},
    {"code": "small_gift", "name": "🎁 Подарить небольшой подарок", "emoji": "🎁", "log_verb": "подарил(а) небольшой подарок", "min_stage_order": 2, "cooldown_seconds": 28800, "affection_reward": 30},

    # Влюблённость (order >= 3)
    {"code": "kiss", "name": "😘 Поцеловать", "emoji": "😘", "log_verb": "поцеловал(а)", "min_stage_order": 3, "cooldown_seconds": 14400, "affection_reward": 18},
    {"code": "play_game", "name": "🎮 Сыграть катку", "emoji": "🎮", "log_verb": "сыграл(а) катку с", "min_stage_order": 3, "cooldown_seconds": 18000, "affection_reward": 23},
    {"code": "stars", "name": "🌃 Полюбоваться звёздами", "emoji": "🌃", "log_verb": "полюбовался(-ась) звёздами с", "min_stage_order": 3, "cooldown_seconds": 21600, "affection_reward": 28},
    {"code": "dance", "name": "🕺 Потанцевать вместе", "emoji": "🕺", "log_verb": "потанцевал(а) с", "min_stage_order": 3, "cooldown_seconds": 28800, "affection_reward": 33},
    {"code": "date_night", "name": "🌇 Устроить свидание", "emoji": "🌇", "log_verb": "устроил(а) свидание с", "min_stage_order": 3, "cooldown_seconds": 36000, "affection_reward": 39},
    {"code": "intimacy", "name": "😏 Заняться любовью", "emoji": "😏", "log_verb": "занялся(-ась) любовью с", "min_stage_order": 3, "cooldown_seconds": 43200, "affection_reward": 45},

    # Помолвка (order >= 4)
    {"code": "ring", "name": "💍 Подарить кольцо", "emoji": "💍", "log_verb": "подарил(а) кольцо", "min_stage_order": 4, "cooldown_seconds": 28800, "affection_reward": 30},
    {"code": "cook_together", "name": "🍽 Приготовить ужин вместе", "emoji": "🍽", "log_verb": "приготовил(а) ужин с", "min_stage_order": 4, "cooldown_seconds": 36000, "affection_reward": 36},
    {"code": "shopping", "name": "🛍 Сходить за покупками", "emoji": "🛍", "log_verb": "сходил(а) за покупками с", "min_stage_order": 4, "cooldown_seconds": 43200, "affection_reward": 42},
    {"code": "dream_house", "name": "🏡 Посмотреть дом мечты", "emoji": "🏡", "log_verb": "посмотрел(а) дом мечты с", "min_stage_order": 4, "cooldown_seconds": 50400, "affection_reward": 49},
    {"code": "plan_trip", "name": "✈️ Спланировать путешествие", "emoji": "✈️", "log_verb": "спланировал(а) путешествие с", "min_stage_order": 4, "cooldown_seconds": 57600, "affection_reward": 57},
    {"code": "engagement_party", "name": "🎉 Отпраздновать помолвку", "emoji": "🎉", "log_verb": "отпраздновал(а) помолвку с", "min_stage_order": 4, "cooldown_seconds": 72000, "affection_reward": 65},

    # Брак (order >= 5)
    {"code": "breakfast", "name": "🍳 Приготовить завтрак", "emoji": "🍳", "log_verb": "приготовил(а) завтрак с", "min_stage_order": 5, "cooldown_seconds": 36000, "affection_reward": 40},
    {"code": "cleaning", "name": "🧹 Сделать уборку вместе", "emoji": "🧹", "log_verb": "сделал(а) уборку вместе с", "min_stage_order": 5, "cooldown_seconds": 43200, "affection_reward": 47},
    {"code": "family_evening", "name": "🎬 Устроить семейный вечер", "emoji": "🎬", "log_verb": "устроил(а) семейный вечер с", "min_stage_order": 5, "cooldown_seconds": 57600, "affection_reward": 55},
    {"code": "kids_time", "name": "👶 Провести время с детьми", "emoji": "👶", "log_verb": "провёл(провела) время с детьми вместе с", "min_stage_order": 5, "cooldown_seconds": 72000, "affection_reward": 63},
    {"code": "vacation", "name": "🚗 Поехать в отпуск", "emoji": "🚗", "log_verb": "поехал(а) в отпуск с", "min_stage_order": 5, "cooldown_seconds": 86400, "affection_reward": 72},
    {"code": "romantic_evening", "name": "❤️ Устроить романтический вечер", "emoji": "❤️", "log_verb": "устроил(а) романтический вечер с", "min_stage_order": 5, "cooldown_seconds": 172800, "affection_reward": 82},
]


# Действия с ребёнком, привязанные к возрастной стадии.
#
# bonus_trait — если у ребёнка есть эта черта характера, награда за действие
# увеличивается (см. TRAIT_BONUS_MULTIPLIER в children_service.py).
CHILD_ACTIONS = [
    # Младенец (BABY)
    {"code": "feed", "name": "🍼 Покормить", "stage": AgeStage.BABY, "affection_reward": 3, "mood_reward": 15, "bonus_trait": "caring"},
    {"code": "put_to_sleep", "name": "😴 Уложить спать", "stage": AgeStage.BABY, "affection_reward": 3, "mood_reward": 15, "bonus_trait": "caring"},
    {"code": "change_diaper", "name": "🧷 Поменять подгузник", "stage": AgeStage.BABY, "affection_reward": 3, "mood_reward": 12, "bonus_trait": "caring"},

    # Малыш (TODDLER)
    {"code": "play_toys", "name": "🧸 Поиграть с игрушками", "stage": AgeStage.TODDLER, "affection_reward": 4, "mood_reward": 16, "bonus_trait": "active"},
    {"code": "teach_words", "name": "🗣️ Научить говорить слова", "stage": AgeStage.TODDLER, "affection_reward": 4, "mood_reward": 17, "bonus_trait": "curious"},
    {"code": "puzzle", "name": "🧩 Собрать пазл", "stage": AgeStage.TODDLER, "affection_reward": 4, "mood_reward": 17, "bonus_trait": "creative"},

    # Ребёнок (CHILD)
    {"code": "play", "name": "⚽ Поиграть", "stage": AgeStage.CHILD, "affection_reward": 4, "mood_reward": 18, "bonus_trait": "active"},
    {"code": "park", "name": "🎡 Сходить в парк", "stage": AgeStage.CHILD, "affection_reward": 5, "mood_reward": 20, "bonus_trait": "active"},
    {"code": "story", "name": "📖 Почитать сказку", "stage": AgeStage.CHILD, "affection_reward": 4, "mood_reward": 18, "bonus_trait": "curious"},

    # Подросток (TEEN)
    {"code": "video_games", "name": "🎮 Поиграть в игры", "stage": AgeStage.TEEN, "affection_reward": 5, "mood_reward": 20, "bonus_trait": "creative"},
    {"code": "bike", "name": "🚲 Научить кататься на велосипеде", "stage": AgeStage.TEEN, "affection_reward": 6, "mood_reward": 22, "bonus_trait": "brave"},
    {"code": "homework", "name": "📚 Помочь с уроками", "stage": AgeStage.TEEN, "affection_reward": 5, "mood_reward": 18, "bonus_trait": "curious"},
]


TOYS = [
    {"code": "teddy_bear", "name": "🧸 Плюшевый мишка", "price": 500, "mood_decay_reduction": 0.10, "order": 1},
    {"code": "kite", "name": "🪁 Воздушный змей", "price": 800, "mood_decay_reduction": 0.12, "order": 2},
    {"code": "train", "name": "🚂 Паровозик", "price": 1000, "mood_decay_reduction": 0.15, "order": 3},
    {"code": "art_set", "name": "🎨 Набор для рисования", "price": 1500, "mood_decay_reduction": 0.15, "order": 4},
    {"code": "bicycle", "name": "🚲 Велосипед", "price": 2000, "mood_decay_reduction": 0.20, "order": 5},
    {"code": "console", "name": "🎮 Игровая приставка", "price": 3000, "mood_decay_reduction": 0.25, "order": 6},
]


async def seed_table(session, model, rows: list[dict], unique_field: str = "code"):
    """
    "Умное" (декларативное) заполнение справочника:
    - если в базе есть запись, которой больше нет в текущем списке (код переименован
      или убран) — удаляет её;
    - если запись с таким кодом уже есть — обновляет её поля под актуальные значения;
    - если нет — создаёт.

    Для таблиц с уникальным полем order (House, Car, RelationshipStage) сначала
    "освобождает" order у всех сохраняемых записей (временные отрицательные значения),
    чтобы при перестановке порядка не возникало конфликтов уникальности в процессе
    (например, если новый order одной записи временно совпадает со старым order другой).
    """
    incoming_codes = {row[unique_field] for row in rows}
    has_order = bool(rows) and "order" in rows[0]

    result = await session.execute(select(model))
    existing_by_code = {}
    for existing in result.scalars().all():
        code = getattr(existing, unique_field)
        if code not in incoming_codes:
            await session.delete(existing)
        else:
            existing_by_code[code] = existing
    await session.flush()

    if has_order:
        for i, existing in enumerate(existing_by_code.values(), start=1):
            existing.order = -i  # временное безопасное значение, вне диапазона реальных order
        await session.flush()

    for row in rows:
        existing = existing_by_code.get(row[unique_field])
        if existing is None:
            session.add(model(**row))
        else:
            for field, value in row.items():
                setattr(existing, field, value)

    await session.commit()


async def main():
    async with async_session_maker() as session:
        await seed_table(session, Job, JOBS)
        await seed_table(session, House, HOUSES)
        await seed_table(session, Car, CARS)
        await seed_table(session, RelationshipStage, RELATIONSHIP_STAGES)
        await seed_table(session, RelationshipAction, RELATIONSHIP_ACTIONS)
        await seed_table(session, ChildAction, CHILD_ACTIONS)
        await seed_table(session, Toy, TOYS)
    print("Справочники успешно заполнены.")


if __name__ == "__main__":
    asyncio.run(main())
