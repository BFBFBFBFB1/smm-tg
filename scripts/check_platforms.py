import asyncio

from app.db import async_session_factory
from app.services.catalog import get_categories_by_platform, get_platforms


async def main() -> None:
    async with async_session_factory() as s:
        plats = await get_platforms(s)
        print("platforms", len(plats), "total_services", sum(p["count"] for p in plats))
        for p in plats:
            cats = await get_categories_by_platform(s, p["slug"])
            print(f"  {p['name']}: services={p['count']} subcats={len(cats)}")


if __name__ == "__main__":
    asyncio.run(main())
