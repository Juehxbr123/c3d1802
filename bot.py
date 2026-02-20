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
        await send_step_cb(
            cb,
            get_cfg("about_text", "Chel3D — 3D-печать, 3D-сканирование и разработка моделей."),
            kb(rows),
            photo_ref_for("photo_about"),
        )
        return

    if step == "result":
        text = (
            f"{get_cfg('text_result_prefix', 'Проверьте заявку:')}\n"
            f"{payload_summary(payload)}\n\n"
            f"{get_cfg('text_price_note', '💰 Уточнит менеджер после проверки.')}"
        )
        await send_step_cb(
            cb,
            text,
            kb(
                [
                    [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="submit")],
                    [InlineKeyboardButton(text="🔁 Новый расчет", callback_data="nav:menu")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu")],
                ]
            ),
        )
        return

    # fallback
    if cb.message:
        await show_main(cb.message, state)
    await cb.answer()


# -----------------------------
# Handlers
# -----------------------------
async def on_start(message: Message, state: FSMContext):
    await show_main(message, state)


async def on_menu(cb: CallbackQuery, state: FSMContext):
    _, branch = (cb.data or "").split(":", 1)
    await start_order(cb, state, branch)


async def on_nav(cb: CallbackQuery, state: FSMContext):
    _, cmd = (cb.data or "").split(":", 1)
    if cmd == "menu":
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return
    if cmd == "back":
        await go_back(cb, state)
        return
    await cb.answer()


async def on_set(cb: CallbackQuery, state: FSMContext):
    data = cb.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        await cb.answer()
        return

    _, key, value = parts
    sdata = await state.get_data()
    payload: dict[str, Any] = sdata.get("payload", {})
    payload[key] = value
    await state.update_data(payload=payload)
    await persist(state)

    # routing
    if key == "technology":
        await render_step(cb, state, "print_material")
        return

    if key == "material":
        if value in {"🤔 Другой материал", "🤔 Другая смола"}:
            await render_step(cb, state, "print_material_custom")
            return
        await render_step(cb, state, "attach_file")
        return

    if key == "scan_type":
        await render_step(cb, state, "describe_task")
        return

    if key == "idea_type":
        await render_step(cb, state, "describe_task")
        return

    if key == "file":
        await render_step(cb, state, "result")
        return

    await render_step(cb, state, "result")


async def on_about(cb: CallbackQuery, state: FSMContext):
    _, part = (cb.data or "").split(":", 1)
    texts = {
        "eq": ("about_equipment_text", "Оборудование"),
        "projects": ("about_projects_text", "Наши проекты"),
        "contacts": ("about_contacts_text", "Контакты"),
        "map": ("about_map_text", "На карте"),
    }
    key, title = texts.get(part, ("about_text", "О нас"))
    rows = [nav_row()]
    await send_step_cb(cb, get_cfg(key, title), kb([rows[0]]), photo_ref_for("photo_about"))


async def on_submit(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    payload: dict[str, Any] = data.get("payload", {})
    if not order_id:
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return

    summary = payload_summary(payload)
    try:
        database.finalize_order(int(order_id), summary)
    except Exception:
        logger.exception("Не удалось финализировать заявку")

    # send to group/chat
    chat_id = get_orders_chat_id()
    if chat_id:
        try:
            bot: Bot = cb.bot
            await bot.send_message(chat_id=chat_id, text=summary)
        except Exception:
            logger.exception("Не удалось отправить заявку в чат заказов")

    if cb.message:
        await send_step(
            cb.message,
            get_cfg("text_submit_ok", "✅ Заявка отправлена! Менеджер свяжется с вами."),
            kb([nav_row(False)]),
            photo_ref_for("photo_main_menu"),
        )
    await cb.answer()
    await state.clear()


async def on_text(message: Message, state: FSMContext):
    if message.from_user is None:
        return

    data = await state.get_data()
    waiting = data.get("waiting_text")
    if not waiting:
        # keep dialog messages as "dialog" order
        try:
            order_id = database.find_or_create_active_order(
                message.from_user.id, message.from_user.username, message.from_user.full_name
            )
            database.add_order_message(order_id, "in", message.text or "", message.message_id)
        except Exception:
            logger.exception("Не удалось сохранить входящее сообщение")
        return

    payload: dict[str, Any] = data.get("payload", {})
    if waiting == "material_custom":
        payload["material_custom"] = (message.text or "").strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)

        fake_cb = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data="noop")
        await render_step(fake_cb, state, "attach_file")
        return

    if waiting == "description":
        payload["description"] = (message.text or "").strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)

        fake_cb = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data="noop")
        if payload.get("branch") == "print":
            await render_step(fake_cb, state, "attach_file")
        else:
            await render_step(fake_cb, state, "result")
        return


