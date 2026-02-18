import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

import database
from config import settings

logging.basicConfig(level=logging.INFO)

MENU_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📐 Рассчитать печать")],
        [KeyboardButton(text="📡 3D-сканирование")],
        [KeyboardButton(text="❓ Нет модели / Идея")],
        [KeyboardButton(text="ℹ️ О нас")],
    ],
    resize_keyboard=True,
)
SKIP_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="➡️ Пропустить шаг")]],
    resize_keyboard=True,
)
FILES_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✅ Готово")], [KeyboardButton(text="➡️ Пропустить шаг")]],
    resize_keyboard=True,
)


class Form(StatesGroup):
    print_type = State()
    print_dimensions = State()
    print_conditions = State()
    urgency = State()
    comment = State()
    files = State()

    scan_object = State()
    scan_dimensions = State()
    scan_location = State()
    scan_details = State()

    idea_description = State()
    idea_references = State()
    idea_dimensions = State()


SAFE_REPLY = "Сервис временно недоступен, попробуйте позже"


async def reply_db_error(message: Message):
    await message.answer(SAFE_REPLY, reply_markup=MENU_KEYBOARD)


def get_step_value(text: str) -> str:
    return "Другое" if text == "➡️ Пропустить шаг" else text


async def start_branch(message: Message, state: FSMContext, branch: str, first_state: State, first_question: str):
    try:
        database.cancel_old_filling_orders(message.from_user.id)
        order_id = database.create_order(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            branch=branch,
        )
    except Exception:
        logging.exception("Failed to create branch")
        await reply_db_error(message)
        return

    await state.clear()
    await state.set_state(first_state)
    await state.update_data(order_id=order_id, branch=branch)
    await message.answer(first_question, reply_markup=SKIP_KEYBOARD)


async def update_field_and_ask_next(
    message: Message,
    state: FSMContext,
    field_name: str,
    next_state: State,
    next_question: str,
):
    data = await state.get_data()
    order_id = data.get("order_id")

    try:
        database.update_order_field(order_id, field_name, get_step_value(message.text or ""))
    except Exception:
        logging.exception("Failed to update order field")
        await reply_db_error(message)
        await state.clear()
        return

    await state.set_state(next_state)
    await message.answer(next_question, reply_markup=SKIP_KEYBOARD)


