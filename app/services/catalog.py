from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.bundles import BUNDLES, get_bundle
from app.core.platforms import detect_platform
from app.core.speed import detect_speed
from app.db.models import Category, Service
from app.db.redis import CacheKeys, cache_get, cache_set


def _service_dict(s: Service) -> dict:
    rank = int(getattr(s, "speed_rank", 9) or 9)
    if rank >= 9:
        rank, _ = detect_speed(s.name)
    return {
        "id": s.id,
        "panel_service_id": s.panel_service_id,
        "category_id": s.category_id,
        "name": s.name,
        "type": s.type,
        "panel_rate": str(s.panel_rate),
        "resale_rate": str(s.resale_rate),
        "min_order": s.min_order,
        "max_order": s.max_order,
        "description": s.description,
        "refill": bool(getattr(s, "refill", False)),
        "cancel_allowed": bool(getattr(s, "cancel_allowed", False)),
        "dripfeed": bool(getattr(s, "dripfeed", False)),
        "speed_rank": rank,
    }


async def get_platforms(session: AsyncSession) -> list[dict]:
    """Top-level social networks present in the catalog."""
    cached = await cache_get(CacheKeys.PLATFORMS)
    if isinstance(cached, list) and cached:
        return cached

    categories = await get_categories(session)
    services = await _all_active_services(session)

    counts: dict[str, int] = {}
    for svc in services:
        cat_name = ""
        for c in categories:
            if c["id"] == svc.get("category_id"):
                cat_name = c["name"]
                break
        slug, _ = detect_platform(cat_name, svc.get("name") or "")
        counts[slug] = counts.get(slug, 0) + 1

    platforms = []
    from app.core.platforms import OTHER, PLATFORMS

    for slug, title, _ in PLATFORMS:
        if counts.get(slug):
            platforms.append({"slug": slug, "name": title, "count": counts[slug]})
    if counts.get(OTHER[0]):
        platforms.append(
            {"slug": OTHER[0], "name": OTHER[1], "count": counts[OTHER[0]]}
        )

    await cache_set(CacheKeys.PLATFORMS, platforms)
    return platforms


async def get_categories(session: AsyncSession) -> list[dict]:
    cached = await cache_get(CacheKeys.CATEGORIES)
    if isinstance(cached, list) and cached:
        return cached

    result = await session.execute(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_order, Category.name)
    )
    categories = result.scalars().all()
    return [{"id": c.id, "name": c.name, "icon": c.icon or "#"} for c in categories]


async def get_categories_by_platform(session: AsyncSession, platform: str) -> list[dict]:
    key = CacheKeys.CATEGORIES_BY_PLATFORM.format(platform=platform)
    cached = await cache_get(key)
    if isinstance(cached, list):
        return cached

    categories = await get_categories(session)
    services = await _all_active_services(session)
    svc_count_by_cat: dict[int, int] = {}
    for svc in services:
        cid = svc.get("category_id")
        if cid is None:
            continue
        cat_name = next((c["name"] for c in categories if c["id"] == cid), "")
        slug, _ = detect_platform(cat_name, svc.get("name") or "")
        if slug != platform:
            continue
        svc_count_by_cat[cid] = svc_count_by_cat.get(cid, 0) + 1

    result = []
    for cat in categories:
        count = svc_count_by_cat.get(cat["id"], 0)
        if count:
            result.append({**cat, "count": count})

    await cache_set(key, result)
    return result


async def get_services_by_category(session: AsyncSession, category_id: int) -> list[dict]:
    key = CacheKeys.SERVICES_BY_CATEGORY.format(category_id=category_id)
    cached = await cache_get(key)
    if isinstance(cached, list) and cached and "speed_rank" in cached[0]:
        return cached

    result = await session.execute(
        select(Service)
        .where(Service.category_id == category_id, Service.is_active.is_(True))
        .order_by(Service.name)
    )
    services = [_service_dict(s) for s in result.scalars().all()]
    await cache_set(key, services)
    return services


async def get_services_by_platform(
    session: AsyncSession,
    platform: str,
    *,
    search: str | None = None,
) -> list[dict]:
    """All services for a platform (across panel subcategories)."""
    key = CacheKeys.SERVICES_BY_PLATFORM.format(platform=platform)
    cached = await cache_get(key)
    if isinstance(cached, list) and not search and cached and "speed_rank" in cached[0]:
        return cached

    categories = await get_categories(session)
    cat_by_id = {c["id"]: c for c in categories}
    services = await _all_active_services(session)

    result = []
    for svc in services:
        cat = cat_by_id.get(svc.get("category_id") or -1, {})
        slug, _ = detect_platform(cat.get("name") or "", svc.get("name") or "")
        if slug != platform:
            continue
        item = {**svc, "category_name": cat.get("name") or ""}
        if search:
            q = search.lower()
            hay = f"{item['name']} {item.get('category_name', '')}".lower()
            if q not in hay:
                continue
        result.append(item)

    result.sort(key=lambda x: (x.get("category_name") or "", x.get("name") or ""))
    if not search:
        await cache_set(key, result)
    return result


