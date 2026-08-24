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


class TopUpFSM(StatesGroup):
    entering_amount = State()
    choosing_method = State()


class BroadcastFSM(StatesGroup):
    waiting_text = State()
    confirming = State()
