import asyncio
import html
import logging
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chel3d_bot")

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)


# -----------------------------
# helpers
# -----------------------------

def bot_cfg() -> dict[str, str]:
    try:
        return database.get_bot_config()
    except Exception:
        return {}


def get_cfg(key: str, default: str = "") -> str:
    val = bot_cfg().get(key, "")
    if val is None or str(val).strip() == "":
        return default
    return str(val)


def cfg_bool(key: str, default: bool = True) -> bool:
    raw = bot_cfg().get(key, "")
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def user_full_name(user) -> str:
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    name = (first + " " + last).strip()
    return name or getattr(user, "full_name", "") or "Без имени"


def user_username(user) -> str | None:
    return getattr(user, "username", None)


def photo_ref_for(key: str) -> str:
    cfg = bot_cfg()
    return (
        cfg.get(key, "")
        or cfg.get("placeholder_photo_path", "")
        or getattr(settings, "placeholder_photo_path", "")
        or ""
    )


def get_orders_chat_id() -> str:
    return get_cfg("orders_chat_id", getattr(settings, "orders_chat_id", ""))


def normalize_chat_id(value: str) -> int | str:
    cleaned = (value or "").strip().replace(" ", "")
    if cleaned.startswith("-") and cleaned[1:].isdigit():
        return int(cleaned)
    if cleaned.isdigit():
        return int(cleaned)
    return cleaned


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav_row(include_back: bool = True) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if include_back:
        row.append(InlineKeyboardButton(text="🔙 Назад", callback_data="nav:back"))
    row.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:menu"))
    return row


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


async def _send_with_optional_photo(message: Message, text: str, keyboard: InlineKeyboardMarkup | None, photo_ref: str | None):
    ref = (photo_ref or "").strip()

    if ref:
        try:
            if ref.startswith("http://") or ref.startswith("https://"):
                return await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
            p = Path(ref)
            if p.exists() and p.is_file():
                return await message.answer_photo(photo=FSInputFile(str(p)), caption=text, reply_markup=keyboard)
            # может быть file_id Telegram
            return await message.answer_photo(photo=ref, caption=text, reply_markup=keyboard)
        except Exception:
            logger.exception("Не удалось отправить фото шага")

    return await message.answer(text, reply_markup=keyboard)


async def send_step(message: Message, text: str, keyboard: InlineKeyboardMarkup | None = None, photo_ref: str | None = None) -> None:
    await _send_with_optional_photo(message, text, keyboard, photo_ref)


async def send_step_cb(cb: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None, photo_ref: str | None = None) -> None:
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
        "branch": "Раздел",
        "technology": "Технология",
        "material": "Материал",
        "material_custom": "Материал (свой)",
        "scan_type": "Тип сканирования",
        "idea_type": "Тип задачи",
        "file": "Файл",
        "description": "Комментарий",
    }

    lines: list[str] = []
    br = payload.get("branch")
    if br:
        lines.append(f"• {field_map['branch']}: {branch_map.get(str(br), str(br))}")

    for k, title in field_map.items():
        if k == "branch":
            continue
        v = payload.get(k)
        if v is None or str(v).strip() == "":
            continue
        lines.append(f"• {title}: {v}")

    return "\n".join(lines) if lines else "(пока пусто)"


# -----------------------------
# FSM
# -----------------------------

class Form(StatesGroup):
    step = State()


async def persist(state: FSMContext) -> None:
    st = await state.get_data()
    order_id = int(st.get("order_id", 0) or 0)
    payload: dict[str, Any] = st.get("payload", {})
    if order_id:
        database.update_order_payload(order_id, payload, summary=None)


async def refresh_order_contact(state: FSMContext, user) -> None:
    st = await state.get_data()
    order_id = int(st.get("order_id", 0) or 0)
    if order_id:
        database.update_order_contact(order_id, user_username(user), user_full_name(user))


