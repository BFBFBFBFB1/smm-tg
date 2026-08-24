from aiogram.fsm.state import State, StatesGroup


class OrderFSM(StatesGroup):
    choosing_platform = State()
    choosing_category = State()
    choosing_service = State()
    searching = State()
    entering_link = State()
    entering_quantity = State()
    confirming = State()
    choosing_payment = State()
    entering_promo = State()


class TopUpFSM(StatesGroup):
    entering_amount = State()
    choosing_method = State()


class PromoMenuFSM(StatesGroup):
    entering = State()


class BroadcastFSM(StatesGroup):
    waiting_text = State()
    confirming = State()


class AdminFSM(StatesGroup):
    give_balance_user = State()
    give_balance_amount = State()
    take_balance_user = State()
    take_balance_amount = State()
    ban_user = State()
    promo_code = State()
    promo_type = State()
    promo_value = State()
    promo_max_uses = State()
    find_user = State()