async def on_document(message: Message, state: FSMContext):
    if message.from_user is None:
        return

    data = await state.get_data()
    waiting = data.get("waiting_text")
    if waiting != "file":
        return

    doc = message.document
    if not doc:
        return

    file_id = doc.file_id
    file_name = doc.file_name or "file"
    mime = doc.mime_type
    size = doc.file_size

    local_path = None
    try:
        bot: Bot = message.bot
        tg_file = await bot.get_file(file_id)
        dest = UPLOADS_DIR / f"{message.from_user.id}_{doc.file_unique_id}_{file_name}"
        await bot.download_file(tg_file.file_path, destination=dest)
        local_path = str(dest)
    except Exception:
        logger.exception("Не удалось скачать файл локально")

    try:
        order_id = int(data["order_id"])
        database.add_order_file(order_id, file_id, file_name, mime, size, message.message_id, local_path)
    except Exception:
        logger.exception("Не удалось сохранить файл в БД")

    payload: dict[str, Any] = data.get("payload", {})
    payload["file"] = file_name
    await state.update_data(payload=payload, waiting_text=None)
    await persist(state)

    fake_cb = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data="noop")
    await render_step(fake_cb, state, "result")


# -----------------------------
# Internal API (backend -> bot)
# -----------------------------
async def internal_send_message(request: web.Request) -> web.Response:
    key = request.headers.get("X-Internal-Key", "")
    if key != getattr(settings, "internal_api_key", ""):
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    user_id = body.get("user_id")
    text = (body.get("text") or "").strip()
    order_id = body.get("order_id")

    if not user_id or not text:
        return web.json_response({"error": "user_id and text are required"}, status=400)

    bot: Bot = request.app["bot"]
    try:
        sent = await bot.send_message(chat_id=user_id, text=text)
    except Exception as exc:
        logger.exception("Не удалось отправить сообщение пользователю")
        return web.json_response({"error": str(exc)}, status=400)

    try:
        if order_id:
            database.add_order_message(int(order_id), "out", text, getattr(sent, "message_id", None))
        else:
            oid = database.find_or_create_active_order(user_id, None, None)
            database.add_order_message(int(oid), "out", text, getattr(sent, "message_id", None))
    except Exception:
        logger.exception("Не удалось сохранить исходящее сообщение в БД")

    return web.json_response({"ok": True, "message_id": getattr(sent, "message_id", None)})


async def start_internal_api(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/sendMessage", internal_send_message)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=int(getattr(settings, "internal_api_port", 8081)))
    await site.start()
    logger.info("Internal API started on 0.0.0.0:%s", getattr(settings, "internal_api_port", 8081))
    return runner


async def main() -> None:
    database.init_db_if_needed()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(on_start, CommandStart())
    dp.callback_query.register(on_menu, F.data.startswith("menu:"))
    dp.callback_query.register(on_nav, F.data.startswith("nav:"))
    dp.callback_query.register(on_set, F.data.startswith("set:"))
    dp.callback_query.register(on_about, F.data.startswith("about:"))
    dp.callback_query.register(on_submit, F.data == "submit")

    dp.message.register(on_document, F.content_type == ContentType.DOCUMENT)
    dp.message.register(on_text, F.content_type == ContentType.TEXT)

    runner = await start_internal_api(bot)
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())