async def show_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_step(
        message,
        get_cfg(
            "welcome_menu_msg",
            "Привет! Я бот Chel3D. Выберите нужный раздел:",
        ),
        menu_kb(),
        photo_ref_for("photo_main_menu"),
    )


async def start_order(cb: CallbackQuery, state: FSMContext, branch: str) -> None:
    user = cb.from_user
    order_id = database.create_order(user.id, user_username(user), user_full_name(user), branch)
    payload: dict[str, Any] = {"branch": branch}
    await state.update_data(order_id=order_id, payload=payload, history=[], waiting_text=None)
    await persist(state)


def tech_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if cfg_bool("enabled_print_fdm", True):
        rows.append([InlineKeyboardButton(text=get_cfg("btn_print_fdm", "FDM"), callback_data="set:technology:FDM")])
    if cfg_bool("enabled_print_resin", True):
        rows.append([InlineKeyboardButton(text=get_cfg("btn_print_resin", "Фотополимер"), callback_data="set:technology:Фотополимер")])
    if cfg_bool("enabled_print_unknown", True):
        rows.append([InlineKeyboardButton(text=get_cfg("btn_print_unknown", "Не знаю"), callback_data="set:technology:Не знаю")])
    rows.append(nav_row())
    return kb(rows)


def material_kb(tech: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if (tech or "").lower().startswith("фото"):
        rows.extend(
            [
                [InlineKeyboardButton(text=get_cfg("btn_resin_standard", "Стандартная"), callback_data="set:material:Смола: стандартная")],
                [InlineKeyboardButton(text=get_cfg("btn_resin_abs", "ABS-Like"), callback_data="set:material:Смола: ABS-Like")],
                [InlineKeyboardButton(text=get_cfg("btn_resin_tpu", "TPU-Like"), callback_data="set:material:Смола: TPU-Like")],
                [InlineKeyboardButton(text=get_cfg("btn_resin_nylon", "Nylon-Like"), callback_data="set:material:Смола: Nylon-Like")],
                [InlineKeyboardButton(text=get_cfg("btn_resin_other", "Другая"), callback_data="set:material:🤔 Другая смола")],
            ]
        )
    else:
        rows.extend(
            [
                [InlineKeyboardButton(text=get_cfg("btn_mat_petg", "PET-G"), callback_data="set:material:PET-G")],
                [InlineKeyboardButton(text=get_cfg("btn_mat_pla", "PLA"), callback_data="set:material:PLA")],
                [InlineKeyboardButton(text=get_cfg("btn_mat_petg_carbon", "PET-G Carbon"), callback_data="set:material:PET-G Carbon")],
                [InlineKeyboardButton(text=get_cfg("btn_mat_tpu", "TPU"), callback_data="set:material:TPU")],
                [InlineKeyboardButton(text=get_cfg("btn_mat_nylon", "Нейлон"), callback_data="set:material:Нейлон")],
                [InlineKeyboardButton(text=get_cfg("btn_mat_other", "Другой"), callback_data="set:material:🤔 Другой материал")],
            ]
        )

    rows.append(nav_row())
    return kb(rows)


async def send_result(message: Message, state: FSMContext) -> None:
    st = await state.get_data()
    payload: dict[str, Any] = st.get("payload", {})
    text = (
        f"{get_cfg('text_result_prefix', 'Проверьте заявку:')}\n"
        f"{payload_summary(payload)}\n\n"
        f"{get_cfg('text_price_note', '💰 Стоимость уточнит менеджер после проверки.') }"
    )

    await send_step(
        message,
        text,
        kb(
            [
                [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="submit:order")],
                [InlineKeyboardButton(text="🔁 Новый расчёт", callback_data="nav:menu")],
            ]
        ),
    )