async def finish_order(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")

    try:
        database.finalize_order(order_id)
    except Exception:
        logging.exception("Failed to finalize order")
        await reply_db_error(message)
        await state.clear()
        return

    await state.clear()
    await message.answer("Спасибо! Заявка отправлена менеджеру ✅", reply_markup=MENU_KEYBOARD)


async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    try:
        config = database.get_bot_config()
        text = config.get(
            "welcome_menu_msg",
            "Добро пожаловать в Chel3D 👋\nВыберите нужный пункт меню:",
        )
    except Exception:
        text = "Добро пожаловать в Chel3D 👋\nВыберите нужный пункт меню:"

    await message.answer(text, reply_markup=MENU_KEYBOARD)


async def about_handler(message: Message):
    try:
        config = database.get_bot_config()
        text = config.get(
            "about_text",
            "Chel3D — 3D-печать, 3D-сканирование и помощь в создании модели.",
        )
    except Exception:
        text = "Chel3D — 3D-печать, 3D-сканирование и помощь в создании модели."
    await message.answer(text, reply_markup=MENU_KEYBOARD)


async def print_start(message: Message, state: FSMContext):
    await start_branch(
        message,
        state,
        branch="print_3d",
        first_state=Form.print_type,
        first_question="Тип работы (FDM / Фотополимер / Не знаю):",
    )


async def scan_start(message: Message, state: FSMContext):
    await start_branch(
        message,
        state,
        branch="scan_3d",
        first_state=Form.scan_object,
        first_question="Что нужно отсканировать?",
    )


async def idea_start(message: Message, state: FSMContext):
    await start_branch(
        message,
        state,
        branch="no_model_idea",
        first_state=Form.idea_description,
        first_question="Опишите вашу идею:",
    )


async def on_print_type(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "step_type", Form.print_dimensions, "Размеры / габариты:")


async def on_print_dimensions(message: Message, state: FSMContext):
    await update_field_and_ask_next(
        message,
        state,
        "step_dimensions",
        Form.print_conditions,
        "Условия (материал/цвет/прочность/назначение):",
    )


async def on_print_conditions(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "step_conditions", Form.urgency, "Срочность:")


async def on_scan_object(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "scan_object", Form.scan_dimensions, "Размеры / габариты объекта:")


async def on_scan_dimensions(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "scan_dimensions", Form.scan_location, "Где находится объект?")


async def on_scan_location(message: Message, state: FSMContext):
    await update_field_and_ask_next(
        message,
        state,
        "scan_location",
        Form.scan_details,
        "Нужна ли высокая детализация? Опишите требования:",
    )


async def on_scan_details(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "scan_details", Form.urgency, "Срочность:")


async def on_idea_description(message: Message, state: FSMContext):
    await update_field_and_ask_next(
        message,
        state,
        "idea_description",
        Form.idea_references,
        "Есть ли референсы? Опишите или вставьте ссылку:",
    )


async def on_idea_references(message: Message, state: FSMContext):
    await update_field_and_ask_next(
        message,
        state,
        "idea_references",
        Form.idea_dimensions,
        "Габариты / назначение изделия:",
    )


async def on_idea_dimensions(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "idea_dimensions", Form.urgency, "Срочность:")


async def on_urgency_common(message: Message, state: FSMContext):
    await update_field_and_ask_next(message, state, "step_urgency", Form.comment, "Комментарий:")


async def on_comment_common(message: Message, state: FSMContext):
    await update_field_and_ask_next(
        message,
        state,
        "step_comment",
        Form.files,
        "Прикрепите файлы (документы/фото). Нажмите ✅ Готово для завершения.",
    )
    await message.answer("Можно отправить несколько файлов.", reply_markup=FILES_KEYBOARD)


async def file_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")

    file_id = None
    file_name = "file"
    mime = None
    size = None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "document"
        mime = message.document.mime_type
        size = message.document.file_size
    elif message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_name = f"photo_{photo.file_unique_id}.jpg"
        size = photo.file_size
        mime = "image/jpeg"

    if not file_id:
        await message.answer("Отправьте документ/фото или нажмите ✅ Готово", reply_markup=FILES_KEYBOARD)
        return

    try:
        database.add_order_file(order_id, file_id, file_name, mime, size)
    except Exception:
        logging.exception("Failed to save file")
        await reply_db_error(message)
        await state.clear()
        return

    await message.answer("Файл сохранён. Можете отправить ещё или нажать ✅ Готово", reply_markup=FILES_KEYBOARD)


async def files_done(message: Message, state: FSMContext):
    await finish_order(message, state)


async def fallback_handler(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Выберите пункт меню, чтобы оформить заявку 🙂", reply_markup=MENU_KEYBOARD)
        return

    await message.answer("Пожалуйста, ответьте на вопрос шага или нажмите ➡️ Пропустить шаг")


async def on_startup():
    database.init_db_if_needed()


def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(about_handler, F.text == "ℹ️ О нас")

    dp.message.register(print_start, F.text == "📐 Рассчитать печать")
    dp.message.register(scan_start, F.text == "📡 3D-сканирование")
    dp.message.register(idea_start, F.text == "❓ Нет модели / Идея")

    dp.message.register(on_print_type, Form.print_type)
    dp.message.register(on_print_dimensions, Form.print_dimensions)
    dp.message.register(on_print_conditions, Form.print_conditions)

    dp.message.register(on_scan_object, Form.scan_object)
    dp.message.register(on_scan_dimensions, Form.scan_dimensions)
    dp.message.register(on_scan_location, Form.scan_location)
    dp.message.register(on_scan_details, Form.scan_details)

    dp.message.register(on_idea_description, Form.idea_description)
    dp.message.register(on_idea_references, Form.idea_references)
    dp.message.register(on_idea_dimensions, Form.idea_dimensions)

    dp.message.register(on_urgency_common, Form.urgency)
    dp.message.register(on_comment_common, Form.comment)

    dp.message.register(file_handler, Form.files, F.content_type.in_({ContentType.DOCUMENT, ContentType.PHOTO}))
    dp.message.register(files_done, Form.files, F.text.in_({"✅ Готово", "➡️ Пропустить шаг"}))

    dp.message.register(fallback_handler)


async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty")

    await on_startup()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
