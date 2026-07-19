"""
Хендлеры системы отношений: предложение, действия пары, профиль пары, брак.
"""
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_or_create_user
from bot.keyboards.relationships import (
    ACTION_PREFIX,
    BREAKUP_CANCEL_PREFIX,
    BREAKUP_CONFIRM_PREFIX,
    MARRY_ACCEPT_PREFIX,
    MARRY_REJECT_PREFIX,
    PROPOSAL_ACCEPT_PREFIX,
    PROPOSAL_REJECT_PREFIX,
    build_actions_keyboard,
    build_breakup_confirm_keyboard,
    build_marry_keyboard,
    build_proposal_keyboard,
)
from bot.services.children_service import get_active_children_count
from bot.services.relationship_service import (
    RelationshipError,
    accept_proposal,
    can_marry,
    create_proposal,
    end_relationship,
    get_action_by_code,
    get_active_relationship,
    get_available_actions,
    get_partner,
    get_relationship_by_id,
    get_relationship_cooldown_remaining,
    marry,
    perform_action,
    reject_proposal,
    format_timedelta,
)

router = Router(name="relationships")


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
    """Кликабельное упоминание пользователя для сообщений в чат."""
    if user.username:
        return f"@{user.username}"
    return user.first_name


# ---------------------------------------------------------------------------
# /propose — предложение отношений (ответом на сообщение того, кому предлагаем)
# ---------------------------------------------------------------------------


@router.message(Command("propose"))
async def cmd_propose(message: Message, session: AsyncSession):
    if message.reply_to_message is None:
        await message.answer(
            "Чтобы предложить отношения, ответь этой командой на любое "
            "сообщение человека, которому хочешь предложить встречаться."
        )
        return

    target_tg_user = message.reply_to_message.from_user
    if target_tg_user.is_bot:
        await message.answer("Ботам отношения не положены 🙂")
        return

    proposer = await _get_user(message, session)
    target = await get_or_create_user(
        session=session,
        telegram_id=target_tg_user.id,
        username=target_tg_user.username,
        first_name=target_tg_user.first_name,
        chat_id=message.chat.id,
    )

    try:
        relationship = await create_proposal(session, proposer, target)
    except RelationshipError as e:
        await message.answer(str(e))
        return

    await message.answer(
        f"💌 {_mention(proposer)} предлагает {_mention(target)} встречаться!\n\n"
        f"{_mention(target)}, что скажешь?",
        reply_markup=build_proposal_keyboard(relationship.id),
    )


