import asyncio
import html
import logging
from pathlib import Path
from typing import Any, Optional

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import database
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chel3d_bot")

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)


# -----------------------------
# Config helpers (from DB + env)
# -----------------------------
def bot_cfg() -> dict[str, str]:
    try:
        return database.get_bot_config()
    except Exception:
        return {}


def get_cfg(key: str, default: str = "") -> str:
    val = bot_cfg().get(key, "")
    if val is None or val == "":
        return default
    return str(val)


def cfg_bool(key: str, default: bool = True) -> bool:
    raw = bot_cfg().get(key, "")
    if raw is None or raw == "":
        return default
    return str(raw).lower() in {"1", "true", "yes", "on"}


def get_orders_chat_id() -> str:
    # DB value has priority, then env/settings
    return get_cfg("orders_chat_id", getattr(settings, "orders_chat_id", ""))


def photo_ref_for(step_key: str) -> str:
    cfg = bot_cfg()
    return (
        cfg.get(step_key, "")
        or cfg.get("placeholder_photo_path", "")
        or getattr(settings, "placeholder_photo_path", "")
    )


# -----------------------------
# FSM
# -----------------------------
class Form(StatesGroup):
    step = State()


# -----------------------------
# Keyboards
# -----------------------------
def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if cfg_bool("enabled_menu_print", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_cfg("btn_menu_print", "📐 Рассчитать печать"),
                    callback_data="menu:print",
                )
            ]
        )
    if cfg_bool("enabled_menu_scan", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_cfg("btn_menu_scan", "📡 3D-сканирование"),
                    callback_data="menu:scan",
                )
            ]
        )
    if cfg_bool("enabled_menu_idea", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_cfg("btn_menu_idea", "❓ Нет модели / Хочу придумать"),
                    callback_data="menu:idea",
                )
            ]
        )
    if cfg_bool("enabled_menu_about", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_cfg("btn_menu_about", "ℹ️ О нас"),
                    callback_data="menu:about",
                )
            ]
        )
    if not rows:
        rows = [[InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu:about")]]
    return kb(rows)


def nav_row(include_back: bool = True) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if include_back:
        row.append(InlineKeyboardButton(text="🔙 Назад", callback_data="nav:back"))
    row.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu"))
    return row


def step_keyboard_for_print(payload: dict[str, Any]) -> InlineKeyboardMarkup:
    tech = payload.get("technology")
    if tech == "FDM":
        items = [
            "PET-G",
            "PLA",
            "PET-G Carbon",
            "TPU",
            "Нейлон",
            "🤔 Другой материал",
        ]
    elif tech == "Фотополимер":
        items = [
            "Стандартная",
            "ABS-Like",
            "TPU-Like",
            "Нейлон-Like",
            "🤔 Другая смола",
        ]
    else:
        items = ["Пропустить"]

    rows = [[InlineKeyboardButton(text=t, callback_data=f"set:material:{t}")] for t in items]
    rows.append(nav_row())
    return kb(rows)


# -----------------------------
# Messaging helpers
# -----------------------------
async def send_step(
    message: Message,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    photo_ref: Optional[str] = None,
) -> None:
    ref = photo_ref or getattr(settings, "placeholder_photo_path", "")
    if ref:
        try:
            if ref.startswith("http://") or ref.startswith("https://"):
                await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
                return

            p = Path(ref)
            if p.exists() and p.is_file():
                await message.answer_photo(photo=FSInputFile(str(p)), caption=text, reply_markup=keyboard)
                return

            # might be telegram file_id
            await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
            return
        except Exception:
            logger.exception("Не удалось отправить фото — отправляю текстом")

    await message.answer(text, reply_markup=keyboard)


async def send_step_cb(
    cb: CallbackQuery,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    photo_ref: Optional[str] = None,
) -> None:
    if cb.message:
        await send_step(cb.message, text, keyboard, photo_ref)
    await cb.answer()


def payload_summary(payload: dict[str, Any]) -> str:
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

    branch = str(payload.get("branch", ""))
    parts: list[str] = [f"Тип заявки: {branch_map.get(branch, branch)}"]

    for key, value in payload.items():
        if key == "branch" or value in (None, ""):
            continue
        label = field_map.get(key, key)
        if isinstance(value, list):
            value = ", ".join(str(x) for x in value)
        parts.append(f"• {label}: {value}")

    return "\n".join(parts)


async def persist(state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        return
    payload = data.get("payload", {})
    database.update_order_payload(int(order_id), payload, payload_summary(payload))

def get_orders_chat_id() -> str:
    return get_cfg("orders_chat_id", settings.orders_chat_id)

# -----------------------------
# Flow
# -----------------------------
async def show_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_step(
        message,
        get_cfg(
            "welcome_menu_msg",
            "Привет! 👋 Я бот Chel3D.\nВыберите, что вам нужно — и я соберу заявку по шагам.",
        ),
        menu_kb(),
        photo_ref_for("photo_main_menu"),
    )

def get_cfg(key: str, default: str = "") -> str:
    return bot_cfg().get(key, default)

async def start_order(cb: CallbackQuery, state: FSMContext, branch: str) -> None:
    order_id = database.create_order(cb.from_user.id, cb.from_user.username, cb.from_user.full_name, branch)
    await state.set_state(Form.step)
    await state.update_data(order_id=order_id, payload={"branch": branch}, history=[], current_step=None, waiting_text=None)

    if branch == "print":
        await render_step(cb, state, "print_tech")
    elif branch == "scan":
        await render_step(cb, state, "scan_type")
    elif branch == "idea":
        await render_step(cb, state, "idea_type")
    elif branch == "about":
        await render_step(cb, state, "about")
    else:
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()


async def go_back(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    history: list[str] = data.get("history", [])
    if not history:
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return

    prev = history.pop()
    await state.update_data(history=history)
    await render_step(cb, state, prev, from_back=True)

def get_orders_chat_id() -> str:
    return get_cfg("orders_chat_id", settings.orders_chat_id)

def _push_history(state_data: dict[str, Any]) -> list[str]:
    history: list[str] = state_data.get("history", [])
    current = state_data.get("current_step")
    if current:
        history.append(current)
    return history


async def render_step(cb: CallbackQuery, state: FSMContext, step: str, from_back: bool = False) -> None:
    if not from_back:
        data = await state.get_data()
        await state.update_data(history=_push_history(data))
    await state.update_data(current_step=step, waiting_text=None)

    data = await state.get_data()
    payload: dict[str, Any] = data.get("payload", {})

    if step == "print_tech":
        rows = [
            [InlineKeyboardButton(text=get_cfg("btn_print_fdm", "🧵 FDM (Пластик)"), callback_data="set:technology:FDM")],
            [InlineKeyboardButton(text=get_cfg("btn_print_resin", "💧 Фотополимер"), callback_data="set:technology:Фотополимер")],
            [InlineKeyboardButton(text=get_cfg("btn_print_unknown", "🤷 Не знаю"), callback_data="set:technology:Не знаю")],
            nav_row(False),
        ]
        await send_step_cb(cb, get_cfg("text_print_tech", "Выберите технологию печати:"), kb(rows), photo_ref_for("photo_print"))
        return

    if step == "print_material":
        await send_step_cb(cb, get_cfg("text_select_material", "Выберите материал:"), step_keyboard_for_print(payload), photo_ref_for("photo_print"))
        return

    if step == "print_material_custom":
        await state.update_data(waiting_text="material_custom")
        rows = [nav_row()]
        await send_step_cb(
            cb,
            get_cfg("text_describe_material", "Напишите, какой материал нужен (одним сообщением):"),
            kb([rows[0]]),
            photo_ref_for("photo_print"),
        )
        return

    if step == "scan_type":
        rows = [
            [InlineKeyboardButton(text=get_cfg("btn_scan_human", "🧑 Человек"), callback_data="set:scan_type:Человек")],
            [InlineKeyboardButton(text=get_cfg("btn_scan_object", "📦 Предмет"), callback_data="set:scan_type:Предмет")],
            [InlineKeyboardButton(text=get_cfg("btn_scan_industrial", "🏭 Промышленный объект"), callback_data="set:scan_type:Промышленный объект")],
            [InlineKeyboardButton(text=get_cfg("btn_scan_other", "🤔 Другое"), callback_data="set:scan_type:Другое")],
            nav_row(False),
        ]
        await send_step_cb(cb, get_cfg("text_scan_type", "Что нужно отсканировать?"), kb(rows), photo_ref_for("photo_scan"))
        return

    if step == "idea_type":
        rows = [
            [InlineKeyboardButton(text=get_cfg("btn_idea_photo", "✏️ По фото/эскизу"), callback_data="set:idea_type:По фото/эскизу")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_award", "🏆 Сувенир/Кубок/Медаль"), callback_data="set:idea_type:Сувенир/Кубок/Медаль")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_master", "📏 Мастер-модель"), callback_data="set:idea_type:Мастер-модель")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_sign", "🎨 Вывески"), callback_data="set:idea_type:Вывески")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_other", "🤔 Другое"), callback_data="set:idea_type:Другое")],
            nav_row(False),
        ]
        await send_step_cb(cb, get_cfg("text_idea_type", "Выберите категорию:"), kb(rows), photo_ref_for("photo_idea"))
        return

    if step == "describe_task":
        await state.update_data(waiting_text="description")
        rows = [nav_row()]
        await send_step_cb(
            cb,
            get_cfg("text_describe_task", "Опишите задачу (одним сообщением):"),
            kb([rows[0]]),
            photo_ref_for("photo_idea"),
        )
        return

    if step == "attach_file":
        await state.update_data(waiting_text="file")
        rows = [
            [InlineKeyboardButton(text="➡️ Пропустить шаг", callback_data="set:file:skip")],
            nav_row(),
        ]
        await send_step_cb(
            cb,
            get_cfg("text_attach_file", "Прикрепите файл (STL/3MF/OBJ) или нажмите «Пропустить шаг»."),
            kb(rows),
            photo_ref_for("photo_print"),
        )
        return

    if step == "about":
        rows = [
            [InlineKeyboardButton(text=get_cfg("btn_about_equipment", "🏭 Оборудование"), callback_data="about:eq")],
            [InlineKeyboardButton(text=get_cfg("btn_about_projects", "🖼 Наши проекты"), callback_data="about:projects")],
            [InlineKeyboardButton(text=get_cfg("btn_about_contacts", "📞 Контакты"), callback_data="about:contacts")],
            [InlineKeyboardButton(text=get_cfg("btn_about_map", "📍 На карте"), callback_data="about:map")],
            nav_row(False),
        ]
        await send_step_cb(cb, get_cfg("about_text", "Chel3D — 3D-печать, 3D-сканирование и разработка моделей."), kb(rows), photo_ref_for("photo_about"))
        return

    # fallback
    if cb.message:
        await show_main(cb.message, state)
    await cb.answer()


