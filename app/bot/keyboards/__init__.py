from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🛒 Каталог"))
    builder.row(
        KeyboardButton(text="💰 Баланс"),
        KeyboardButton(text="📦 Мои заказы"),
    )
    builder.row(
        KeyboardButton(text="🎟 Промокод"),
        KeyboardButton(text="👥 Рефералы"),
    )
    builder.row(
        KeyboardButton(text="ℹ️ Помощь"),
        KeyboardButton(text="💬 Поддержка"),
    )
    return builder.as_markup(resize_keyboard=True)


def support_kb(username: str) -> InlineKeyboardMarkup:
    clean = username.lstrip("@")
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать администратору", url=f"https://t.me/{clean}")
    return builder.as_markup()


def help_kb(username: str, *, offer_url: str, privacy_url: str) -> InlineKeyboardMarkup:
    clean = username.lstrip("@")
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Публичная оферта", url=offer_url)
    builder.button(text="🔒 Политика конфиденциальности", url=privacy_url)
    builder.button(text="Написать администратору", url=f"https://t.me/{clean}")
    builder.adjust(1)
    return builder.as_markup()


def platforms_kb(platforms: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Популярные", callback_data="popular:0")
    builder.button(text="📦 Наборы", callback_data="bundles")
    builder.button(text="🔎 Поиск", callback_data="search")
    for p in platforms:
        builder.button(
            text=f"{p['name']} ({p['count']})",
            callback_data=f"plat:{p['slug']}",
        )
    builder.adjust(2, 1, 2)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="menu:home"))
    return builder.as_markup()


def subcategories_kb(
    categories: list[dict],
    platform: str,
    page: int = 0,
    per_page: int = 10,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(categories)
    start = page * per_page
    chunk = categories[start : start + per_page]

    for cat in chunk:
        name = cat["name"]
        # Drop redundant platform prefix for shorter buttons
        short = name
        for sep in (" | ", " — ", " - ", " – "):
            if sep in name:
                short = name.split(sep, 1)[-1].strip()
                break
        count = cat.get("count", 0)
        label = f"{short[:42]} ({count})" if count else short[:48]
        builder.button(text=label, callback_data=f"cat:{cat['id']}:{platform}")
    builder.adjust(1)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="‹", callback_data=f"platpage:{platform}:{page - 1}")
        )
    if start + per_page < total:
        nav.append(
            InlineKeyboardButton(text="›", callback_data=f"platpage:{platform}:{page + 1}")
        )
    if nav:
        pages = max(1, (total + per_page - 1) // per_page)
        nav.insert(
            1 if page > 0 else 0,
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"),
        )
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text="📋 Все услуги раздела", callback_data=f"platall:{platform}:0")
    )
    builder.row(InlineKeyboardButton(text="« К соцсетям", callback_data="catalog"))
    return builder.as_markup()


