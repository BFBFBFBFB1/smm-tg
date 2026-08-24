from aiogram import Router

from app.bot.handlers import admin, balance, catalog, order, orders_list, promo, referral, start


def setup_routers() -> Router:
    root = Router()
    root.include_router(start.router)
    root.include_router(catalog.router)
    root.include_router(order.router)
    root.include_router(balance.router)
    root.include_router(orders_list.router)
    root.include_router(referral.router)
    root.include_router(promo.router)
    root.include_router(admin.router)
    return root
