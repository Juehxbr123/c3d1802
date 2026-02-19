import asyncio
import logging
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import settings

logging.basicConfig(level=logging.INFO)

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)




def bot_cfg() -> dict[str, str]:
    try:
        return database.get_bot_config()
    except Exception:
        return {}


def get_cfg(key: str, default: str = "") -> str:
    return bot_cfg().get(key, default)


def get_orders_chat_id() -> str:
    return get_cfg("orders_chat_id", settings.orders_chat_id)


def photo_ref_for(step_key: str) -> str:
    cfg = bot_cfg()
    return cfg.get(step_key, "") or cfg.get("placeholder_photo_path", "") or settings.placeholder_photo_path


class Form(StatesGroup):
    step = State()


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_kb():
    return kb([
        [InlineKeyboardButton(text="📐 Рассчитать печать", callback_data="menu:print")],
        [InlineKeyboardButton(text="📡 3D-сканирование", callback_data="menu:scan")],
        [InlineKeyboardButton(text="❓ Нет модели / Хочу придумать", callback_data="menu:idea")],
        [InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu:about")],
    ])


def nav_row(include_back=True):
    row = []
    if include_back:
        row.append(InlineKeyboardButton(text="🔙 Назад", callback_data="nav:back"))
    row.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu"))
    return row


async def send_step(message: Message, text: str, keyboard: InlineKeyboardMarkup | None = None, photo_ref: str | None = None):
    ref = photo_ref or settings.placeholder_photo_path
    if ref:
        try:
            if ref.startswith("http://") or ref.startswith("https://"):
                await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
                return
            ref_path = Path(ref)
            if ref_path.exists() and ref_path.is_file():
                await message.answer_photo(photo=FSInputFile(str(ref_path)), caption=text, reply_markup=keyboard)
                return
            await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
            return
        except Exception:
            logging.exception("Не удалось отправить фото шага")
    await message.answer(text, reply_markup=keyboard)


async def send_step_cb(cb: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None, photo_ref: str | None = None):
    await send_step(cb.message, text, keyboard, photo_ref)
    await cb.answer()


def payload_summary(payload: dict) -> str:
    branch_map = {
        "print": "Рассчитать печать",
        "scan": "3D-сканирование",
        "idea": "Нет модели / Хочу придумать",
        "dialog": "Диалог",
    }
    field_map = {
        "technology": "Технология",
        "material": "Материал",
        "material_custom": "Другой материал",
        "scan_type": "Тип сканирования",
        "idea_type": "Категория",
        "description": "Описание",
        "file": "Файл",
    }

    branch = payload.get("branch", "")
    parts = [f"Тип заявки: {branch_map.get(branch, branch)}"]
    for key, value in payload.items():
        if key == "branch" or value in (None, ""):
            continue
        label = field_map.get(key, key)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        parts.append(f"• {label}: {value}")
    return "\n".join(parts)


async def show_main(message: Message, state: FSMContext):
    await state.clear()
    await send_step(message, get_cfg("welcome_menu_msg", "Добро пожаловать в Chel3D 👋\nВыберите нужный пункт меню:"), menu_kb(), photo_ref_for("photo_main_menu"))


async def start_order(cb: CallbackQuery, state: FSMContext, branch: str):
    order_id = database.create_order(cb.from_user.id, cb.from_user.username, cb.from_user.full_name, branch)
    await state.set_state(Form.step)
    await state.update_data(order_id=order_id, payload={"branch": branch}, history=[])


async def go_back(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    if not history:
        await show_main(cb.message, state)
        await cb.answer()
        return
    prev = history.pop()
    await state.update_data(history=history)
    await render_step(cb, state, prev, from_back=True)


async def render_step(cb: CallbackQuery, state: FSMContext, step: str, from_back: bool = False):
    if not from_back:
        data = await state.get_data()
        history = data.get("history", [])
        current = data.get("current_step")
        if current:
            history.append(current)
        await state.update_data(history=history)
    await state.update_data(current_step=step)

    if step == "print_tech":
        await send_step_cb(cb, "Выберите технологию печати:", kb([
            [InlineKeyboardButton(text="🧵 FDM (Пластик)", callback_data="set:technology:FDM")],
            [InlineKeyboardButton(text="💧 Фотополимер", callback_data="set:technology:Фотополимер")],
            [InlineKeyboardButton(text="🤷 Не знаю", callback_data="set:technology:Не знаю")],
            nav_row(False),
        ]), photo_ref_for("photo_print"))
    elif step == "scan_type":
        await send_step_cb(cb, "Что нужно отсканировать?", kb([
            [InlineKeyboardButton(text="🧑 Человек", callback_data="set:scan_type:Человек")],
            [InlineKeyboardButton(text="📦 Предмет", callback_data="set:scan_type:Предмет")],
            [InlineKeyboardButton(text="🏭 Промышленный объект", callback_data="set:scan_type:Промышленный объект")],
            [InlineKeyboardButton(text="🤔 Другое", callback_data="set:scan_type:Другое")],
            nav_row(False),
        ]), photo_ref_for("photo_scan"))
    elif step == "idea_type":
        await send_step_cb(cb, "Выберите категорию:", kb([
            [InlineKeyboardButton(text="✏️ По фото/эскизу", callback_data="set:idea_type:По фото/эскизу")],
            [InlineKeyboardButton(text="🏆 Сувенир/Кубок/Медаль", callback_data="set:idea_type:Сувенир/Кубок/Медаль")],
            [InlineKeyboardButton(text="📏 Мастер-модель", callback_data="set:idea_type:Мастер-модель")],
            [InlineKeyboardButton(text="🎨 Вывески", callback_data="set:idea_type:Вывески")],
            [InlineKeyboardButton(text="🤔 Другое", callback_data="set:idea_type:Другое")],
            nav_row(False),
        ]), photo_ref_for("photo_idea"))
    elif step == "about":
        await send_step_cb(cb, get_cfg("about_text", "Chel3D — 3D-печать, 3D-сканирование и разработка моделей."), kb([
            [InlineKeyboardButton(text="🏭 Оборудование", callback_data="about:eq")],
            [InlineKeyboardButton(text="🖼 Наши проекты", callback_data="about:projects")],
            [InlineKeyboardButton(text="📞 Контакты", callback_data="about:contacts")],
            [InlineKeyboardButton(text="📍 На карте", callback_data="about:map")],
            nav_row(False),
        ]), photo_ref_for("photo_about"))


async def persist(state: FSMContext):
    data = await state.get_data()
    database.update_order_payload(data["order_id"], data.get("payload", {}), payload_summary(data.get("payload", {})))


def step_keyboard_for_print(payload: dict):
    tech = payload.get("technology")
    if tech == "FDM":
        mat_rows = [[InlineKeyboardButton(text=t, callback_data=f"set:material:{t}")] for t in ["PET-G", "PLA", "PET-G Carbon", "TPU", "Нейлон", "🤔 Другой материал"]]
    elif tech == "Фотополимер":
        mat_rows = [[InlineKeyboardButton(text=t, callback_data=f"set:material:{t}")] for t in ["Стандартная", "ABS-Like", "TPU-Like", "Нейлон-Like", "🤔 Другая смола"]]
    else:
        mat_rows = [[InlineKeyboardButton(text="Пропустить", callback_data="set:material:Не выбрано")]]
    mat_rows.append(nav_row())
    return kb(mat_rows)


async def on_start(message: Message, state: FSMContext):
    await show_main(message, state)


async def on_menu(cb: CallbackQuery, state: FSMContext):
    branch = cb.data.split(":", 1)[1]
    if branch == "about":
        await render_step(cb, state, "about")
        return
    await start_order(cb, state, branch)
    step = {"print": "print_tech", "scan": "scan_type", "idea": "idea_type"}[branch]
    await render_step(cb, state, step)


async def on_about_item(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    mapping = {
        "eq": ("about_equipment_text", "photo_about_equipment", "🏭 Наше оборудование"),
        "projects": ("about_projects_text", "photo_about_projects", "🖼 Наши проекты"),
        "contacts": ("about_contacts_text", "photo_about_contacts", "📞 Контакты"),
        "map": ("about_map_text", "photo_about_map", "📍 Мы на карте"),
    }
    text_key, photo_key, default_text = mapping.get(key, ("about_text", "photo_about", "О нас"))
    await send_step_cb(cb, get_cfg(text_key, default_text), kb([nav_row()]), photo_ref_for(photo_key))


async def on_set(cb: CallbackQuery, state: FSMContext):
    _, key, value = cb.data.split(":", 2)
    data = await state.get_data()
    payload = data.get("payload", {})
    payload[key] = value
    await state.update_data(payload=payload)
    await persist(state)

    if key == "technology":
        await send_step_cb(cb, "Выберите материал:", step_keyboard_for_print(payload))
    elif key == "material":
        if value.startswith("🤔"):
            await state.update_data(waiting_text="other_material")
            await send_step_cb(cb, "Опишите материал/смолу свободным текстом:", kb([nav_row()]))
        else:
            await send_step_cb(cb, "Прикрепите STL/3MF/OBJ как документ или нажмите ❌ У меня нет файла", kb([
                [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
                nav_row(),
            ]))
    elif key in {"scan_type", "idea_type"}:
        await state.update_data(waiting_text="description")
        await send_step_cb(cb, "Опишите задачу свободным текстом:", kb([nav_row()]))
    elif key == "file":
        await send_result(cb, state)
    else:
        await cb.answer("Сохранено")


async def on_text(message: Message, state: FSMContext):
    data = await state.get_data()
    waiting = data.get("waiting_text")
    if not waiting:
        order_id = database.find_or_create_active_order(message.from_user.id, message.from_user.username, message.from_user.full_name)
        database.add_order_message(order_id, "in", message.text or "")
        await send_step(message, "Сообщение получено. Менеджер ответит в этом чате.")
        return

    payload = data.get("payload", {})
    if waiting == "other_material":
        payload["material_custom"] = message.text
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        await send_step(message, "Прикрепите STL/3MF/OBJ как документ или нажмите кнопку ниже.", kb([
            [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
            nav_row(),
        ]))
    elif waiting == "description":
        payload["description"] = message.text
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        await send_result_message(message, state)

    database.add_order_message(data["order_id"], "in", message.text or "")


async def on_file(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if not data.get("order_id"):
        await send_step(message, "Сначала создайте заявку через главное меню.")
        return
    doc = message.document
    if not doc:
        return
    ext = (doc.file_name or "").lower().split(".")[-1]
    if ext not in {"stl", "3mf", "obj"}:
        await send_step(message, "Поддерживаются только STL/3MF/OBJ.")
        return

    local_path = None
    try:
        file = await bot.get_file(doc.file_id)
        local_path = str(UPLOADS_DIR / f"{doc.file_unique_id}_{doc.file_name}")
        await bot.download_file(file.file_path, destination=local_path)
    except Exception:
        logging.exception("Не удалось скачать файл локально")

    database.add_order_file(data["order_id"], doc.file_id, doc.file_name or "model", doc.mime_type, doc.file_size, message.message_id, local_path)
    await send_result_message(message, state)


async def send_result(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    payload = data.get("payload", {})
    text = f"Проверьте заявку:\n{payload_summary(payload)}\n\n💰 Уточнит менеджер после проверки."
    await send_step_cb(cb, text, kb([
        [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="submit:order")],
        [InlineKeyboardButton(text="🔁 Новый расчет", callback_data="nav:menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu")],
    ]))


async def send_result_message(message: Message, state: FSMContext):
    data = await state.get_data()
    payload = data.get("payload", {})
    text = f"Проверьте заявку:\n{payload_summary(payload)}\n\n💰 Уточнит менеджер после проверки."
    await send_step(message, text, kb([
        [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="submit:order")],
        [InlineKeyboardButton(text="🔁 Новый расчет", callback_data="nav:menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu")],
    ]))


async def on_submit(cb: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        data = await state.get_data()
        order_id = data.get("order_id")
        if not order_id:
            await send_step_cb(cb, "Не найдена активная заявка. Откройте главное меню и начните заново.", menu_kb())
            await state.clear()
            return

        payload = data.get("payload", {})
        summary = payload_summary(payload)
        database.finalize_order(order_id, summary)
        database.add_order_message(order_id, "in", "Заявка отправлена")

        orders_chat_id = get_orders_chat_id()
        if orders_chat_id:
            try:
                await bot.send_message(orders_chat_id, f"Новая заявка #{order_id}\n{summary}")
            except Exception:
                logging.exception("Не удалось отправить заявку в группу")

        await send_step_cb(cb, "Спасибо! Заявка отправлена менеджеру ✅", menu_kb())
        await state.clear()
    except Exception:
        logging.exception("Ошибка при отправке заявки")
        await send_step_cb(cb, "Не удалось отправить заявку. Попробуйте ещё раз через минуту.", menu_kb())


async def on_nav(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":", 1)[1]
    if action == "menu":
        await show_main(cb.message, state)
        await cb.answer()
    elif action == "back":
        await go_back(cb, state)


async def internal_send_message(request: web.Request):
    if settings.internal_api_key and request.headers.get("X-Internal-Key") != settings.internal_api_key:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    data = await request.json()
    user_id = data.get("user_id")
    text = data.get("text", "")
    order_id = data.get("order_id")
    bot: Bot = request.app["bot"]
    try:
        sent = await bot.send_message(user_id, text)
        if order_id:
            database.add_order_message(order_id, "out", text, sent.message_id)
        return web.json_response({"ok": True, "message_id": sent.message_id})
    except Exception:
        return web.json_response({"ok": False, "error": "Не удалось отправить сообщение в Telegram"}, status=400)


async def setup_internal_api(bot: Bot):
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/sendMessage", internal_send_message)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.internal_api_host, settings.internal_api_port)
    await site.start()
    return runner


def register_handlers(dp: Dispatcher, bot: Bot):
    async def submit_handler(cb: CallbackQuery, state: FSMContext):
        await on_submit(cb, state, bot)

    async def file_handler(message: Message, state: FSMContext):
        await on_file(message, state, bot)

    dp.message.register(on_start, CommandStart())
    dp.callback_query.register(on_menu, F.data.startswith("menu:"))
    dp.callback_query.register(on_nav, F.data.startswith("nav:"))
    dp.callback_query.register(on_set, F.data.startswith("set:"))
    dp.callback_query.register(on_about_item, F.data.startswith("about:"))
    dp.callback_query.register(submit_handler, F.data == "submit:order")
    dp.message.register(file_handler, F.content_type == ContentType.DOCUMENT)
    dp.message.register(on_text, Form.step)


async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty")

    database.init_db_if_needed()
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp, bot)
    internal_runner = await setup_internal_api(bot)
    try:
        await dp.start_polling(bot)
    finally:
        await internal_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
