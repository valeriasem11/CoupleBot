"""
Хендлеры питомцев: /petshop (покупка), /pet (карточка/список), /name_pet
(переименовать), /pet_actions (взаимодействие).

Лимит питомцев зависит от дома (см. pet_service.get_pet_limit) — без дома
всегда можно завести только одного, с домом — по его вместимости.
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.services.achievement_service import award_couple, format_unlock_text
from bot.services.pet_service import (
    PET_ACTIONS,
    PET_SEARCH_PAID_PREFIX,
    PET_SEARCH_POSTER_PREFIX,
    PetError,
    adopt_pet,
    choose_poster_search,
    format_timedelta,
    get_all_species,
    get_pet_action_cooldown_remaining,
    get_pet_by_id,
    get_pet_limit,
    get_pets,
    get_species_by_id,
    mood_label,
    pay_for_search,
    perform_pet_action,
    rename_pet,
)
from bot.services.relationship_service import get_active_relationship, get_partner

router = Router(name="pets")

PET_BUY_PREFIX = "pet_buy:"
PET_ACTION_PREFIX = "pet_action:"
PICK_PET_PREFIX = "pet_pick:"


async def _get_user(message_or_callback, session: AsyncSession):
    from_user = message_or_callback.from_user
    chat = getattr(message_or_callback, "message", message_or_callback).chat
    return await get_or_create_user(
        session=session,
        telegram_id=from_user.id,
        username=from_user.username,
        first_name=from_user.first_name,
        chat_id=chat.id,
    )


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name


def _build_pet_species_keyboard(species_list) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{s.name} — {s.price} 🪙", callback_data=f"{PET_BUY_PREFIX}{s.id}"
            )
        ]
        for s in species_list
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_pick_pet_keyboard(pets) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"🐾 {p.name}", callback_data=f"{PICK_PET_PREFIX}{p.id}")]
        for p in pets
        if not p.is_missing
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_pet_actions_keyboard(pet_id: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for code, action in PET_ACTIONS.items():
        row.append(
            InlineKeyboardButton(
                text=f"{action['emoji']} {action['name']}",
                callback_data=f"{PET_ACTION_PREFIX}{pet_id}:{code}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------------------------------------------------------------------
# /petshop — покупка питомца
# ---------------------------------------------------------------------------


@router.message(Command("petshop"))
async def cmd_petshop(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    existing_pets = await get_pets(session, relationship.id)
    limit = get_pet_limit(relationship)

    if len(existing_pets) >= limit:
        if relationship.house is None:
            await message.answer(
                f"У вашей пары уже есть питомец. Без дома можно завести только одного — "
                f"купите дом в /shop, чтобы заводить больше."
            )
        else:
            await message.answer(
                f"У вашей пары уже максимум питомцев для текущего дома ({limit}). "
                f"Нужен дом побольше — загляните в /shop."
            )
        return

    species_list = await get_all_species(session)
    slots_line = f" ({len(existing_pets)}/{limit})" if limit > 1 else ""
    await message.answer(
        f"🐾 Кого хотите завести?{slots_line}\n(деньги спишутся с твоего личного баланса)",
        reply_markup=_build_pet_species_keyboard(species_list),
    )


@router.callback_query(F.data.startswith(PET_BUY_PREFIX))
async def on_pet_buy(callback: CallbackQuery, session: AsyncSession):
    species_id = int(callback.data.removeprefix(PET_BUY_PREFIX))
    species = await get_species_by_id(session, species_id)
    if species is None:
        await callback.answer("Этот питомец больше не продаётся.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)
    if relationship is None:
        await callback.answer("У тебя больше нет пары.", show_alert=True)
        return

    try:
        pet = await adopt_pet(session, relationship, user, species)
    except PetError as e:
        await callback.answer(str(e), show_alert=True)
        return

    partner = get_partner(relationship, user.id)
    await callback.message.edit_text(
        f"🎉 {_mention(user)} завёл(-а) питомца для пары с {_mention(partner)}: "
        f"{species.name} по имени {pet.name}!\n\n"
        f"Переименовать: /name_pet (имя)\nВзаимодействовать: /pet_actions"
    )

    newly_unlocked = await award_couple(session, (relationship.user1, relationship.user2), "pet_owner")
    if newly_unlocked:
        names = " и ".join(_mention(u) for u in newly_unlocked)
        await callback.message.answer(f"{names}\n{format_unlock_text('pet_owner')}")

    await callback.answer()


# ---------------------------------------------------------------------------
# /name_pet — переименовать питомца
# ---------------------------------------------------------------------------


@router.message(Command("name_pet"))
async def cmd_name_pet(message: Message, command: CommandObject, session: AsyncSession):
    if command.args is None or not command.args.strip():
        await message.answer("Укажи имя, например: /name_pet Барсик")
        return

    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    pets = await get_pets(session, relationship.id)
    if not pets:
        await message.answer("У вашей пары пока нет питомца. Завести: /petshop")
        return

    args = command.args.strip()

    if len(pets) == 1:
        name = args
        target_pet = pets[0]
    else:
        # Несколько питомцев — первое слово должно быть номером из /pet
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            listing = "\n".join(f"{i}. {p.name}" for i, p in enumerate(pets, start=1))
            await message.answer(
                f"У вас несколько питомцев — укажи номер и новое имя, например: "
                f"/name_pet 2 Барсик\n\n{listing}"
            )
            return

        index = int(parts[0]) - 1
        if index < 0 or index >= len(pets):
            await message.answer(f"Такого номера нет — их всего {len(pets)}.")
            return

        target_pet = pets[index]
        name = parts[1]

    if len(name) > 100:
        await message.answer("Имя слишком длинное.")
        return

    pet = await rename_pet(session, target_pet, name)
    await message.answer(f"🐾 Теперь этого питомца зовут {pet.name}!")


# ---------------------------------------------------------------------------
# /pet — карточка(и) питомца
# ---------------------------------------------------------------------------


@router.message(Command("pet"))
async def cmd_pet(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    pets = await get_pets(session, relationship.id)
    if not pets:
        await message.answer("У вашей пары пока нет питомца. Завести: /petshop")
        return

    if len(pets) == 1:
        pet = pets[0]
        status_line = "🔍 В розыске..." if pet.is_missing else f"😊 Настроение: {mood_label(pet.mood)} ({pet.mood}%)"
        await message.answer(f"{pet.species.name.split(' ', 1)[0]} {pet.name}\n{status_line}")
        return

    lines = [f"🐾 Питомцы пары ({len(pets)}):", ""]
    for i, pet in enumerate(pets, start=1):
        emoji = pet.species.name.split(" ", 1)[0]
        status = "🔍 в розыске" if pet.is_missing else f"{mood_label(pet.mood)} ({pet.mood}%)"
        lines.append(f"{i}. {emoji} {pet.name} — {status}")

    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# /pet_actions — взаимодействие с питомцем
# ---------------------------------------------------------------------------


async def _send_pet_actions(target, pet, session: AsyncSession, edit: bool):
    cooldown_line = ""
    remaining = get_pet_action_cooldown_remaining(pet)
    if remaining is not None:
        cooldown_line = f"\n⏳ Следующее действие будет доступно через {format_timedelta(remaining)}"

    text = (
        f"🐾 {pet.name} · Настроение: {mood_label(pet.mood)} ({pet.mood}%)"
        f"{cooldown_line}\n\nВыбери действие:"
    )
    keyboard = _build_pet_actions_keyboard(pet.id)

    if edit:
        await target.message.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@router.message(Command("pet_actions"))
async def cmd_pet_actions(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    pets = await get_pets(session, relationship.id)
    available_pets = [p for p in pets if not p.is_missing]

    if not available_pets:
        if pets:
            await message.answer("Ваш питомец сейчас пропал — сначала попробуйте его вернуть.")
        else:
            await message.answer("У вашей пары пока нет питомца. Завести: /petshop")
        return

    if len(available_pets) == 1:
        await _send_pet_actions(message, available_pets[0], session, edit=False)
        return

    await message.answer(
        "У вас несколько питомцев — с кем взаимодействовать?",
        reply_markup=_build_pick_pet_keyboard(available_pets),
    )


@router.callback_query(F.data.startswith(PICK_PET_PREFIX))
async def on_pick_pet(callback: CallbackQuery, session: AsyncSession):
    pet_id = int(callback.data.removeprefix(PICK_PET_PREFIX))
    pet = await get_pet_by_id(session, pet_id)

    if pet is None or pet.is_missing:
        await callback.answer("Этот питомец сейчас недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)
    if relationship is None or pet.relationship_id != relationship.id:
        await callback.answer("Это не ваш питомец.", show_alert=True)
        return

    await _send_pet_actions(callback, pet, session, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith(PET_ACTION_PREFIX))
async def on_pet_action(callback: CallbackQuery, session: AsyncSession):
    payload = callback.data.removeprefix(PET_ACTION_PREFIX)
    pet_id_str, action_code = payload.split(":", 1)
    pet_id = int(pet_id_str)

    pet = await get_pet_by_id(session, pet_id)
    if pet is None or pet.is_missing:
        await callback.answer("Этот питомец сейчас недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id, user.chat_id)
    if relationship is None or pet.relationship_id != relationship.id:
        await callback.answer("Это не ваш питомец.", show_alert=True)
        return

    remaining = get_pet_action_cooldown_remaining(pet)
    if remaining is not None:
        await callback.answer(
            f"С питомцем уже недавно взаимодействовали. Попробуйте через {format_timedelta(remaining)}.",
            show_alert=True,
        )
        return

    result = await perform_pet_action(session, relationship, pet, action_code)
    action = PET_ACTIONS[action_code]

    text = (
        f"{action['emoji']} {action['name']} · {pet.name}\n\n"
        f"❤️ Близость пары: +{result.affection_gained}\n"
        f"😊 Настроение {pet.name}: +{result.mood_gained} (теперь {result.new_mood}%)"
    )
    await callback.message.edit_text(text)
    await callback.answer()


# ---------------------------------------------------------------------------
# Возврат сбежавшего питомца
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith(PET_SEARCH_POSTER_PREFIX))
async def on_pet_search_poster(callback: CallbackQuery, session: AsyncSession):
    pet_id = int(callback.data.removeprefix(PET_SEARCH_POSTER_PREFIX))
    pet = await get_pet_by_id(session, pet_id)
    if pet is None:
        await callback.answer("Этот питомец уже недоступен.", show_alert=True)
        return

    try:
        await choose_poster_search(session, pet)
    except PetError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(
        f"{callback.message.text}\n\n"
        f"📋 Вы расклеили объявления по району. Остаётся только ждать вестей..."
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PET_SEARCH_PAID_PREFIX))
async def on_pet_search_paid(callback: CallbackQuery, session: AsyncSession):
    pet_id = int(callback.data.removeprefix(PET_SEARCH_PAID_PREFIX))
    pet = await get_pet_by_id(session, pet_id)
    if pet is None:
        await callback.answer("Этот питомец уже недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)

    try:
        new_mood = await pay_for_search(session, pet, user)
    except PetError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(
        f"🎉 Поисковик нашёл {pet.name}! Питомец сразу вернулся домой "
        f"(настроение: {new_mood}%)."
    )
    await callback.answer()
