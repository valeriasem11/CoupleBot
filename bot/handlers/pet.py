"""
Хендлеры питомцев: /petshop (покупка), /pet (карточка), /name_pet (переименовать),
/pet_actions (взаимодействие).
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.keyboards.pet import (
    PET_ACTION_PREFIX,
    PET_BUY_PREFIX,
    build_pet_actions_keyboard,
    build_pet_species_keyboard,
)
from bot.services.achievement_service import award, format_unlock_text
from bot.services.pet_service import (
    PET_ACTIONS,
    PetError,
    adopt_pet,
    format_timedelta,
    get_all_species,
    get_pet,
    get_pet_action_cooldown_remaining,
    get_species_by_id,
    mood_label,
    perform_pet_action,
    rename_pet,
)
from bot.services.relationship_service import get_active_relationship, get_partner

router = Router(name="pets")


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


@router.message(Command("petshop"))
async def cmd_petshop(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    existing = await get_pet(session, relationship.id)
    if existing is not None:
        await message.answer(
            f"У вашей пары уже есть питомец — {existing.name}. Посмотреть: /pet"
        )
        return

    species_list = await get_all_species(session)
    await message.answer(
        "🐾 Кого хотите завести?\n(деньги спишутся с твоего личного баланса)",
        reply_markup=build_pet_species_keyboard(species_list),
    )


@router.callback_query(F.data.startswith(PET_BUY_PREFIX))
async def on_pet_buy(callback: CallbackQuery, session: AsyncSession):
    species_id = int(callback.data.removeprefix(PET_BUY_PREFIX))
    species = await get_species_by_id(session, species_id)
    if species is None:
        await callback.answer("Этот питомец больше не продаётся.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
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

    for partner_user in (relationship.user1, relationship.user2):
        if await award(session, partner_user, "pet_owner"):
            await callback.message.answer(f"{_mention(partner_user)}\n{format_unlock_text('pet_owner')}")

    await callback.answer()


@router.message(Command("name_pet"))
async def cmd_name_pet(message: Message, command: CommandObject, session: AsyncSession):
    if command.args is None or not command.args.strip():
        await message.answer("Укажи имя, например: /name_pet Барсик")
        return

    name = command.args.strip()
    if len(name) > 100:
        await message.answer("Имя слишком длинное.")
        return

    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    try:
        pet = await rename_pet(session, relationship.id, name)
    except PetError as e:
        await message.answer(str(e))
        return

    await message.answer(f"🐾 Теперь вашего питомца зовут {pet.name}!")


@router.message(Command("pet"))
async def cmd_pet(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    pet = await get_pet(session, relationship.id)
    if pet is None:
        await message.answer("У вашей пары пока нет питомца. Завести: /petshop")
        return

    await message.answer(
        f"{pet.species.name.split(' ', 1)[0]} {pet.name}\n"
        f"😊 Настроение: {mood_label(pet.mood)} ({pet.mood}%)"
    )


@router.message(Command("pet_actions"))
async def cmd_pet_actions(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    pet = await get_pet(session, relationship.id)
    if pet is None:
        await message.answer("У вашей пары пока нет питомца. Завести: /petshop")
        return

    cooldown_line = ""
    remaining = get_pet_action_cooldown_remaining(pet)
    if remaining is not None:
        cooldown_line = f"\n⏳ Следующее действие будет доступно через {format_timedelta(remaining)}"

    await message.answer(
        f"🐾 {pet.name} · Настроение: {mood_label(pet.mood)} ({pet.mood}%)"
        f"{cooldown_line}\n\nВыбери действие:",
        reply_markup=build_pet_actions_keyboard(PET_ACTIONS),
    )


@router.callback_query(F.data.startswith(PET_ACTION_PREFIX))
async def on_pet_action(callback: CallbackQuery, session: AsyncSession):
    action_code = callback.data.removeprefix(PET_ACTION_PREFIX)

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await callback.answer("У тебя больше нет пары.", show_alert=True)
        return

    pet = await get_pet(session, relationship.id)
    if pet is None:
        await callback.answer("У вашей пары больше нет питомца.", show_alert=True)
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