@router.callback_query(F.data.startswith(PROPOSAL_ACCEPT_PREFIX))
async def on_proposal_accept(callback: CallbackQuery, session: AsyncSession):
    relationship_id = int(callback.data.removeprefix(PROPOSAL_ACCEPT_PREFIX))
    relationship = await get_relationship_by_id(session, relationship_id)

    if relationship is None:
        await callback.answer("Это предложение больше не действительно.", show_alert=True)
        return

    responder = await _get_user(callback, session)
    if responder.id != relationship.user2_id:
        await callback.answer("Это предложение адресовано не тебе.", show_alert=True)
        return

    await accept_proposal(session, relationship, callback.message.chat.id)
    await session.refresh(relationship)

    await callback.message.edit_text(
        f"💞 {_mention(relationship.user1)} и {_mention(relationship.user2)} теперь встречаются!\n\n"
        f"Стадия: {relationship.stage.name}\n"
        f"Используйте /actions, чтобы взаимодействовать друг с другом."
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PROPOSAL_REJECT_PREFIX))
async def on_proposal_reject(callback: CallbackQuery, session: AsyncSession):
    relationship_id = int(callback.data.removeprefix(PROPOSAL_REJECT_PREFIX))
    relationship = await get_relationship_by_id(session, relationship_id)

    if relationship is None:
        await callback.answer("Это предложение больше не действительно.", show_alert=True)
        return

    responder = await _get_user(callback, session)
    if responder.id != relationship.user2_id:
        await callback.answer("Это предложение адресовано не тебе.", show_alert=True)
        return

    await reject_proposal(session, relationship)

    await callback.message.edit_text(
        f"💔 {_mention(relationship.user2)} отклонил(а) предложение {_mention(relationship.user1)}."
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# /actions — меню доступных действий пары
# ---------------------------------------------------------------------------


@router.message(Command("actions"))
async def cmd_actions(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары. Используй /propose, ответив на сообщение человека.")
        return

    actions = await get_available_actions(session, relationship)
    partner = get_partner(relationship, user.id)

    cooldown_line = ""
    remaining = await get_relationship_cooldown_remaining(session, relationship.id)
    if remaining is not None:
        cooldown_line = f"\n⏳ Следующее действие будет доступно через {format_timedelta(remaining)}"

    await message.answer(
        f"Стадия: {relationship.stage.name} · Близость: {relationship.affection_points} ❤️\n"
        f"Партнёр: {_mention(partner)}"
        f"{cooldown_line}\n\n"
        f"Выбери действие:",
        reply_markup=build_actions_keyboard(actions),
    )


@router.callback_query(F.data.startswith(ACTION_PREFIX))
async def on_action_selected(callback: CallbackQuery, session: AsyncSession):
    action_code = callback.data.removeprefix(ACTION_PREFIX)
    user = await _get_user(callback, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await callback.answer("У тебя больше нет активной пары.", show_alert=True)
        return

    action = await get_action_by_code(session, action_code)
    if action is None or action.min_stage_order > relationship.stage.order:
        await callback.answer("Это действие сейчас недоступно.", show_alert=True)
        return

    remaining = await get_relationship_cooldown_remaining(session, relationship.id)
    if remaining is not None:
        await callback.answer(
            f"Пара недавно уже выполняла действие. Следующее действие будет "
            f"доступно через {format_timedelta(remaining)}.",
            show_alert=True,
        )
        return

    result = await perform_action(session, relationship, action, user.id)
    await session.refresh(relationship)

    partner = get_partner(relationship, user.id)
    text = f"{action.emoji} | {_mention(user)} {action.log_verb} {_mention(partner)} (+{action.affection_reward} ❤️)"

    if result.stage_advanced:
        text += f"\n\n🎉 Новая стадия отношений: {result.new_stage.name}!"

    if result.ready_for_marriage and relationship.status.value == "active":
        text += "\n\n💍 Пара накопила достаточно близости для брака! Используйте /marry."

    await callback.message.answer(text)
    await callback.answer()


# ---------------------------------------------------------------------------
# /couple — профиль пары
# ---------------------------------------------------------------------------


@router.message(Command("couple"))
async def cmd_couple(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    partner = get_partner(relationship, user.id)
    now = datetime.now(timezone.utc)

    days_together = (now - relationship.started_at).days if relationship.started_at else 0

    lines = [
        f"💞 Профиль пары",
        f"{_mention(relationship.user1)} и {_mention(relationship.user2)}",
        "",
        f"⭐️ Стадия: {relationship.stage.name}",
        f"❤️ Близость: {relationship.affection_points}",
        "",
        f"📅 Вместе: {days_together} дн.",
    ]

    if relationship.married_at:
        days_married = (now - relationship.married_at).days
        lines.append(f"💍 В браке: {days_married} дн.")

    if relationship.status.value == "married":
        lines.append("")
        children_count = await get_active_children_count(session, relationship.id)
        lines.append(f"👶 Дети: {children_count}")
        lines.append(f"🏠 Дом: {relationship.house.name if relationship.house else 'нет'}")
        lines.append(f"🚗 Машина: {relationship.car.name if relationship.car else 'нет'}")
        lines.append(f"💰 Семейный бюджет: {relationship.family_budget} 🪙")

    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# /marry — предложение пожениться (с подтверждением партнёра)
# ---------------------------------------------------------------------------


@router.message(Command("marry"))
async def cmd_marry(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    if not await can_marry(session, relationship):
        await message.answer(
            "Пока рано жениться — нужно дойти до стадии «Помолвка» и накопить "
            "достаточно очков близости."
        )
        return

    partner = get_partner(relationship, user.id)
    await message.answer(
        f"💍 {_mention(user)} делает {_mention(partner)} предложение руки и сердца!\n\n"
        f"{_mention(partner)}, что скажешь?",
        reply_markup=build_marry_keyboard(relationship.id),
    )


@router.callback_query(F.data.startswith(MARRY_ACCEPT_PREFIX))
async def on_marry_accept(callback: CallbackQuery, session: AsyncSession):
    relationship_id = int(callback.data.removeprefix(MARRY_ACCEPT_PREFIX))
    relationship = await get_relationship_by_id(session, relationship_id)

    if relationship is None:
        await callback.answer("Эта пара больше не существует.", show_alert=True)
        return

    responder = await _get_user(callback, session)
    if responder.id not in (relationship.user1_id, relationship.user2_id):
        await callback.answer("Это предложение не для тебя.", show_alert=True)
        return

    if not await can_marry(session, relationship):
        await callback.answer("Условия для брака больше не выполняются.", show_alert=True)
        return

    await marry(session, relationship)
    await session.refresh(relationship)

    await callback.message.edit_text(
        f"👰🤵 {_mention(relationship.user1)} и {_mention(relationship.user2)} поженились! Поздравляем!\n\n"
        f"Стадия: {relationship.stage.name}"
    )
    await callback.answer()


@router.callback_query(F.data.startswith(MARRY_REJECT_PREFIX))
async def on_marry_reject(callback: CallbackQuery, session: AsyncSession):
    relationship_id = int(callback.data.removeprefix(MARRY_REJECT_PREFIX))
    relationship = await get_relationship_by_id(session, relationship_id)

    if relationship is None:
        await callback.answer("Эта пара больше не существует.", show_alert=True)
        return

    await callback.message.edit_text("😔 Предложение руки и сердца отклонено. Может, в другой раз.")
    await callback.answer()


# ---------------------------------------------------------------------------
# /breakup — разорвать отношения (расставание или развод)
# ---------------------------------------------------------------------------


@router.message(Command("breakup"))
async def cmd_breakup(message: Message, session: AsyncSession):
    user = await _get_user(message, session)
    relationship = await get_active_relationship(session, user.id)

    if relationship is None:
        await message.answer("У тебя пока нет пары.")
        return

    partner = get_partner(relationship, user.id)
    is_married = relationship.status.value == "married"
    verb = "развестись с" if is_married else "расстаться с"

    warning = ""
    if is_married:
        children_count = await get_active_children_count(session, relationship.id)
        warning_parts = []
        if relationship.house_id or relationship.car_id:
            warning_parts.append("дом/машина останутся недоступны")
        if children_count > 0:
            warning_parts.append("дети останутся в старой семье")
        if relationship.family_budget > 0:
            half = relationship.family_budget // 2
            warning_parts.append(f"семейный бюджет разделится: по {half} 🪙 каждому")
        if warning_parts:
            warning = "\n\n⚠️ " + "; ".join(warning_parts) + "."

    await message.answer(
        f"Ты уверена, что хочешь {verb} {_mention(partner)}?{warning}",
        reply_markup=build_breakup_confirm_keyboard(relationship.id, user.id),
    )


@router.callback_query(F.data.startswith(BREAKUP_CONFIRM_PREFIX))
async def on_breakup_confirm(callback: CallbackQuery, session: AsyncSession):
    payload = callback.data.removeprefix(BREAKUP_CONFIRM_PREFIX)
    relationship_id_str, initiator_id_str = payload.split(":")
    relationship_id, initiator_id = int(relationship_id_str), int(initiator_id_str)

    responder = await _get_user(callback, session)
    if responder.id != initiator_id:
        await callback.answer("Это решение принимает только тот, кто его начал.", show_alert=True)
        return

    relationship = await get_relationship_by_id(session, relationship_id)
    if relationship is None or relationship.status.value not in ("active", "married"):
        await callback.answer("Эти отношения уже неактивны.", show_alert=True)
        return

    result = await end_relationship(session, relationship)

    if result.was_married:
        text = "💔 Пара развелась."
        if result.budget_split_each > 0:
            text += f" Семейный бюджет разделён — по {result.budget_split_each} 🪙 каждому."
    else:
        text = "💔 Пара рассталась."

    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data.startswith(BREAKUP_CANCEL_PREFIX))
async def on_breakup_cancel(callback: CallbackQuery, session: AsyncSession):
    payload = callback.data.removeprefix(BREAKUP_CANCEL_PREFIX)
    _, initiator_id_str = payload.split(":")
    initiator_id = int(initiator_id_str)

    responder = await _get_user(callback, session)
    if responder.id != initiator_id:
        await callback.answer("Это решение принимает только тот, кто его начал.", show_alert=True)
        return

    await callback.message.edit_text("Отменено — вы остаётесь вместе 💕")
    await callback.answer()
