import asyncio
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
# Small helpers
# -----------------------------
def user_full_name(user) -> str:
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    name = (first + " " + last).strip()
    return name or getattr(user, "full_name", "") or "Без имени"


def user_username(user) -> str | None:
    return getattr(user, "username", None)


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


def normalize_chat_id(value: str) -> int | str:
    cleaned = (value or "").strip().replace(" ", "")
    if cleaned.startswith("-") and cleaned[1:].isdigit():
        return int(cleaned)
    if cleaned.isdigit():
        return int(cleaned)
    return cleaned


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
        rows.append([InlineKeyboardButton(text=get_cfg("btn_menu_print", "📐 Рассчитать печать"), callback_data="menu:print")])
    if cfg_bool("enabled_menu_scan", True):
        rows.append([InlineKeyboardButton(text=get_cfg("btn_menu_scan", "📡 3D-сканирование"), callback_data="menu:scan")])
    if cfg_bool("enabled_menu_idea", True):
        rows.append([InlineKeyboardButton(text=get_cfg("btn_menu_idea", "❓ Нет модели / Хочу придумать"), callback_data="menu:idea")])
    if cfg_bool("enabled_menu_about", True):
        rows.append([InlineKeyboardButton(text=get_cfg("btn_menu_about", "ℹ️ О нас"), callback_data="menu:about")])
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
            ("btn_mat_petg", "PET-G"),
            ("btn_mat_pla", "PLA"),
            ("btn_mat_petg_carbon", "PET-G Carbon"),
            ("btn_mat_tpu", "TPU"),
            ("btn_mat_nylon", "Нейлон"),
            ("btn_mat_other", "🤔 Другой материал"),
        ]
    elif tech == "Фотополимер":
        items = [
            ("btn_resin_standard", "Стандартная"),
            ("btn_resin_abs", "ABS-Like"),
            ("btn_resin_tpu", "TPU-Like"),
            ("btn_resin_nylon", "Нейлон-Like"),
            ("btn_resin_other", "🤔 Другая смола"),
        ]
    else:
        items = [("", "Пропустить")]

    rows = []
    for key, label in items:
        txt = get_cfg(key, label) if key else label
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"set:material:{label}")])
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
) -> Message:
    ref = photo_ref or getattr(settings, "placeholder_photo_path", "")
    if ref:
        try:
            if ref.startswith("http://") or ref.startswith("https://"):
                return await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)

            p = Path(ref)
            if p.exists() and p.is_file():
                return await message.answer_photo(photo=FSInputFile(str(p)), caption=text, reply_markup=keyboard)

            # might be telegram file_id
            return await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
        except Exception:
            logger.exception("Не удалось отправить фото — отправляю текстом")

    return await message.answer(text, reply_markup=keyboard)


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


def _push_history(state_data: dict[str, Any]) -> list[str]:
    history: list[str] = state_data.get("history", [])
    current = state_data.get("current_step")
    if current:
        history.append(current)
    return history


# -----------------------------
# Flow rendering
# -----------------------------
async def show_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_step(
        message,
        get_cfg("welcome_menu_msg", "Привет! 👋 Я бот Chel3D.\nВыберите, что вам нужно — и я соберу заявку по шагам."),
        menu_kb(),
        photo_ref_for("photo_main_menu"),
    )


async def start_order(cb: CallbackQuery, state: FSMContext, branch: str) -> None:
    order_id = database.create_order(cb.from_user.id, user_username(cb.from_user), user_full_name(cb.from_user), branch)
    await state.set_state(Form.step)
    await state.update_data(
        order_id=order_id,
        payload={"branch": branch},
        history=[],
        current_step=None,
        waiting_text=None,
    )