# -----------------------------
# Handlers
# -----------------------------
dp = Dispatcher(storage=MemoryStorage())


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await show_main(message, state)


@dp.callback_query(F.data.startswith("menu:"))
async def on_menu(cb: CallbackQuery, state: FSMContext):
    branch = cb.data.split(":", 1)[1]
    if branch == "about":
        await start_order(cb, state, "about")
        return
    await start_order(cb, state, branch)


@dp.callback_query(F.data == "nav:menu")
async def on_nav_menu(cb: CallbackQuery, state: FSMContext):
    if cb.message:
        await show_main(cb.message, state)
    await cb.answer()

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

@dp.callback_query(F.data == "nav:back")
async def on_nav_back(cb: CallbackQuery, state: FSMContext):
    await go_back(cb, state)


@dp.callback_query(F.data.startswith("about:"))
async def on_about(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    mapping = {
        "eq": ("about_equipment_text", "photo_about_equipment"),
        "projects": ("about_projects_text", "photo_about_projects"),
        "contacts": ("about_contacts_text", "photo_about_contacts"),
        "map": ("about_map_text", "photo_about_map"),
    }
    text_key, photo_key = mapping.get(key, ("about_text", "photo_about"))
    await send_step_cb(cb, get_cfg(text_key, ""), kb([nav_row()]), photo_ref_for(photo_key))


@dp.callback_query(F.data.startswith("set:"))
async def on_set(cb: CallbackQuery, state: FSMContext):
    _, field, value = cb.data.split(":", 2)
    data = await state.get_data()
    payload: dict[str, Any] = data.get("payload", {}) or {}
    waiting_text = data.get("waiting_text")

    if field == "technology":
        payload["technology"] = value
        await state.update_data(payload=payload)
        await persist(state)
        await render_step(cb, state, "print_material")
        return

    if field == "material":
        if value == "🤔 Другой материал":
            payload["material"] = "Другой материал"
            await state.update_data(payload=payload)
            await persist(state)
            await render_step(cb, state, "print_material_custom")
            return

        payload["material"] = value
        await state.update_data(payload=payload)
        await persist(state)
        await render_step(cb, state, "describe_task")
        return

    if field == "scan_type":
        payload["scan_type"] = value
        await state.update_data(payload=payload)
        await persist(state)
        await render_step(cb, state, "describe_task")
        return

    if field == "idea_type":
        payload["idea_type"] = value
        await state.update_data(payload=payload)
        await persist(state)
        await render_step(cb, state, "describe_task")
        return

    if field == "file":
        if value == "skip":
            payload["file"] = "Пропущено"
            await state.update_data(payload=payload)
            await persist(state)

            order_id = int((await state.get_data()).get("order_id"))
            database.finalize_order(order_id, payload_summary(payload))

            msg = get_cfg("text_submit_ok", "✅ Заявка отправлена! Мы скоро свяжемся с вами.")
            await send_step_cb(cb, msg, kb([nav_row(False)]), photo_ref_for("photo_main_menu"))

            await notify_orders_chat(cb, payload, order_id)
            return

    # unknown
    await cb.answer()


@dp.message(F.content_type == ContentType.TEXT)
async def on_text(message: Message, state: FSMContext):
    data = await state.get_data()
    waiting_text = data.get("waiting_text")
    if not waiting_text:
        return

    payload: dict[str, Any] = data.get("payload", {}) or {}
    if waiting_text == "material_custom":
        payload["material_custom"] = message.text.strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        await send_step(message, "✅ Принято.", kb([nav_row()]))
        return

    if waiting_text == "description":
        payload["description"] = message.text.strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        await send_step(message, "✅ Принято. Теперь можно прикрепить файл.", kb([nav_row()]))
        # after description always ask for file
        cb_fake = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", data="", message=message)
        await render_step(cb_fake, state, "attach_file")  # type: ignore[arg-type]
        return

async def on_set(cb: CallbackQuery, state: FSMContext):
    _, key, value = cb.data.split(":", 2)
    data = await state.get_data()
    payload = data.get("payload", {})
    payload[key] = value
    await state.update_data(payload=payload)
    await persist(state)

    if key == "technology":
        await send_step_cb(cb, get_cfg("text_select_material", "Выберите материал:"), step_keyboard_for_print(payload))
    elif key == "material":
        if value.startswith("🤔"):
            await state.update_data(waiting_text="other_material")
            await send_step_cb(cb, get_cfg("text_describe_material", "Опишите материал/смолу свободным текстом:"), kb([nav_row()]))
        else:
            await send_step_cb(cb, get_cfg("text_attach_file", "Прикрепите STL/3MF/OBJ документ или фото, либо нажмите ❌ У меня нет файла"), kb([
                [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
                nav_row(),
            ]))
    elif key in {"scan_type", "idea_type", "goods_type"}:
        await state.update_data(waiting_text="description")
        await send_step_cb(cb, get_cfg("text_describe_task", "Опишите задачу свободным текстом:"), kb([nav_row()]))
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

@dp.message(F.content_type.in_({ContentType.DOCUMENT, ContentType.PHOTO}))
async def on_file(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("waiting_text") != "file":
        return

    order_id = int(data.get("order_id"))
    payload: dict[str, Any] = data.get("payload", {}) or {}

    file_id = None
    filename = None
    mime = None
    size = None

    if message.document:
        file_id = message.document.file_id
        filename = message.document.file_name
        mime = message.document.mime_type
        size = message.document.file_size
    elif message.photo:
        p = message.photo[-1]
        file_id = p.file_id
        filename = "photo.jpg"
        mime = "image/jpeg"
        size = p.file_size

    if not file_id:
        await message.answer("Не смог распознать файл. Попробуйте ещё раз.")
        return

    local_path = None
    try:
        database.add_order_file(order_id, file_id, filename, mime, size, message.message_id, None)
    except Exception:
        logger.exception("Не удалось сохранить файл в БД")

    payload["file"] = filename or "Файл"
    await state.update_data(payload=payload, waiting_text=None)
    await persist(state)

    database.finalize_order(order_id, payload_summary(payload))
    await message.answer(get_cfg("text_submit_ok", "✅ Заявка отправлена! Мы скоро свяжемся с вами."), reply_markup=kb([nav_row(False)]))
    await notify_orders_chat_message(message, payload, order_id)

async def send_result_message(message: Message, state: FSMContext):
    data = await state.get_data()
    payload = data.get("payload", {})
    text = f"{get_cfg('text_result_prefix', 'Проверьте заявку:')}\n{payload_summary(payload)}\n\n{get_cfg('text_price_note', '💰 Уточнит менеджер после проверки.')}"
    await send_step(message, text, kb([
        [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="submit:order")],
        [InlineKeyboardButton(text="🔁 Новый расчет", callback_data="nav:menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu")],
    ]))

async def notify_orders_chat(cb: CallbackQuery, payload: dict[str, Any], order_id: int) -> None:
    if not cb.bot:
        return
    chat_id = get_orders_chat_id()
    if not chat_id:
        return
    try:
        await cb.bot.send_message(chat_id=chat_id, text=f"🆕 Новая заявка #{order_id}\n\n{payload_summary(payload)}")
    except Exception:
        logger.exception("Не удалось отправить заявку в чат заказов")


async def notify_orders_chat_message(message: Message, payload: dict[str, Any], order_id: int) -> None:
    chat_id = get_orders_chat_id()
    if not chat_id:
        return
    try:
        await message.bot.send_message(chat_id=chat_id, text=f"🆕 Новая заявка #{order_id}\n\n{payload_summary(payload)}")
    except Exception:
        logger.exception("Не удалось отправить заявку в чат заказов")


# -----------------------------
# Internal API (for admin -> user DM)
# -----------------------------
async def internal_send_message(request: web.Request) -> web.Response:
    key = request.headers.get("X-Internal-Key", "")
    if key != getattr(settings, "internal_api_key", ""):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Bad JSON"}, status=400)

    user_id = data.get("user_id")
    text = (data.get("text") or "").strip()
    order_id = data.get("order_id")

    if not user_id or not text:
        return web.json_response({"error": "user_id and text are required"}, status=400)

    try:
        bot: Bot = request.app["bot"]
        msg = await bot.send_message(chat_id=int(user_id), text=text)
        try:
            database.add_order_message(int(order_id), "out", text, msg.message_id)
        except Exception:
            logger.exception("Не удалось сохранить исходящее сообщение (internal)")
        return web.json_response({"ok": True, "message_id": msg.message_id})
    except Exception as exc:
        logger.exception("Failed to send message")
        return web.json_response({"error": str(exc)}, status=500)


async def start_internal_server(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/sendMessage", internal_send_message)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(getattr(settings, "internal_port", 8081)))
    await site.start()
    return runner


async def main():
    database.init_db_if_needed()

    bot = Bot(token=settings.bot_token)
    runner = await start_internal_server(bot)

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
