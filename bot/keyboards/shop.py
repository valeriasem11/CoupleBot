"""
Клавиатуры магазина: выбор категории, список домов/машин с ценами.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.models import Car, House

SHOP_HOUSES_PREFIX = "shop_houses"
SHOP_CARS_PREFIX = "shop_cars"
SHOP_TOYS_PREFIX = "shop_toys"
SHOP_MENU_PREFIX = "shop_menu"
BUY_HOUSE_PREFIX = "buy_house:"
BUY_CAR_PREFIX = "buy_car:"


def build_shop_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Дома", callback_data=SHOP_HOUSES_PREFIX)],
            [InlineKeyboardButton(text="🚗 Машины", callback_data=SHOP_CARS_PREFIX)],
            [InlineKeyboardButton(text="🧸 Игрушки", callback_data=SHOP_TOYS_PREFIX)],
        ]
    )


def build_houses_keyboard(houses: list[House], current_house_id: int | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for house in houses:
        mark = "✅ " if house.id == current_house_id else ""
        children_word = "детей" if house.max_children != 1 else "ребёнка"
        capacity = f"без детей" if house.max_children == 0 else f"до {house.max_children} {children_word}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{house.name} — {house.price} 🪙 ({capacity})",
                    callback_data=f"{BUY_HOUSE_PREFIX}{house.id}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=SHOP_MENU_PREFIX)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_cars_keyboard(cars: list[Car], current_car_id: int | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for car in cars:
        mark = "✅ " if car.id == current_car_id else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{car.name} — {car.price} 🪙",
                    callback_data=f"{BUY_CAR_PREFIX}{car.id}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=SHOP_MENU_PREFIX)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
