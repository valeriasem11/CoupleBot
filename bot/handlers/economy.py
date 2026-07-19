"""
Хендлеры экономики: выбор работы, проверка баланса, "поход на работу".
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import (
    get_all_jobs,
    get_job_by_id,
    get_or_create_user,
    set_user_job,
)
from bot.keyboards.economy import JOB_CALLBACK_PREFIX, build_jobs_keyboard
from bot.services.economy_service import (
    WorkOutcome,
    LoanError,
    MAX_LOAN_AMOUNT,
    LOAN_INTEREST_RATE,
    format_timedelta,
    get_work_cooldown_remaining,
    perform_work,
    repay_loan,
    take_loan,
)

router = Router(name="economy")


async def _get_user(message_or_callback, session: AsyncSession):
    """Небольшой помощник, чтобы не дублировать get_or_create_user в каждом хендлере."""
    from_user = message_or_callback.from_user
    chat = getattr(message_or_callback, "message", message_or_callback).chat
    return await get_or_create_user(
        session=session,
        telegram_id=from_user.id,
        username=from_user.username,
        first_name=from_user.first_name,
        chat_id=chat.id,
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    user = await _get_user(message, session)

    job_line = f"Текущая работа: {user.job.name}" if user.job else "Работа не выбрана — набери /job, чтобы выбрать."
    loan_line = f"\n💳 Долг по кредиту: {user.loan_amount} 🪙" if user.loan_amount > 0 else ""

    await message.answer(
        f"💰 Баланс: {user.balance} 🪙\n"
        f"{job_line}"
        f"{loan_line}"
    )


@router.message(Command("job"))
async def cmd_job(message: Message, session: AsyncSession):
    jobs = await get_all_jobs(session)

    if not jobs:
        await message.answer(
            "Список работ пока пуст. Убедись, что справочники заполнены "
            "командой `python -m bot.database.seed`."
        )
        return

    await message.answer(
        "Выбери работу (это чисто по вкусу — на заработок не влияет):",
        reply_markup=build_jobs_keyboard(jobs),
    )


@router.callback_query(F.data.startswith(JOB_CALLBACK_PREFIX))
async def on_job_selected(callback: CallbackQuery, session: AsyncSession):
    job_id = int(callback.data.removeprefix(JOB_CALLBACK_PREFIX))
    job = await get_job_by_id(session, job_id)

    if job is None:
        await callback.answer("Эта работа больше не доступна.", show_alert=True)
        return

    user = await _get_user(callback, session)
    await set_user_job(session, user, job)

    await callback.message.edit_text(f"Готово! Теперь твоя работа: {job.name}\n\nМожешь идти работать: /work")
    await callback.answer()


@router.message(Command("work"))
async def cmd_work(message: Message, session: AsyncSession):
    user = await _get_user(message, session)

    if user.job is None:
        await message.answer("Сначала выбери работу командой /job.")
        return

    job = user.job

    remaining = get_work_cooldown_remaining(user, job)
    if remaining is not None:
        await message.answer(
            f"Ты уже отработала смену недавно. "
            f"Приходи через {format_timedelta(remaining)}."
        )
        return

    result = await perform_work(session, user, job)

    if result.outcome == WorkOutcome.BONUS:
        text = (
            f"🎉 Тебе выдали премию!\n"
            f"База: {result.base_salary} + премия {result.bonus_amount} = "
            f"{result.total} 🪙"
        )
    elif result.outcome == WorkOutcome.TIP:
        text = (
            f"☕ Тебе оставили чаевые!\n"
            f"База: {result.base_salary} + чаевые {result.bonus_amount} = "
            f"{result.total} 🪙"
        )
    else:
        text = f"Ты отработала смену и заработала {result.total} 🪙."

    await message.answer(text)


def _parse_amount(command: CommandObject) -> int | None:
    if command.args is None:
        return None
    try:
        amount = int(command.args.strip())
    except ValueError:
        return None
    if amount <= 0:
        return None
    return amount


@router.message(Command("loan"))
async def cmd_loan(message: Message, command: CommandObject, session: AsyncSession):
    amount = _parse_amount(command)
    if amount is None:
        await message.answer(
            f"Укажи сумму кредита, например: /loan 5000\n"
            f"Максимум — {MAX_LOAN_AMOUNT} 🪙, переплата — {int(LOAN_INTEREST_RATE * 100)}%."
        )
        return

    user = await _get_user(message, session)

    try:
        debt = await take_loan(session, user, amount)
    except LoanError as e:
        await message.answer(str(e))
        return

    await message.answer(
        f"✅ Кредит оформлен: +{amount} 🪙 на баланс.\n"
        f"К возврату (с переплатой {int(LOAN_INTEREST_RATE * 100)}%): {debt} 🪙\n\n"
        f"Погашай через /repay (сумма)."
    )


@router.message(Command("repay"))
async def cmd_repay(message: Message, command: CommandObject, session: AsyncSession):
    amount = _parse_amount(command)
    if amount is None:
        await message.answer("Укажи сумму погашения, например: /repay 1000")
        return

    user = await _get_user(message, session)

    try:
        actual_repay = await repay_loan(session, user, amount)
    except LoanError as e:
        await message.answer(str(e))
        return

    if user.loan_amount == 0:
        await message.answer(f"✅ Погашено {actual_repay} 🪙. Кредит полностью закрыт! 🎉")
    else:
        await message.answer(
            f"✅ Погашено {actual_repay} 🪙.\n"
            f"Остаток долга: {user.loan_amount} 🪙"
        )
