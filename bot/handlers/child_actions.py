"""
Хендлер действий с ребёнком: /child_actions, выбор ребёнка (если их несколько),
выбор и выполнение действия.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.database.models import ChildStatus
from bot.keyboards.children import (
    CHILD_ACTION_PREFIX,
    EVENT_GIFT_PREFIX,
    EVENT_PRAISE_PREFIX,
    PICK_CHILD_PREFIX,
    build_child_actions_keyboard,
    build_pick_child_keyboard,
)
from bot.services.children_service import (
    ChildError,
    format_timedelta,
    get_available_child_actions,
    get_child_action_by_code,
    get_child_action_cooldown_remaining,
    get_child_by_id,
    get_children,
    gift_child,
    mood_label,
    perform_child_action,
    praise_child,
)
from bot.services.relationship_service import get_active_relationship

router = Router(name="child_actions")


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


async def _send_actions_for_child(target, child, session: AsyncSession, edit: bool):
    actions = await get_available_child_actions(session, child)
    label = child.name or "Без имени"

    cooldown_line = ""
    remaining = get_child_action_cooldown_remaining(child)
    if remaining is not None:
        cooldown_line = f"\n⏳ Следующее действие будет доступно через {format_timedelta(remaining)}"

    text = (
        f"👶 {label}\n"
        f"😊 Настроение: {mood_label(child.mood)} ({child.mood}%)"
        f"{cooldown_line}\n\n"
        f"Выберите действие:"
    )
    keyboard = build_child_actions_keyboard(child.id, actions)

    if edit:
        await target.message.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@router.message(Command("child_actions"))
async def cmd_child_actions(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    all_children = await get_children(session, relationship.id)
    alive_children = [c for c in all_children if c.status == ChildStatus.ALIVE]

    if not alive_children:
        if any(c.status == ChildStatus.PREGNANT for c in all_children):
            await message.answer("Ваш ребёнок ещё не родился — подождите немного.")
        else:
            await message.answer("У вашей пары пока нет детей. Попробуйте /have_child.")
        return

    unnamed = [c for c in alive_children if c.name is None]
    if unnamed:
        await message.answer(
            "У вас есть ребёнок без имени — сначала дайте ему имя: /name_child (имя)"
        )
        return

    if len(alive_children) == 1:
        await _send_actions_for_child(message, alive_children[0], session, edit=False)
        return

    await message.answer(
        "У вас несколько детей — выберите, с кем взаимодействовать:",
        reply_markup=build_pick_child_keyboard(alive_children),
    )


@router.callback_query(F.data.startswith(PICK_CHILD_PREFIX))
async def on_pick_child(callback: CallbackQuery, session: AsyncSession):
    child_id = int(callback.data.removeprefix(PICK_CHILD_PREFIX))
    child = await get_child_by_id(session, child_id)

    if child is None or child.status != ChildStatus.ALIVE:
        await callback.answer("Этот ребёнок недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    await _send_actions_for_child(callback, child, session, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith(CHILD_ACTION_PREFIX))
async def on_child_action(callback: CallbackQuery, session: AsyncSession):
    payload = callback.data.removeprefix(CHILD_ACTION_PREFIX)
    child_id_str, action_code = payload.split(":", 1)
    child_id = int(child_id_str)

    child = await get_child_by_id(session, child_id)
    if child is None or child.status != ChildStatus.ALIVE:
        await callback.answer("Этот ребёнок недоступен.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    action = await get_child_action_by_code(session, action_code)
    available_actions = await get_available_child_actions(session, child)
    if action is None or action.code not in {a.code for a in available_actions}:
        await callback.answer("Это действие сейчас недоступно.", show_alert=True)
        return

    remaining = get_child_action_cooldown_remaining(child)
    if remaining is not None:
        await callback.answer(
            f"С этим ребёнком уже недавно взаимодействовали. "
            f"Попробуйте через {format_timedelta(remaining)}.",
            show_alert=True,
        )
        return

    result = await perform_child_action(session, relationship, child, action)

    label = child.name or "Без имени"
    bonus_note = " ✨ (бонус за черту характера!)" if result.trait_bonus_applied else ""
    text = (
        f"{action.name} с {label}{bonus_note}\n\n"
        f"❤️ Близость пары: +{result.affection_gained}\n"
        f"😊 Настроение {label}: +{result.mood_gained} (теперь {result.new_mood}%)"
    )

    await callback.message.edit_text(text)
    await callback.answer()


# ---------------------------------------------------------------------------
# Реакция на случайное событие (👶 ребёнок нарисовал рисунок и т.п.)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith(EVENT_PRAISE_PREFIX))
async def on_event_praise(callback: CallbackQuery, session: AsyncSession):
    child_id = int(callback.data.removeprefix(EVENT_PRAISE_PREFIX))
    child = await get_child_by_id(session, child_id)
    if child is None:
        await callback.answer("Событие уже неактуально.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    gained = await praise_child(session, relationship)
    await callback.message.edit_text(f"{callback.message.text}\n\n❤️ Похвалили! +{gained} близости паре.")
    await callback.answer()


@router.callback_query(F.data.startswith(EVENT_GIFT_PREFIX))
async def on_event_gift(callback: CallbackQuery, session: AsyncSession):
    child_id = int(callback.data.removeprefix(EVENT_GIFT_PREFIX))
    child = await get_child_by_id(session, child_id)
    if child is None:
        await callback.answer("Событие уже неактуально.", show_alert=True)
        return

    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)
    if relationship is None or child.relationship_id != relationship.id:
        await callback.answer("Это не ваш ребёнок.", show_alert=True)
        return

    try:
        await gift_child(session, relationship, child)
    except ChildError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(f"{callback.message.text}\n\n🎁 Подарок подарен! Ребёнок счастлив.")
    await callback.answer()
