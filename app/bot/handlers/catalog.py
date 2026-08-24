from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    bundles_kb,
    platforms_kb,
    quantity_kb,
    services_kb,
    subcategories_kb,
)
from app.bot.states import OrderFSM
from app.core.link_hints import link_hint_for
from app.core.platforms import detect_platform, platform_title
from app.core.pricing import calculate_order_price
from app.core.speed import format_speed_line
from app.services.catalog import (
    find_bundle_service,
    format_rate,
    get_categories_by_platform,
    get_platforms,
    get_popular_services,
    get_service,
    get_service_purchase_count,
    get_services_by_category,
    get_services_by_platform,
    list_bundles,
    search_services,
    sort_services,
)

router = Router(name="catalog")

SORT_LABELS = {
    "price": "дешевле",
    "speed": "быстрее",
    "popular": "популярнее",
}


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
        "Выберите соцсеть, наборы, популярные или поиск:"
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


@router.callback_query(F.data == "bundles")
async def open_bundles(callback: CallbackQuery) -> None:
    bundles = list_bundles()
    await callback.message.edit_text(
        "<b>Готовые наборы</b>\n"
        "Выберите пакет — подберём подходящую услугу автоматически:",
        reply_markup=bundles_kb(bundles),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bundle:"))
async def open_bundle(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    bundle_id = callback.data.split(":", 1)[1]
    found = await find_bundle_service(session, bundle_id)
    if not found:
        await callback.answer(
            "Сейчас нет подходящей услуги для этого набора.",
            show_alert=True,
        )
        return

    bundle, svc = found
    service = await get_service(session, int(svc["id"]))
    if not service:
        await callback.answer("Услуга недоступна.", show_alert=True)
        return

    qty = int(bundle["qty"])
    total = calculate_order_price(Decimal(service.resale_rate), qty)
    await state.update_data(
        service_id=service.id,
        platform=bundle["platform"],
        bundle_qty=qty,
    )
    await state.set_state(OrderFSM.entering_link)

    bought = await get_service_purchase_count(session, service.id)
    extras = _service_extras(service, bundle["platform"], bought)
    text = (
        f"<b>Набор:</b> {bundle['title']}\n"
        f"<b>Услуга:</b> {service.name}\n\n"
        f"{extras}"
        f"Количество: <b>{qty}</b>\n"
        f"Итого ≈ <b>${total:.2f}</b>\n\n"
        f"{link_hint_for(bundle['platform'])}\n\n"
        "Отправьте ссылку:"
    )
    await callback.message.edit_text(text, disable_web_page_preview=True)
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
    hint = link_hint_for(platform)
    await callback.message.edit_text(
        f"<b>{title}</b> · {total} услуг · {len(categories)} разделов\n\n"
        f"{hint}\n\n"
        "Выберите подраздел или все услуги:",
        reply_markup=subcategories_kb(categories, platform, page=0),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platpage:"))
async def platform_page(callback: CallbackQuery, session: AsyncSession) -> None:
    _, platform, page_s = callback.data.split(":")
    page = int(page_s)
    categories = await get_categories_by_platform(session, platform)
    title = platform_title(platform)
    total = sum(c.get("count", 0) for c in categories)
    hint = link_hint_for(platform)
    await callback.message.edit_text(
        f"<b>{title}</b> · {total} услуг · {len(categories)} разделов\n\n"
        f"{hint}\n\n"
        "Выберите подраздел или все услуги:",
        reply_markup=subcategories_kb(categories, platform, page=page),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platall:"))
async def platform_all_services(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    parts = callback.data.split(":")
    # platall:platform:page  OR  platall:platform:sort:page via sort handler
    platform = parts[1]
    page = int(parts[2]) if len(parts) == 3 else 0
    sort = "price"
    await state.update_data(platform=platform, list_sort=sort)
    await state.set_state(OrderFSM.choosing_service)
    services = await sort_services(
        session, await get_services_by_platform(session, platform), sort
    )
    title = platform_title(platform)
    await callback.message.edit_text(
        f"<b>{title}</b> — все услуги ({len(services)}) · {SORT_LABELS[sort]}:",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"platall:{platform}",
            page=page,
            sort=sort,
            sort_prefix=f"psort:{platform}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("psort:"))
async def platform_sorted(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    # psort:platform:sort:page
    _, platform, sort, page_s = callback.data.split(":")
    page = int(page_s)
    if sort not in SORT_LABELS:
        sort = "price"
    await state.update_data(platform=platform, list_sort=sort)
    await state.set_state(OrderFSM.choosing_service)
    services = await sort_services(
        session, await get_services_by_platform(session, platform), sort
    )
    title = platform_title(platform)
    await callback.message.edit_text(
        f"<b>{title}</b> — все услуги ({len(services)}) · {SORT_LABELS[sort]}:",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"platall:{platform}",
            page=page,
            sort=sort,
            sort_prefix=f"psort:{platform}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def open_category(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    platform = parts[2] if len(parts) > 2 else (await state.get_data()).get("platform", "other")
    sort = "price"
    await state.update_data(category_id=category_id, platform=platform, list_sort=sort)
    await state.set_state(OrderFSM.choosing_service)
    services = await sort_services(
        session, await get_services_by_category(session, category_id), sort
    )
    if not services:
        await callback.answer("В этой категории пока нет услуг.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Услуги ({len(services)}) · {SORT_LABELS[sort]}:",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"catpage:{category_id}:{platform}",
            page=0,
            sort=sort,
            sort_prefix=f"csort:{category_id}:{platform}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catpage:"))
async def category_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    platform = parts[2]
    page = int(parts[3])
    data = await state.get_data()
    sort = data.get("list_sort") or "price"
    services = await sort_services(
        session, await get_services_by_category(session, category_id), sort
    )
    await callback.message.edit_text(
        f"Услуги ({len(services)}) · {SORT_LABELS.get(sort, sort)}:",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"catpage:{category_id}:{platform}",
            page=page,
            sort=sort,
            sort_prefix=f"csort:{category_id}:{platform}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("csort:"))
async def category_sorted(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    # csort:category_id:platform:sort:page
    _, cat_s, platform, sort, page_s = callback.data.split(":")
    category_id = int(cat_s)
    page = int(page_s)
    if sort not in SORT_LABELS:
        sort = "price"
    await state.update_data(category_id=category_id, platform=platform, list_sort=sort)
    await state.set_state(OrderFSM.choosing_service)
    services = await sort_services(
        session, await get_services_by_category(session, category_id), sort
    )
    await callback.message.edit_text(
        f"Услуги ({len(services)}) · {SORT_LABELS[sort]}:",
        reply_markup=services_kb(
            services,
            back_callback=f"plat:{platform}",
            page_prefix=f"catpage:{category_id}:{platform}",
            page=page,
            sort=sort,
            sort_prefix=f"csort:{category_id}:{platform}",
        ),
    )
    await callback.answer()


def _service_extras(service, platform: str | None, bought: int) -> str:
    lines: list[str] = []
    speed = format_speed_line(
        service.name, int(getattr(service, "speed_rank", 9) or 9)
    )
    if speed:
        lines.append(speed)
    flags = []
    if getattr(service, "refill", False):
        flags.append("♻️ Refill / гарантия")
    if getattr(service, "cancel_allowed", False):
        flags.append("↩️ Отмена возможна")
    if getattr(service, "dripfeed", False):
        flags.append("💧 Drip-feed")
    if flags:
        lines.append(" · ".join(flags))
    if bought:
        lines.append(f"Уже купили: <b>{bought}</b> раз")
    lines.append("")
    return ("\n".join(lines) + "\n") if lines else ""


@router.callback_query(F.data.startswith("svc:"))
async def open_service(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    service_id = int(callback.data.split(":")[1])
    service = await get_service(session, service_id)
    if not service:
        await callback.answer("Услуга недоступна.", show_alert=True)
        return

    data = await state.get_data()
    platform = data.get("platform")
    if not platform and service.category:
        platform, _ = detect_platform(service.category.name, service.name)

    await state.update_data(service_id=service.id, platform=platform)
    await state.set_state(OrderFSM.entering_link)

    bought = await get_service_purchase_count(session, service.id)
    desc = service.description or "—"
    category_name = service.category.name if service.category else "—"
    extras = _service_extras(service, platform, bought)
    text = (
        f"<b>{service.name}</b>\n"
        f"Категория: {category_name}\n\n"
        f"{desc}\n\n"
        f"{extras}"
        f"💰 Цена: <b>{format_rate(service.resale_rate)}</b> / 1000 шт.\n"
        f"📊 Min: <b>{service.min_order}</b> · Max: <b>{service.max_order}</b>\n\n"
        f"{link_hint_for(platform)}\n\n"
        "Отправьте ссылку:"
    )
    await callback.message.edit_text(text, disable_web_page_preview=True)
    await callback.answer()