async def render_step(cb: CallbackQuery, state: FSMContext, step: str, from_back: bool = False) -> None:
    if not from_back:
        data = await state.get_data()
        await state.update_data(history=_push_history(data))
    await state.update_data(current_step=step, waiting_text=None)

    data = await state.get_data()
    payload: dict[str, Any] = data.get("payload", {})

    if step == "print_tech":
        rows = []
        if cfg_bool("enabled_print_fdm", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_print_fdm", "🧵 FDM (Пластик)"), callback_data="set:technology:FDM")])
        if cfg_bool("enabled_print_resin", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_print_resin", "💧 Фотополимер"), callback_data="set:technology:Фотополимер")])
        if cfg_bool("enabled_print_unknown", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_print_unknown", "🤷 Не знаю"), callback_data="set:technology:Не знаю")])
        rows.append(nav_row(False))
        await send_step_cb(cb, get_cfg("text_print_tech", "🖨 Выберите технологию печати:"), kb(rows), photo_ref_for("photo_print"))
        return

    if step == "print_material":
        await send_step_cb(cb, get_cfg("text_select_material", "Выберите материал:"), step_keyboard_for_print(payload), photo_ref_for("photo_print"))
        return

    if step == "print_material_custom":
        await state.update_data(waiting_text="material_custom")
        await send_step_cb(cb, get_cfg("text_describe_material", "Опишите материал/смолу свободным текстом:"), kb([nav_row()]), photo_ref_for("photo_print"))
        return

    if step == "attach_file":
        rows = [
            [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
            nav_row(),
        ]
        await send_step_cb(cb, get_cfg("text_attach_file", "Прикрепите STL/3MF/OBJ или фото. Или нажмите кнопку ниже:"), kb(rows))
        return

    if step == "description":
        await state.update_data(waiting_text="description")
        await send_step_cb(cb, get_cfg("text_describe_task", "Опишите задачу, размеры, сроки и важные детали:"), kb([nav_row()]))
        return

    if step == "scan_type":
        rows = []
        if cfg_bool("enabled_scan_human", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_scan_human", "🧑 Человек"), callback_data="set:scan_type:Человек")])
        if cfg_bool("enabled_scan_object", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_scan_object", "📦 Предмет"), callback_data="set:scan_type:Предмет")])
        if cfg_bool("enabled_scan_industrial", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_scan_industrial", "🏭 Промышленный объект"), callback_data="set:scan_type:Промышленный объект")])
        if cfg_bool("enabled_scan_other", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_scan_other", "🤔 Другое"), callback_data="set:scan_type:Другое")])
        rows.append(nav_row(False))
        await send_step_cb(cb, get_cfg("text_scan_type", "📡 Выберите тип объекта для 3D-сканирования:"), kb(rows), photo_ref_for("photo_scan"))
        return

    if step == "idea_type":
        rows = []
        if cfg_bool("enabled_idea_photo", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_idea_photo", "✏️ По фото/эскизу"), callback_data="set:idea_type:По фото/эскизу")])
        if cfg_bool("enabled_idea_award", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_idea_award", "🏆 Сувенир/Кубок/Медаль"), callback_data="set:idea_type:Сувенир/Кубок/Медаль")])
        if cfg_bool("enabled_idea_master", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_idea_master", "📏 Мастер-модель"), callback_data="set:idea_type:Мастер-модель")])
        if cfg_bool("enabled_idea_sign", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_idea_sign", "🎨 Вывески"), callback_data="set:idea_type:Вывески")])
        if cfg_bool("enabled_idea_other", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_idea_other", "🤔 Другое"), callback_data="set:idea_type:Другое")])
        rows.append(nav_row(False))
        await send_step_cb(cb, get_cfg("text_idea_type", "✏️ Выберите направление:"), kb(rows), photo_ref_for("photo_idea"))
        return

    if step == "about":
        rows = []
        if cfg_bool("enabled_about_equipment", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_about_equipment", "🏭 Оборудование"), callback_data="about:eq")])
        if cfg_bool("enabled_about_projects", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_about_projects", "🖼 Наши проекты"), callback_data="about:projects")])
        if cfg_bool("enabled_about_contacts", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_about_contacts", "📞 Контакты"), callback_data="about:contacts")])
        if cfg_bool("enabled_about_map", True):
            rows.append([InlineKeyboardButton(text=get_cfg("btn_about_map", "📍 На карте"), callback_data="about:map")])
        rows.append(nav_row(False))
        await send_step_cb(cb, get_cfg("about_text", "🏢 Chel3D — 3D-печать, моделирование и сканирование.\nВыберите раздел:"), kb(rows), photo_ref_for("photo_about"))
        return

    # fallback
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


# -----------------------------
# Sending order to manager chat
# -----------------------------
async def send_order_to_orders_chat(bot: Bot, order_id: int, summary: str) -> None:
    raw_chat = get_orders_chat_id()
    if not raw_chat:
        return
    chat_id = normalize_chat_id(raw_chat)
    try:
        await bot.send_message(chat_id=chat_id, text=f"🆕 Заявка №{order_id}\n\n{summary}")
    except Exception:
        logger.exception("Не удалось отправить заявку в чат заказов")


async def submit_order(bot: Bot, message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data.get("order_id", 0) or 0)
    payload: dict[str, Any] = data.get("payload", {})
    summary = payload_summary(payload)

    if order_id:
        database.finalize_order(order_id, summary)

    await send_order_to_orders_chat(bot, order_id, summary)

    ok_text = get_cfg("text_submit_ok", "✅ Заявка отправлена! Менеджер скоро напишет вам в этот чат.")
    await send_step(message, ok_text, kb([nav_row(include_back=False)]))
    await state.clear()


# -----------------------------
# Handlers
# -----------------------------
async def on_start(message: Message, state: FSMContext) -> None:
    await show_main(message, state)


async def on_menu(cb: CallbackQuery, state: FSMContext) -> None:
    branch = (cb.data or "").split(":", 1)[1] if cb.data else ""
    if branch == "about":
        await render_step(cb, state, "about")
        return

    await start_order(cb, state, branch)
    if branch == "print":
        await render_step(cb, state, "print_tech")
    elif branch == "scan":
        await render_step(cb, state, "scan_type")
    elif branch == "idea":
        await render_step(cb, state, "idea_type")
    else:
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()


async def on_about_item(cb: CallbackQuery, state: FSMContext) -> None:
    key = (cb.data or "").split(":", 1)[1] if cb.data else ""
    mapping = {
        "eq": ("about_equipment_text", "photo_about_equipment", "🏭 Наше оборудование"),
        "projects": ("about_projects_text", "photo_about_projects", "🖼 Наши проекты"),
        "contacts": ("about_contacts_text", "photo_about_contacts", "📞 Контакты"),
        "map": ("about_map_text", "photo_about_map", "📍 Мы на карте"),
    }
    text_key, photo_key, default_text = mapping.get(key, ("about_text", "photo_about", "О нас"))
    await send_step_cb(cb, get_cfg(text_key, default_text), kb([nav_row()]), photo_ref_for(photo_key))


async def refresh_order_contact(state: FSMContext, user) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        return
    database.update_order_contact(int(order_id), user_username(user), user_full_name(user))


async def on_set(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    try:
        _, key, value = (cb.data or "").split(":", 2)
    except Exception:
        await cb.answer()
        return

    await refresh_order_contact(state, cb.from_user)

    data = await state.get_data()
    payload: dict[str, Any] = data.get("payload", {})
    payload[key] = value
    await state.update_data(payload=payload)
    await persist(state)

    if key == "technology":
        await render_step(cb, state, "print_material")
        return

    if key == "material":
        if value.startswith("🤔"):
            await render_step(cb, state, "print_material_custom")
            return
        await render_step(cb, state, "attach_file")
        return

    if key == "scan_type":
        await render_step(cb, state, "description")
        return

    if key == "idea_type":
        await render_step(cb, state, "description")
        return

    if key == "file":
        await render_step(cb, state, "description")
        return

    await cb.answer("Сохранено")


async def on_nav(cb: CallbackQuery, state: FSMContext) -> None:
    action = (cb.data or "").split(":", 1)[1] if cb.data else ""
    if action == "menu":
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return
    if action == "back":
        await go_back(cb, state)
        return
    await cb.answer()


async def on_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await refresh_order_contact(state, message.from_user)

    data = await state.get_data()
    waiting = data.get("waiting_text")

    # If we are not in "order flow" waiting for input -> treat as dialog message
    if not waiting:
        order_id = database.find_or_create_active_order(
            message.from_user.id,
            user_username(message.from_user),
            user_full_name(message.from_user),
        )
        database.add_order_message(order_id, "in", message.text or "", telegram_message_id=message.message_id)
        await send_step(message, "Сообщение получено. Менеджер ответит в этом чате.")
        return

    payload: dict[str, Any] = data.get("payload", {})

    if waiting == "material_custom":
        payload["material_custom"] = (message.text or "").strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        # next step
        await send_step(message, "Принято ✅")
        # render next using synthetic callback wrapper is hard; just ask attach file
        rows = [
            [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
            nav_row(),
        ]
        await send_step(message, get_cfg("text_attach_file", "Прикрепите STL/3MF/OBJ или фото. Или нажмите кнопку ниже:"), kb(rows))
        await state.update_data(current_step="attach_file")
        return

    if waiting == "description":
        payload["description"] = (message.text or "").strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        await submit_order(bot, message, state)
        return

    # fallback
    await send_step(message, "Принято ✅")


async def on_file(message: Message, state: FSMContext, bot: Bot) -> None:
    await refresh_order_contact(state, message.from_user)

    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await send_step(message, "Сначала создайте заявку через главное меню: /start")
        return

    tg_file_id = None
    original_name = None
    content_type = None

    if message.document:
        tg_file_id = message.document.file_id
        original_name = message.document.file_name
        content_type = message.document.mime_type
    elif message.photo:
        tg_file_id = message.photo[-1].file_id
        original_name = "photo.jpg"
        content_type = "image/jpeg"

    if not tg_file_id:
        await send_step(message, "Не удалось распознать файл. Попробуйте отправить документом или фото.")
        return

    database.add_order_file(int(order_id), tg_file_id, original_name=original_name, content_type=content_type)

    payload: dict[str, Any] = data.get("payload", {})
    payload["file"] = original_name or "Файл"
    await state.update_data(payload=payload)
    await persist(state)

    # Go next: description
    await send_step(message, "Файл прикреплён ✅")
    await state.update_data(current_step="description", waiting_text="description")
    await send_step(message, get_cfg("text_describe_task", "Опишите задачу, размеры, сроки и важные детали:"), kb([nav_row()]))


# -----------------------------
# Internal API (backend -> bot)
# -----------------------------
async def internal_send_message(request: web.Request) -> web.Response:
    if request.headers.get("X-Internal-Key") != getattr(settings, "internal_api_key", ""):
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)

    user_id = payload.get("user_id")
    text = (payload.get("text") or "").strip()
    order_id = payload.get("order_id")

    if not user_id or not text:
        return web.json_response({"error": "user_id and text required"}, status=400)

    bot: Bot = request.app["bot"]
    try:
        sent = await bot.send_message(chat_id=int(user_id), text=text)
        if order_id:
            try:
                database.add_order_message(int(order_id), "out", text, telegram_message_id=sent.message_id)
            except Exception:
                logger.exception("Не удалось сохранить исходящее сообщение в БД")
        return web.json_response({"ok": True})
    except Exception as exc:
        logger.exception("Telegram sendMessage failed")
        return web.json_response({"error": str(exc)}, status=400)


async def start_internal_server(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/sendMessage", internal_send_message)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    logger.info("Internal API started on 0.0.0.0:8081")
    return runner


# -----------------------------
# Main
# -----------------------------
async def main() -> None:
    database.init_db_if_needed()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(on_start, CommandStart())
    dp.callback_query.register(on_menu, F.data.startswith("menu:"))
    dp.callback_query.register(on_about_item, F.data.startswith("about:"))
    dp.callback_query.register(on_nav, F.data.startswith("nav:"))
    dp.callback_query.register(on_set, F.data.startswith("set:"))

    dp.message.register(on_file, F.content_type.in_({ContentType.DOCUMENT, ContentType.PHOTO}))
    dp.message.register(on_text, F.content_type == ContentType.TEXT)

    runner = await start_internal_server(bot)
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await runner.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