async def get_service(session: AsyncSession, service_id: int) -> Service | None:
    result = await session.execute(
        select(Service)
        .options(selectinload(Service.category))
        .where(Service.id == service_id, Service.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_service_purchase_count(session: AsyncSession, service_id: int) -> int:
    from app.db.models import Order, OrderStatus

    count = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.service_id == service_id,
            Order.status.in_(
                [
                    OrderStatus.PENDING,
                    OrderStatus.IN_PROGRESS,
                    OrderStatus.COMPLETED,
                    OrderStatus.PARTIAL,
                ]
            ),
        )
    )
    return int(count or 0)


async def get_purchase_counts(session: AsyncSession) -> dict[int, int]:
    from app.db.models import Order, OrderStatus

    rows = (
        await session.execute(
            select(Order.service_id, func.count(Order.id))
            .where(
                Order.status.in_(
                    [
                        OrderStatus.PENDING,
                        OrderStatus.IN_PROGRESS,
                        OrderStatus.COMPLETED,
                        OrderStatus.PARTIAL,
                    ]
                )
            )
            .group_by(Order.service_id)
        )
    ).all()
    return {int(sid): int(cnt) for sid, cnt in rows}


async def sort_services(
    session: AsyncSession,
    services: list[dict],
    mode: str,
) -> list[dict]:
    items = list(services)
    if mode == "price":
        items.sort(key=lambda s: Decimal(s.get("resale_rate") or "999"))
    elif mode == "speed":
        items.sort(
            key=lambda s: (
                int(s.get("speed_rank") if s.get("speed_rank") is not None else 9),
                Decimal(s.get("resale_rate") or "999"),
            )
        )
    elif mode == "popular":
        counts = await get_purchase_counts(session)
        items.sort(
            key=lambda s: (
                -counts.get(int(s["id"]), 0),
                Decimal(s.get("resale_rate") or "999"),
            )
        )
    else:
        items.sort(key=lambda s: s.get("name") or "")
    return items


async def get_popular_services(session: AsyncSession, limit: int = 10) -> list[dict]:
    from app.db.models import Order, OrderStatus

    rows = (
        await session.execute(
            select(Order.service_id, func.count(Order.id).label("cnt"))
            .where(
                Order.status.in_(
                    [
                        OrderStatus.PENDING,
                        OrderStatus.IN_PROGRESS,
                        OrderStatus.COMPLETED,
                        OrderStatus.PARTIAL,
                    ]
                )
            )
            .group_by(Order.service_id)
            .order_by(func.count(Order.id).desc())
            .limit(limit)
        )
    ).all()

    if not rows:
        services = await _all_active_services(session)
        services.sort(key=lambda s: Decimal(s.get("resale_rate") or "999"))
        return services[:limit]

    by_id = {s["id"]: s for s in await _all_active_services(session)}
    result = []
    for service_id, cnt in rows:
        svc = by_id.get(service_id)
        if not svc:
            continue
        result.append({**svc, "orders_count": int(cnt)})
    return result


async def search_services(session: AsyncSession, query: str, limit: int = 40) -> list[dict]:
    q = " ".join((query or "").lower().split())
    if len(q) < 2:
        return []
    categories = await get_categories(session)
    cat_by_id = {c["id"]: c for c in categories}
    tokens = q.split()
    found = []
    for svc in await _all_active_services(session):
        cat = cat_by_id.get(svc.get("category_id") or -1, {})
        hay = f"{svc.get('name', '')} {cat.get('name', '')}".lower()
        if all(token in hay for token in tokens):
            found.append({**svc, "category_name": cat.get("name") or ""})
        if len(found) >= limit:
            break
    return found


async def find_bundle_service(
    session: AsyncSession, bundle_id: str
) -> tuple[dict, dict] | None:
    """Return (bundle, best matching service dict) or None."""
    bundle = get_bundle(bundle_id)
    if not bundle:
        return None
    qty = int(bundle["qty"])
    keywords = tuple(
        k.lower()
        for k in (bundle.get("keywords_any") or bundle.get("keywords") or ())
    )
    exclude = tuple(k.lower() for k in bundle.get("exclude") or ())
    platform = bundle["platform"]

    candidates = []
    for svc in await get_services_by_platform(session, platform):
        name = (svc.get("name") or "").lower()
        if keywords and not any(k in name for k in keywords):
            continue
        if any(x in name for x in exclude):
            continue
        if int(svc["min_order"]) > qty or int(svc["max_order"]) < qty:
            continue
        candidates.append(svc)

    if not candidates:
        return None

    candidates.sort(
        key=lambda s: (
            int(s.get("speed_rank") if s.get("speed_rank") is not None else 9),
            Decimal(s.get("resale_rate") or "999"),
        )
    )
    return bundle, candidates[0]


def list_bundles() -> list[dict]:
    return list(BUNDLES)


async def _all_active_services(session: AsyncSession) -> list[dict]:
    cached = await cache_get(CacheKeys.SERVICES_ALL)
    if isinstance(cached, list) and cached and "speed_rank" in cached[0]:
        return cached

    result = await session.execute(select(Service).where(Service.is_active.is_(True)))
    payload = [_service_dict(s) for s in result.scalars().all()]
    await cache_set(CacheKeys.SERVICES_ALL, payload)
    return payload


def format_rate(rate: Decimal | str) -> str:
    value = Decimal(str(rate))
    return f"${value:.2f}"
