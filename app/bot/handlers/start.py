from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import help_kb, main_menu_kb, support_kb
from app.core.config import get_settings
from app.db.models import User
from app.services.referrals import attach_referrer, parse_referrer_tg_id

router = Router(name="start")

WELCOME_IMAGE = Path(__file__).resolve().parents[3] / "assets" / "welcome.png"

WELCOME_CAPTION = (
    "Привет, <b>{name}</b>!\n\n"
    "🚀 <b>SMM-услуги</b> для роста в соцсетях\n"
    "Подписчики · Просмотры · Лайки и другие услуги\n\n"
    "Баланс: <b>${balance:.2f}</b>{extra}\n\n"
    "Выберите действие в меню ниже.\n"
    "Документы — в «ℹ️ Помощь»."
)


def _support_username() -> str:
    return get_settings().support_username.lstrip("@")


def help_text() -> str:
    settings = get_settings()
    support = _support_username()
    return (
        "🤖 <b>SMM-услуги</b>\n\n"
        "Продвижение в соцсетях: подписчики, просмотры, лайки и другие услуги.\n\n"
        "<b>Как заказать:</b>\n"
        "1. Каталог → соцсеть → услуга\n"
        "2. Укажите ссылку и количество\n"
        "3. Оплатите\n"
        "4. Заказ запускается автоматически\n\n"
        "Статус — в «Мои заказы». Приглашайте друзей в «Рефералы» и получайте бонус.\n"
        "Промокод — кнопка «🎟 Промокод» в меню (или при заказе).\n\n"
        f"<a href=\"{settings.offer_url}\">Публичная оферта</a> · "
        f"<a href=\"{settings.privacy_url}\">Политика конфиденциальности</a>\n\n"
        f"Поддержка: @{support}"
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    db_user: User,
    state: FSMContext,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    await state.clear()
    ref_tg = parse_referrer_tg_id(command.args)
    attached = await attach_referrer(session, db_user, ref_tg)

    extra = ""
    if attached:
        extra = "\nВы пришли по приглашению — добро пожаловать!"

    caption = WELCOME_CAPTION.format(
        name=db_user.first_name or "друг",
        balance=db_user.balance,
        extra=extra,
    )
    markup = main_menu_kb()

    if WELCOME_IMAGE.exists():
        await message.answer_photo(
            photo=FSInputFile(WELCOME_IMAGE),
            caption=caption,
            reply_markup=markup,
        )
    else:
        await message.answer(caption, reply_markup=markup)


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message) -> None:
    settings = get_settings()
    support = _support_username()
    await message.answer(
        help_text(),
        reply_markup=help_kb(
            support,
            offer_url=settings.offer_url,
            privacy_url=settings.privacy_url,
        ),
        disable_web_page_preview=True,
    )


@router.message(Command("support"))
@router.message(F.text == "💬 Поддержка")
async def cmd_support(message: Message) -> None:
    support = _support_username()
    await message.answer(
        f"По вопросам заказов и оплаты напишите администратору:\n"
        f"@{support}",
        reply_markup=support_kb(support),
    )


@router.message(Command("stop_mail"))
async def stop_mail(message: Message, session: AsyncSession, db_user: User) -> None:
    db_user.broadcast_opt_out = True
    await session.flush()
    await message.answer("Вы отписались от рассылок. Вернуть: /start_mail")


@router.message(Command("start_mail"))
async def start_mail(message: Message, session: AsyncSession, db_user: User) -> None:
    db_user.broadcast_opt_out = False
    await session.flush()
    await message.answer("Подписка на рассылки включена.")


@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        f"Главное меню\nБаланс: <b>${db_user.balance:.2f}</b>",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()