def services_kb(
    services: list[dict],
    *,
    back_callback: str,
    page_prefix: str,
    page: int = 0,
    per_page: int = 8,
    sort: str | None = None,
    sort_prefix: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(services)
    start = page * per_page
    chunk = services[start : start + per_page]

    for svc in chunk:
        rate = svc.get("resale_rate", "0")
        name = (svc.get("name") or "")[:36]
        builder.button(
            text=f"{name} · ${rate}/1k",
            callback_data=f"svc:{svc['id']}",
        )
    builder.adjust(1)

    page_cb_prefix = f"{sort_prefix}:{sort}" if sort_prefix and sort else page_prefix
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="‹", callback_data=f"{page_cb_prefix}:{page - 1}")
        )
    if start + per_page < total:
        nav.append(
            InlineKeyboardButton(text="›", callback_data=f"{page_cb_prefix}:{page + 1}")
        )
    if nav:
        pages = max(1, (total + per_page - 1) // per_page)
        mid = InlineKeyboardButton(
            text=f"{page + 1}/{pages} · {total} шт", callback_data="noop"
        )
        if page > 0 and start + per_page < total:
            builder.row(nav[0], mid, nav[1])
        elif page > 0:
            builder.row(nav[0], mid)
        else:
            builder.row(mid, nav[0])

    if sort_prefix:
        price_l = "💰 Дешевле ✓" if sort == "price" else "💰 Дешевле"
        speed_l = "⚡ Быстрее ✓" if sort == "speed" else "⚡ Быстрее"
        pop_l = "🔥 Топ ✓" if sort == "popular" else "🔥 Топ"
        builder.row(
            InlineKeyboardButton(text=price_l, callback_data=f"{sort_prefix}:price:0"),
            InlineKeyboardButton(text=speed_l, callback_data=f"{sort_prefix}:speed:0"),
            InlineKeyboardButton(text=pop_l, callback_data=f"{sort_prefix}:popular:0"),
        )

    builder.row(InlineKeyboardButton(text="« Назад", callback_data=back_callback))
    return builder.as_markup()


def bundles_kb(bundles: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bundles:
        builder.button(text=b["title"], callback_data=f"bundle:{b['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="« К каталогу", callback_data="catalog"))
    return builder.as_markup()


def confirm_order_kb(
    *,
    offer_url: str,
    privacy_url: str,
    has_promo: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_promo:
        builder.button(text="🎟 Промокод применён", callback_data="promo:noop")
    else:
        builder.button(text="🎟 Ввести промокод", callback_data="promo:enter")
    builder.button(text="✅ Подтвердить", callback_data="order:confirm")
    builder.button(text="❌ Отмена", callback_data="order:cancel")
    builder.adjust(1, 2)
    builder.row(
        InlineKeyboardButton(text="📄 Оферта", url=offer_url),
        InlineKeyboardButton(text="🔒 Конфиденциальность", url=privacy_url),
    )
    return builder.as_markup()


def quantity_kb(min_order: int, max_order: int) -> InlineKeyboardMarkup:
    """Smart package buttons within service min/max."""
    candidates = [min_order, 1000, 2500, 5000, 10000, 25000, 50000, max_order]
    seen: set[int] = set()
    values: list[int] = []
    for raw in candidates:
        value = max(min_order, min(max_order, int(raw)))
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    values.sort()

    builder = InlineKeyboardBuilder()
    for value in values[:8]:
        builder.button(text=f"{value:,}".replace(",", " "), callback_data=f"qty:{value}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="✏️ Своё число", callback_data="qty:custom"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="order:cancel"))
    return builder.as_markup()


def orders_list_kb(orders: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders[:10]:
        if order.status in {"awaiting_payment", "failed", "canceled"}:
            continue
        builder.button(
            text=f"Повторить #{order.id}",
            callback_data=f"reorder:{order.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить", callback_data="broadcast:send")
    builder.button(text="❌ Отмена", callback_data="broadcast:cancel")
    builder.adjust(2)
    return builder.as_markup()


def payment_methods_kb(
    *,
    balance_ok: bool,
    yookassa: bool,
    stars: bool,
    crypto: bool,
    has_promo: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_promo:
        builder.button(text="🎟 Промокод применён", callback_data="promo:noop")
    else:
        builder.button(text="🎟 Ввести промокод", callback_data="promo:enter")
    if balance_ok:
        builder.button(text="💳 С баланса", callback_data="pay:balance")
    if yookassa:
        builder.button(text="🏦 ЮKassa", callback_data="pay:yookassa")
    if stars:
        builder.button(text="⭐ Telegram Stars", callback_data="pay:stars")
    if crypto:
        builder.button(text="🪙 Crypto Bot", callback_data="pay:crypto")
    builder.button(text="❌ Отмена", callback_data="order:cancel")
    builder.adjust(1)
    return builder.as_markup()


def admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="adm:stats")
    builder.button(text="💰 Баланс панели", callback_data="adm:panel_bal")
    builder.button(text="🔄 Синхронизация", callback_data="adm:sync")
    builder.button(text="🎟 Промокоды", callback_data="adm:promos")
    builder.button(text="💵 Выдать баланс", callback_data="adm:give")
    builder.button(text="💸 Снять баланс", callback_data="adm:take")
    builder.button(text="🔎 Найти юзера", callback_data="adm:find")
    builder.button(text="🚫 Бан / разбан", callback_data="adm:ban")
    builder.button(text="📣 Рассылка", callback_data="adm:broadcast")
    builder.adjust(2)
    return builder.as_markup()


def admin_promos_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать", callback_data="adm:promo_create")
    builder.button(text="📋 Список", callback_data="adm:promo_list")
    builder.button(text="« Назад", callback_data="adm:home")
    builder.adjust(2, 1)
    return builder.as_markup()


def admin_promo_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Процент %", callback_data="adm:promo_type:percent")
    builder.button(text="Скидка $", callback_data="adm:promo_type:fixed")
    builder.button(text="Баланс +$", callback_data="adm:promo_type:balance")
    builder.button(text="« Отмена", callback_data="adm:promos")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="« В админку", callback_data="adm:home")
    return builder.as_markup()


def topup_methods_kb(*, yookassa: bool, stars: bool, crypto: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if yookassa:
        builder.button(text="🏦 ЮKassa", callback_data="topup:yookassa")
    if stars:
        builder.button(text="⭐ Telegram Stars", callback_data="topup:stars")
    if crypto:
        builder.button(text="🪙 Crypto Bot", callback_data="topup:crypto")
    builder.button(text="« Назад", callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


def topup_amounts_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for amount in (5, 10, 25, 50, 100):
        builder.button(text=f"${amount}", callback_data=f"topup_amount:{amount}")
    builder.button(text="Другая сумма", callback_data="topup_amount:custom")
    builder.button(text="« Назад", callback_data="menu:home")
    builder.adjust(3, 2, 1, 1)
    return builder.as_markup()