async def send_order_to_orders_chat(bot: Bot, order_id: int, summary: str, user_id: int, username: str | None, full_name: str | None) -> None:
    raw_chat = get_orders_chat_id()
    if not raw_chat:
        return
    chat_id = normalize_chat_id(raw_chat)

    username_text = f"@{html.escape(username)}" if username else "не указан"
    customer_link = f"<a href=\"tg://user?id={user_id}\">{html.escape(full_name or 'Без имени')}</a>"

    text = (
        f"🆕 Заявка №{order_id}\n\n"
        f"👤 Заказчик: {customer_link}\n"
        f"🔗 Username: {username_text}\n"
        f"🆔 Telegram ID: {user_id}\n\n"
        f"{html.escape(summary)}"
    )

    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить заявку в чат заказов")


async def submit_order(bot: Bot, message: Message, state: FSMContext) -> None:
    st = await state.get_data()
    order_id = int(st.get("order_id", 0) or 0)
    payload: dict[str, Any] = st.get("payload", {})
    summary = payload_summary(payload)

    if order_id:
        database.finalize_order(order_id, summary)

    await send_order_to_orders_chat(bot, order_id, summary, message.from_user.id, user_username(message.from_user), user_full_name(message.from_user))

    ok_text = get_cfg("text_submit_ok", "✅ Заявка отправлена! Менеджер скоро напишет вам в этот чат.")
    await send_step(message, f"{ok_text}\n\n{summary}", kb([nav_row(include_back=False)]))
    await state.clear()


# -----------------------------
# Handlers
# -----------------------------

async def on_start(message: Message, state: FSMContext) -> None:
    await show_main(message, state)


async def on_menu(cb: CallbackQuery, state: FSMContext) -> None:
    branch = (cb.data or "").split(":", 1)[1] if cb.data else ""

    if branch == "about":
        await send_step_cb(
            cb,
            get_cfg("about_text", "🏢 Chel3D — 3D-печать, моделирование и сканирование.\nВыберите раздел:"),
            kb(
                [
                    [InlineKeyboardButton(text=get_cfg("btn_about_equipment", "🏭 Оборудование"), callback_data="about:eq")],
                    [InlineKeyboardButton(text=get_cfg("btn_about_projects", "🖼 Наши проекты"), callback_data="about:projects")],
                    [InlineKeyboardButton(text=get_cfg("btn_about_contacts", "📞 Контакты"), callback_data="about:contacts")],
                    [InlineKeyboardButton(text=get_cfg("btn_about_map", "📍 На карте"), callback_data="about:map")],
                    nav_row(False),
                ]
            ),
            photo_ref_for("photo_about"),
        )
        return

    if branch not in {"print", "scan", "idea"}:
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return

    await start_order(cb, state, branch)

    if branch == "print":
        await send_step_cb(cb, get_cfg("text_print_tech", "📐 Выберите технологию печати:"), tech_kb(), photo_ref_for("photo_print"))
        return

    if branch == "scan":
        rows = [
            [InlineKeyboardButton(text=get_cfg("btn_scan_human", "Человек"), callback_data="set:scan_type:Человек")],
            [InlineKeyboardButton(text=get_cfg("btn_scan_object", "Предмет"), callback_data="set:scan_type:Предмет")],
            [InlineKeyboardButton(text=get_cfg("btn_scan_industrial", "Промышленный объект"), callback_data="set:scan_type:Промышленный объект")],
            [InlineKeyboardButton(text=get_cfg("btn_scan_other", "Другое"), callback_data="set:scan_type:Другое")],
            nav_row(),
        ]
        await send_step_cb(cb, get_cfg("text_scan_type", "📡 Выберите тип сканирования:"), kb(rows), photo_ref_for("photo_scan"))
        return

    if branch == "idea":
        rows = [
            [InlineKeyboardButton(text=get_cfg("btn_idea_photo", "По фото/эскизу"), callback_data="set:idea_type:По фото/эскизу")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_award", "Сувенир/награда"), callback_data="set:idea_type:Сувенир/награда")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_master", "Мастер-модель"), callback_data="set:idea_type:Мастер-модель")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_sign", "Вывески"), callback_data="set:idea_type:Вывески")],
            [InlineKeyboardButton(text=get_cfg("btn_idea_other", "Другое"), callback_data="set:idea_type:Другое")],
            nav_row(),
        ]
        await send_step_cb(cb, get_cfg("text_idea_type", "✏️ Выберите направление:"), kb(rows), photo_ref_for("photo_idea"))
        return


