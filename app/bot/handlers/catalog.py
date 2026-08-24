from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import platforms_kb, quantity_kb, services_kb, subcategories_kb
from app.bot.states import OrderFSM
from app.core.platforms import platform_title
from app.services.catalog import (
    format_rate,
    get_categories_by_platform,
    get_platforms,
    get_popular_services,
    get_service,
    get_service_purchase_count,
    get_services_by_category,
    get_services_by_platform,
    search_services,
)

router = Router(name="catalog")


@router.message(F.text == "🛒 Каталог")
@router.callback_query(F.data == "catalog")
async def open_catalog(
    event: Message | CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.set_state(OrderFSM.choosing_platform)
    platforms = await get_platforms(session)
    total = sum(p["count"] for p in platforms)
    text = (
        f"Каталог: <b>{total}</b> услуг\n"
        "Выберите соцсеть, популярные или поиск:"
    )
    kb = platforms_kb(platforms)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb)
    else:
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("popular:"))
async def open_popular(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    await state.set_state(OrderFSM.choosing_service)
    services = await get_popular_services(session, limit=20)
    await callback.message.edit_text(
        f"🔥 Популярные услуги ({len(services)}):",
        reply_markup=services_kb(
            services,
            back_callback="catalog",
            page_prefix="popular",
            page=page,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "search")
async def start_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderFSM.searching)
    await callback.message.edit_text(
        "🔎 Введите запрос для поиска услуги\n"
        "Например: <code>telegram views</code> или <code>instagram likes</code>"
    )
    await callback.answer()


@router.message(OrderFSM.searching)
async def process_search(message: Message, session: AsyncSession, state: FSMContext) -> None:
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer("Введите минимум 2 символа.")
        return
    services = await search_services(session, query, limit=40)
    if not services:
        await message.answer("Ничего не найдено. Попробуйте другой запрос.")
        return
    await state.set_state(OrderFSM.choosing_service)
    await state.update_data(search_results=services)
    await message.answer(
        f"Найдено: <b>{len(services)}</b> по запросу «{query}»",
        reply_markup=services_kb(
            services,
            back_callback="catalog",
            page_prefix="searchpage",
            page=0,
        ),
    )


@router.callback_query(F.data.startswith("searchpage:"))
async def search_page(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    services = data.get("search_results") or []
    if not services:
        await callback.answer("Запустите поиск заново", show_alert=True)
        return
    await callback.message.edit_text(
        f"Результаты поиска ({len(services)}):",
        reply_markup=services_kb(
            services,
            back_callback="catalog",
            page_prefix="searchpage",
            page=page,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plat:"))
async def open_platform(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    platform = callback.data.split(":", 1)[1]
    await state.update_data(platform=platform)
    await state.set_state(OrderFSM.choosing_category)
    categories = await get_categories_by_platform(session, platform)
    title = platform_title(platform)
    if not categories:
        await callback.answer("В этом разделе пока нет услуг.", show_alert=True)
        return
    total = sum(c.get("count", 0) for c in categories)
    await callback.message.edit_text(
        f"<b>{title}</b> · {total} услуг · {len(categories)} разделов\n"
        "Выберите подраздел или все услуги:",
        reply_markup=subcategories_kb(categories, platform, page=0),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platpage:"))
async def platform_page(callback: CallbackQuery, session: AsyncSession) -> None:
    _, platform, page_s = callback.data.split(":")
    page = int(page_s)
    categories = await get_categories_by_platform(session, platform)
    title = platform_title(platform)
    total = sum(c.get("count", 0) for c in categories)
    await callback.message.edit_text(
        f"<b>{title}</b> · {total} услуг · {len(categories)} разделов\n"
        "Выберите подраздел или все услуги:",
        reply_markup=subcategories_kb(categories, platform, page=page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platall:"))
async def platform_all_services(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    _, platform, page_s = callback.data.split(":")
    page = int(page_s)
    await state.update_data(platform=platform)
    await state.set_state(OrderFSM.choosing_service)
    services = await get_services_by_platform(session, platform)
    title = platform_title(platform)
    await callback.message.edit_text(
        f"<b>{title}</b> — все услуги ({len(services)}):",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"platall:{platform}",
            page=page,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def open_category(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    platform = parts[2] if len(parts) > 2 else (await state.get_data()).get("platform", "other")
    await state.update_data(category_id=category_id, platform=platform)
    await state.set_state(OrderFSM.choosing_service)
    services = await get_services_by_category(session, category_id)
    if not services:
        await callback.answer("В этой категории пока нет услуг.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Услуги ({len(services)}):",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"catpage:{category_id}:{platform}",
            page=0,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catpage:"))
async def category_page(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    platform = parts[2]
    page = int(parts[3])
    services = await get_services_by_category(session, category_id)
    await callback.message.edit_text(
        f"Услуги ({len(services)}):",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"catpage:{category_id}:{platform}",
            page=page,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("svc:"))
async def open_service(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    service_id = int(callback.data.split(":")[1])
    service = await get_service(session, service_id)
    if not service:
        await callback.answer("Услуга недоступна.", show_alert=True)
        return

    await state.update_data(service_id=service.id)
    await state.set_state(OrderFSM.entering_link)

    bought = await get_service_purchase_count(session, service.id)
    desc = service.description or "—"
    category_name = service.category.name if service.category else "—"
    social_proof = f"Уже купили: <b>{bought}</b> раз\n" if bought else ""
    text = (
        f"<b>{service.name}</b>\n"
        f"Категория: {category_name}\n\n"
        f"{desc}\n\n"
        f"{social_proof}"
        f"💰 Цена: <b>{format_rate(service.resale_rate)}</b> / 1000 шт.\n"
        f"📊 Min: <b>{service.min_order}</b> · Max: <b>{service.max_order}</b>\n\n"
        "Отправьте ссылку на пост / профиль / канал:"
    )
    await callback.message.edit_text(text)
    await callback.answer()
