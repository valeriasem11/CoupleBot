"""
Категоризированное меню команд для /start — вместо длинного списка текстом.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MENU_CATEGORY_PREFIX = "menu_cat:"
MENU_BACK = "menu_back"

CATEGORIES = {
    "work": {
        "label": "💼 Работа и деньги",
        "commands": [
            ("/job", "Выбрать работу"),
            ("/work", "Пойти на смену (раз в 6 часов)"),
            ("/balance", "Посмотреть баланс"),
            ("/loan", "Взять кредит (до 15 000 🪙)"),
            ("/repay", "Погасить кредит"),
            ("/casino", "Казино: ставка на слот 🎰"),
        ],
    },
    "relationships": {
        "label": "💞 Отношения",
        "commands": [
            ("/propose", "Предложить отношения (ответом на сообщение)"),
            ("/actions", "Взаимодействовать с партнёром"),
            ("/couple", "Профиль пары"),
            ("/marry", "Сделать предложение руки и сердца"),
            ("/breakup", "Расстаться / развестись"),
        ],
    },
    "family": {
        "label": "🏠 Семья",
        "commands": [
            ("/budget", "Посмотреть семейный бюджет"),
            ("/deposit", "Положить деньги в бюджет"),
            ("/withdraw", "Снять деньги из бюджета"),
            ("/shop", "Магазин: дом, машина, игрушки"),
        ],
    },
    "children": {
        "label": "👶 Дети",
        "commands": [
            ("/have_child", "Попробовать зачать ребёнка (в браке)"),
            ("/name_child", "Дать имя новорождённому"),
            ("/children", "Список детей и карточки"),
            ("/child_actions", "Взаимодействовать с ребёнком"),
        ],
    },
}


def build_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for code, category in CATEGORIES.items():
        row.append(InlineKeyboardButton(text=category["label"], callback_data=f"{MENU_CATEGORY_PREFIX}{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_category_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=MENU_BACK)]]
    )


def format_category_text(code: str) -> str:
    category = CATEGORIES[code]
    lines = [category["label"], ""]
    for command, description in category["commands"]:
        lines.append(f"{command} — {description}")
    return "\n".join(lines)