async def on_nav(cb: CallbackQuery, state: FSMContext) -> None:
    action = (cb.data or "").split(":", 1)[1]
    if action == "menu":
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return

    if action == "back":
        # для простоты вернём в главное меню
        if cb.message:
            await show_main(cb.message, state)
        await cb.answer()
        return

    await cb.answer()


async def on_about(cb: CallbackQuery, state: FSMContext) -> None:
    key = (cb.data or "").split(":", 1)[1]
    mapping = {
        "eq": ("about_equipment_text", "photo_about_equipment"),
        "projects": ("about_projects_text", "photo_about_projects"),
        "contacts": ("about_contacts_text", "photo_about_contacts"),
        "map": ("about_map_text", "photo_about_map"),
    }
    cfg_key, photo_key = mapping.get(key, ("about_text", "photo_about"))
    await send_step_cb(cb, get_cfg(cfg_key, "ℹ️ О нас"), kb([nav_row()]), photo_ref_for(photo_key))


async def on_set(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    parts = (cb.data or "").split(":", 2)
    if len(parts) < 3:
        await cb.answer()
        return

    _, field, value = parts

    await refresh_order_contact(state, cb.from_user)

    st = await state.get_data()
    payload: dict[str, Any] = st.get("payload", {})
    payload[field] = value
    await state.update_data(payload=payload)
    await persist(state)

    # маршрутизация шагов
    if field == "technology":
        await send_step_cb(cb, get_cfg("text_select_material", "Выберите материал:"), material_kb(value), photo_ref_for("photo_print"))
        return

    if field == "material":
        if "🤔" in value:
            await state.update_data(waiting_text="material_custom")
            await send_step_cb(cb, get_cfg("text_describe_material", "Опишите материал/смолу свободным текстом:"), kb([nav_row()]), photo_ref_for("photo_print"))
            return

        # дальше вложение
        await send_step_cb(
            cb,
            get_cfg("text_attach_file", "Прикрепите STL/3MF/OBJ документ или фото, либо нажмите ❌ У меня нет файла"),
            kb(
                [
                    [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
                    nav_row(),
                ]
            ),
            photo_ref_for("photo_print"),
        )
        return

    if field in {"scan_type", "idea_type"}:
        await state.update_data(waiting_text="description")
        await send_step_cb(cb, get_cfg("text_describe_task", "Опишите задачу / детали (свободным текстом):"), kb([nav_row()]))
        return

    if field == "file":
        await state.update_data(waiting_text="description")
        await send_step_cb(cb, get_cfg("text_describe_task", "Опишите задачу / детали (свободным текстом):"), kb([nav_row()]))
        return

    await cb.answer()


async def on_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await refresh_order_contact(state, message.from_user)
    st = await state.get_data()
    waiting = st.get("waiting_text")

    # если пользователь просто пишет менеджеру вне формы
    if not waiting:
        order_id = database.find_or_create_active_order(message.from_user.id, user_username(message.from_user), user_full_name(message.from_user))
        database.add_order_message(order_id, "in", message.text or "")
        await send_step(message, "Сообщение получено. Менеджер ответит в этом чате.")
        return

    payload: dict[str, Any] = st.get("payload", {})

    if waiting == "material_custom":
        payload["material_custom"] = (message.text or "").strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)

        await send_step(
            message,
            get_cfg("text_attach_file", "Прикрепите STL/3MF/OBJ документ или фото, либо нажмите ❌ У меня нет файла"),
            kb(
                [
                    [InlineKeyboardButton(text="❌ У меня нет файла", callback_data="set:file:нет")],
                    nav_row(),
                ]
            ),
            photo_ref_for("photo_print"),
        )
        return

    if waiting == "description":
        payload["description"] = (message.text or "").strip()
        await state.update_data(payload=payload, waiting_text=None)
        await persist(state)
        database.add_order_message(int(st.get("order_id", 0) or 0), "in", message.text or "")
        await send_result(message, state)
        return


async def on_file(message: Message, state: FSMContext, bot: Bot) -> None:
    await refresh_order_contact(state, message.from_user)
    st = await state.get_data()
    order_id = int(st.get("order_id", 0) or 0)
    if not order_id:
        await send_step(message, "Сначала создайте заявку через главное меню.")
        return

    file_id = None
    file_name = None
    mime = None
    size = None

    if message.document:
        doc = message.document
        file_id = doc.file_id
        file_name = doc.file_name
        mime = doc.mime_type
        size = doc.file_size
    elif message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_name = f"photo_{photo.file_unique_id}.jpg"
        mime = "image/jpeg"
        size = photo.file_size

    if not file_id:
        return

    local_path = None
    try:
        tg_file = await bot.get_file(file_id)
        local_path = str(UPLOADS_DIR / f"{message.from_user.id}_{file_name or 'file'}")
        await bot.download_file(tg_file.file_path, destination=local_path)
    except Exception:
        logger.exception("Не удалось скачать вложение локально")

    database.add_order_file(order_id, file_id, original_name=file_name, mime_type=mime, file_size=size, telegram_message_id=message.message_id, local_path=local_path)

    payload: dict[str, Any] = st.get("payload", {})
    payload["file"] = file_name or "файл"
    await state.update_data(payload=payload, waiting_text="description")
    await persist(state)

    await send_step(message, "Файл получен ✅\nТеперь опишите задачу/детали (свободным текстом):", kb([nav_row()]))


async def on_submit(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not cb.message:
        await cb.answer()
        return

    await refresh_order_contact(state, cb.from_user)
    await submit_order(bot, cb.message, state)
    await cb.answer()


# -----------------------------
# Internal API (backend -> bot)
# -----------------------------

async def internal_send_message(request: web.Request):
    if getattr(settings, "internal_api_key", "") and request.headers.get("X-Internal-Key") != settings.internal_api_key:
        return web.json_response({"ok": False, "detail": "unauthorized"}, status=401)

    data = await request.json()
    user_id = int(data.get("user_id"))
    text = (data.get("text") or "").strip()
    order_id = int(data.get("order_id") or 0)

    if not text:
        return web.json_response({"ok": False, "detail": "Текст сообщения пустой"}, status=400)

    bot: Bot = request.app["bot"]

    try:
        sent = await bot.send_message(chat_id=user_id, text=text)
        if order_id:
            database.add_order_message(order_id, "out", text, telegram_message_id=sent.message_id)
        return web.json_response({"ok": True, "message_id": sent.message_id})
    except Exception:
        logger.exception("Не удалось отправить сообщение в Telegram")
        return web.json_response({"ok": False, "detail": "Не удалось отправить сообщение в Telegram"}, status=400)


async def start_internal_api(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/sendMessage", internal_send_message)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host="0.0.0.0", port=8081)
    await site.start()
    logger.info("Internal API started on 0.0.0.0:8081")
    return runner


async def main() -> None:
    database.init_db_if_needed()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(on_start, CommandStart())
    dp.callback_query.register(on_menu, F.data.startswith("menu:"))
    dp.callback_query.register(on_nav, F.data.startswith("nav:"))
    dp.callback_query.register(on_about, F.data.startswith("about:"))
    dp.callback_query.register(on_set, F.data.startswith("set:"))
    dp.callback_query.register(on_submit, F.data == "submit:order")

    dp.message.register(on_file, F.document | F.photo)
    dp.message.register(on_text, F.text)

    runner = await start_internal_api(bot)

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
