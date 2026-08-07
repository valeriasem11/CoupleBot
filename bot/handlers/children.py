"""
Хендлеры детей: попытка зачатия, присвоение имени, список/карточки детей.
"""
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.database.models import ChildStatus
from bot.services.children_service import (
    AGE_STAGE_LABELS,
    ChildError,
    end_pregnancy,
    ensure_can_try_conceive,
    format_timedelta,
    get_active_children_count,
    get_child_by_id,
    get_children,
    get_conception_cooldown_remaining,
    mood_label,
    name_child,
    pickup_from_kindergarten,
    send_to_kindergarten,
    set_protection,
    trait_codes_to_labels,
    toy_codes_to_labels,
    try_conceive,
)
from bot.services.relationship_service import get_active_relationship

router = Router(name="children")

KINDERGARTEN_TOGGLE_PREFIX = "kindergarten_toggle:"


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


# ---------------------------------------------------------------------------
# /protection — включить/выключить защиту от зачатия
# ---------------------------------------------------------------------------


@router.message(Command("protection"))
async def cmd_protection(message: Message, command: CommandObject, session: AsyncSession):
    arg = (command.args or "").strip().lower()
    if arg not in ("on", "off", "вкл", "выкл"):
        await message.answer(
            "Укажи, включить или выключить защиту:\n"
            "/protection on — включить (зачатие будет заблокировано)\n"
            "/protection off — выключить"
        )
        return

    enabled = arg in ("on", "вкл")

    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    await set_protection(session, relationship, enabled)

    if enabled:
        await message.answer("🛡 Защита включена — зачатие ребёнка теперь заблокировано.")
    else:
        await message.answer("🛡 Защита выключена — зачатие снова возможно.")


# ---------------------------------------------------------------------------
# /end_pregnancy — прервать текущую беременность
# ---------------------------------------------------------------------------


@router.message(Command("end_pregnancy"))
async def cmd_end_pregnancy(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    try:
        await end_pregnancy(session, relationship)
    except ChildError as e:
        await message.answer(str(e))
        return

    await message.answer(
        "Беременность прервана по вашему решению.\n"
        "Следующая попытка зачатия будет доступна через 12 часов."
    )


# ---------------------------------------------------------------------------
# /kindergarten — отдать ребёнка в детский сад / забрать домой
# ---------------------------------------------------------------------------


def _build_kindergarten_keyboard(children_list: list) -> InlineKeyboardMarkup:
    buttons = []
    for child in children_list:
        label = child.name or "Без имени"
        text = f"🏠 Забрать {label} домой" if child.is_in_kindergarten else f"🏫 Отправить {label} в сад"
        buttons.append(
            [InlineKeyboardButton(text=text, callback_data=f"{KINDERGARTEN_TOGGLE_PREFIX}{child.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("kindergarten"))
async def cmd_kindergarten(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    all_children = await get_children(session, relationship.id)
    alive_children = [c for c in all_children if c.status == ChildStatus.ALIVE]

    if not alive_children:
        await message.answer("У вашей пары пока нет детей.")
        return

    lines = ["🏫 Детский сад", ""]
    for child in alive_children:
        label = child.name or "Без имени"
        status = "в саду 🏫 (действия недоступны, настроение угасает медленнее)" if child.is_in_kindergarten else "дома 🏠"
        lines.append(f"{label} — {status}")

    await message.answer(
        "\n".join(lines), reply_markup=_build_kindergarten_keyboard(alive_children)
    )


@router.callback_query(F.data.startswith(KINDERGARTEN_TOGGLE_PREFIX))
async def on_kindergarten_toggle(callback: CallbackQuery, session: AsyncSession):
    child_id = int(callback.data.removeprefix(KINDERGARTEN_TOGGLE_PREFIX))
    child = await get_child_by_id(session, child_id)

    if child is None or child.status != ChildStatus.ALIVE:
        await callback.answer("Этот ребёнок недоступен.", show_alert=True)
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        chat_id=callback.message.chat.id,
    )
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    label = child.name or "Без имени"
    try:
        if child.is_in_kindergarten:
            await pickup_from_kindergarten(session, child)
            await callback.message.edit_text(f"🏠 {label} забран(а) из детского сада домой.")
        else:
            await send_to_kindergarten(session, child)
            await callback.message.edit_text(
                f"🏫 {label} отправлен(а) в детский сад.\n"
                f"Действия с ним(ней) недоступны, пока он(а) там, но и настроение будет угасать медленнее."
            )
    except ChildError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.answer()
