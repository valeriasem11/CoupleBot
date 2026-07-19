"""
Хендлеры детей: попытка зачатия, присвоение имени, список/карточки детей.
"""
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.database.models import ChildStatus
from bot.services.children_service import (
    AGE_STAGE_LABELS,
    ChildError,
    ensure_can_try_conceive,
    format_timedelta,
    get_active_children_count,
    get_children,
    get_conception_cooldown_remaining,
    mood_label,
    name_child,
    trait_codes_to_labels,
    toy_codes_to_labels,
    try_conceive,
)
from bot.services.relationship_service import get_active_relationship

router = Router(name="children")


async def _get_user(message, session: AsyncSession):
    return await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        chat_id=message.chat.id,
    )


@router.message(Command("have_child"))
async def cmd_have_child(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    active_count = await get_active_children_count(session, relationship.id)
    try:
        ensure_can_try_conceive(relationship, active_count)
    except ChildError as e:
        await message.answer(str(e))
        return

    remaining = get_conception_cooldown_remaining(relationship)
    if remaining is not None:
        await message.answer(
            f"Пара пока отдыхает — следующая попытка будет доступна через "
            f"{format_timedelta(remaining)}."
        )
        return

    result = await try_conceive(session, relationship)

    if result.success:
        await message.answer(
            "🤰 Получилось! Через 3 дня у вас родится ребёнок — бот сам напишет об этом в чат."
        )
    else:
        await message.answer(
            "😔 В этот раз не получилось. Попробуйте ещё раз позже (следующая попытка — через 12 часов)."
        )


@router.message(Command("name_child"))
async def cmd_name_child(message: Message, command: CommandObject, session: AsyncSession):
    if command.args is None or not command.args.strip():
        await message.answer("Укажи имя, например: /name_child София")
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
        child = await name_child(session, relationship, name)
    except ChildError as e:
        await message.answer(str(e))
        return

    emoji = "👦" if child.gender.value == "male" else "👧"
    await message.answer(f"{emoji} Теперь вашего ребёнка зовут {child.name}!")


@router.message(Command("children"))
async def cmd_children(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    children = await get_children(session, relationship.id)

    if not children:
        await message.answer(
            "У вашей пары пока нет детей.\n"
            "Если вы в браке и у вас есть дом со свободным местом — попробуйте /have_child."
        )
        return

    now = datetime.now(timezone.utc)
    blocks = []

    for child in children:
        if child.status == ChildStatus.PREGNANT:
            due_at = child.due_at
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            remaining = due_at - now
            if remaining.total_seconds() > 0:
                blocks.append(f"🤰 Ожидаем рождения (осталось {format_timedelta(remaining)})")
            else:
                blocks.append("🤰 Роды вот-вот начнутся...")
            continue

        name = child.name or "(пока без имени — используйте /name_child)"
        gender_emoji = "👦" if child.gender.value == "male" else "👧"
        gender_label = "Мальчик" if child.gender.value == "male" else "Девочка"
        traits = trait_codes_to_labels(child.traits)
        traits_block = "\n".join(f"• {t}" for t in traits) if traits else "—"
        toys = toy_codes_to_labels(child.owned_toys)
        toys_line = ", ".join(toys) if toys else "нет"

        blocks.append(
            f"{gender_emoji} {name}\n"
            f"⚥ Пол: {gender_label}\n"
            f"🎂 Возраст: {AGE_STAGE_LABELS[child.age_stage]}\n"
            f"😊 Настроение: {mood_label(child.mood)} ({child.mood}%)\n\n"
            f"🧬 Черты характера:\n{traits_block}\n\n"
            f"🧸 Игрушки: {toys_line}"
        )

    await message.answer("\n\n----------\n\n".join(blocks))
