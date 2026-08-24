from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pricing import calculate_resale_price, detect_service_type
from app.core.speed import detect_speed
from app.db.models import Category, Service
from app.db.redis import CacheKeys, cache_delete, cache_set
from app.panel import PanelClient

# Common category icons
CATEGORY_ICONS: dict[str, str] = {
    "instagram": "IG",
    "youtube": "YT",
    "tiktok": "TT",
    "telegram": "TG",
    "vk": "VK",
    "twitter": "X",
    "x": "X",
    "twitch": "TW",
    "facebook": "FB",
    "spotify": "SP",
    "discord": "DC",
    "soundcloud": "SC",
    "linkedin": "IN",
    "threads": "TH",
    "snapchat": "SN",
    "pinterest": "PIN",
}


def _category_icon(name: str) -> str:
    lowered = name.lower()
    for key, icon in CATEGORY_ICONS.items():
        if key in lowered:
            return icon
    return "#"


async def _get_or_create_category(session: AsyncSession, name: str) -> Category:
    result = await session.execute(select(Category).where(Category.name == name))
    category = result.scalar_one_or_none()
    if category:
        return category
    category = Category(name=name, icon=_category_icon(name), is_active=True)
    session.add(category)
    await session.flush()
    return category


async def sync_services_from_panel(session: AsyncSession) -> dict[str, int]:
    """Fetch services from smmpanelus.com and upsert into DB + Redis."""
    async with PanelClient() as client:
        panel_services = await client.get_services()

    seen_panel_ids: set[int] = set()
    created = updated = 0

    for item in panel_services:
        try:
            panel_id = int(item["service"])
            name = str(item.get("name") or f"Service {panel_id}")
            category_name = str(item.get("category") or "Other")
            panel_rate = Decimal(str(item.get("rate") or "0"))
            min_order = int(item.get("min") or 1)
            max_order = int(item.get("max") or min_order)
            panel_type = str(item.get("type") or "")
            description = item.get("description")
            refill = bool(item.get("refill"))
            cancel_allowed = bool(item.get("cancel"))
            dripfeed = bool(item.get("dripfeed"))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skip malformed panel service {}: {}", item, exc)
            continue

        seen_panel_ids.add(panel_id)
        service_type = detect_service_type(name, panel_type)
        resale_rate = calculate_resale_price(panel_rate, service_type)
        speed_rank, _ = detect_speed(name)
        category = await _get_or_create_category(session, category_name)

        result = await session.execute(
            select(Service).where(Service.panel_service_id == panel_id)
        )
        service = result.scalar_one_or_none()

        if service is None:
            session.add(
                Service(
                    panel_service_id=panel_id,
                    category_id=category.id,
                    name=name,
                    type=service_type,
                    panel_rate=panel_rate,
                    resale_rate=resale_rate,
                    min_order=min_order,
                    max_order=max_order,
                    description=description,
                    refill=refill,
                    cancel_allowed=cancel_allowed,
                    dripfeed=dripfeed,
                    speed_rank=speed_rank,
                    is_active=True,
                    last_synced_at=datetime.now(timezone.utc),
                )
            )
            created += 1
        else:
            service.category_id = category.id
            service.name = name
            service.type = service_type
            service.panel_rate = panel_rate
            service.resale_rate = resale_rate
            service.min_order = min_order
            service.max_order = max_order
            service.description = description
            service.refill = refill
            service.cancel_allowed = cancel_allowed
            service.dripfeed = dripfeed
            service.speed_rank = speed_rank
            service.is_active = True
            service.last_synced_at = datetime.now(timezone.utc)
            updated += 1

    if seen_panel_ids:
        await session.execute(
            update(Service)
            .where(Service.panel_service_id.not_in(seen_panel_ids))
            .values(is_active=False)
        )

    await session.flush()
    await _refresh_cache(session)

    stats = {"created": created, "updated": updated, "total": len(seen_panel_ids)}
    logger.info("Services sync done: {}", stats)
    return stats


async def _refresh_cache(session: AsyncSession) -> None:
    cats = (
        await session.execute(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order, Category.name)
        )
    ).scalars().all()

    categories_payload = [
        {"id": c.id, "name": c.name, "icon": c.icon or "#"} for c in cats
    ]
    await cache_set(CacheKeys.CATEGORIES, categories_payload)

    services = (
        await session.execute(select(Service).where(Service.is_active.is_(True)))
    ).scalars().all()

    all_services = []
    by_category: dict[int, list[dict]] = {}
    for s in services:
        payload = {
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
            "speed_rank": int(getattr(s, "speed_rank", 9) or 9),
        }
        all_services.append(payload)
        if s.category_id is not None:
            by_category.setdefault(s.category_id, []).append(payload)

    await cache_set(CacheKeys.SERVICES_ALL, all_services)
    for category_id, items in by_category.items():
        await cache_set(CacheKeys.SERVICES_BY_CATEGORY.format(category_id=category_id), items)

    # Drop derived indexes so they rebuild on next catalog open
    from app.core.platforms import OTHER, PLATFORMS
    from app.db.redis import _memory

    derived_keys = [CacheKeys.PLATFORMS, CacheKeys.PANEL_BALANCE]
    for slug, _, _ in PLATFORMS:
        derived_keys.append(CacheKeys.CATEGORIES_BY_PLATFORM.format(platform=slug))
        derived_keys.append(CacheKeys.SERVICES_BY_PLATFORM.format(platform=slug))
    derived_keys.append(CacheKeys.CATEGORIES_BY_PLATFORM.format(platform=OTHER[0]))
    derived_keys.append(CacheKeys.SERVICES_BY_PLATFORM.format(platform=OTHER[0]))
    await cache_delete(*derived_keys)
    # Also wipe any stale platform keys in memory backend
    for key in list(_memory.keys()):
        if key.startswith("categories:platform:") or key.startswith("services:platform:"):
            _memory.pop(key, None)
