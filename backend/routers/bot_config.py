import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import database
from routers.auth import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)

TEXT_KEYS = [
    # Общие
    "welcome_menu_msg",
    "text_submit_ok",
    "text_submit_fail",
    "text_result_prefix",
    "text_price_note",
    # Главное меню
    "btn_menu_print",
    "btn_menu_scan",
    "btn_menu_idea",
    "btn_menu_about",
    # Печать
    "text_print_tech",
    "btn_print_fdm",
    "btn_print_resin",
    "btn_print_unknown",
    "text_select_material",
    "btn_mat_petg",
    "btn_mat_pla",
    "btn_mat_petg_carbon",
    "btn_mat_tpu",
    "btn_mat_nylon",
    "btn_mat_other",
    "btn_resin_standard",
    "btn_resin_abs",
    "btn_resin_tpu",
    "btn_resin_nylon",
    "btn_resin_other",
    "text_describe_material",
    "text_attach_file",
    # Скан
    "text_scan_type",
    "btn_scan_human",
    "btn_scan_object",
    "btn_scan_industrial",
    "btn_scan_other",
    # Идея
    "text_idea_type",
    "btn_idea_photo",
    "btn_idea_award",
    "btn_idea_master",
    "btn_idea_sign",
    "btn_idea_other",
    "text_describe_task",
    # О нас
    "about_text",
    "btn_about_equipment",
    "btn_about_projects",
    "btn_about_contacts",
    "btn_about_map",
    "about_equipment_text",
    "about_projects_text",
    "about_contacts_text",
    "about_map_text",
]

PHOTO_KEYS = [
    "photo_main_menu",
    "photo_print",
    "photo_scan",
    "photo_idea",
    "photo_about",
    "photo_about_equipment",
    "photo_about_projects",
    "photo_about_contacts",
    "photo_about_map",
]

TOGGLE_KEYS = [
    "enabled_menu_print",
    "enabled_menu_scan",
    "enabled_menu_idea",
    "enabled_menu_about",
    "enabled_print_fdm",
    "enabled_print_resin",
    "enabled_print_unknown",
    "enabled_scan_human",
    "enabled_scan_object",
    "enabled_scan_industrial",
    "enabled_scan_other",
    "enabled_idea_photo",
    "enabled_idea_award",
    "enabled_idea_master",
    "enabled_idea_sign",
    "enabled_idea_other",
    "enabled_about_equipment",
    "enabled_about_projects",
    "enabled_about_contacts",
    "enabled_about_map",
]

SETTINGS_KEYS = [
    "orders_chat_id",
    "manager_username",
    "placeholder_photo_path",
] + TOGGLE_KEYS


def _to_bool(v: Any, default: bool = True) -> bool:
    if v is None or v == "":
        return default
    return str(v).lower() in {"1", "true", "yes", "on"}


@router.get("/")
async def get_bot_config(payload: dict = Depends(verify_token)) -> dict[str, Any]:
    return database.get_bot_config()


@router.put("/")
async def update_bot_config(data: dict[str, str], payload: dict = Depends(verify_token)):
    try:
        database.set_bot_config_many({str(k): "" if v is None else str(v) for k, v in (data or {}).items()})
        return {"message": "Настройки сохранены"}
    except Exception as exc:
        logger.exception("Ошибка сохранения настроек бота")
        raise HTTPException(status_code=500, detail="Не удалось сохранить настройки") from exc


@router.get("/texts")
async def get_bot_texts(payload: dict = Depends(verify_token)):
    cfg = database.get_bot_config()
    return {k: cfg.get(k, "") for k in TEXT_KEYS}


@router.put("/texts")
async def update_bot_texts(data: dict[str, Any], payload: dict = Depends(verify_token)):
    try:
        to_save: dict[str, str] = {}
        for k in TEXT_KEYS:
            if k in (data or {}):
                v = data.get(k)
                to_save[k] = "" if v is None else str(v)
        database.set_bot_config_many(to_save)
        return {"message": "Тексты сохранены"}
    except Exception as exc:
        logger.exception("Ошибка сохранения текстов бота")
        raise HTTPException(status_code=500, detail="Не удалось сохранить тексты") from exc


@router.get("/settings")
async def get_bot_settings(payload: dict = Depends(verify_token)):
    cfg = database.get_bot_config()
    keys = SETTINGS_KEYS + PHOTO_KEYS
    result: dict[str, Any] = {k: cfg.get(k, "") for k in keys}
    for k in TOGGLE_KEYS:
        result[k] = _to_bool(result.get(k, ""), True)
    return result


@router.put("/settings")
async def update_bot_settings(data: dict[str, Any], payload: dict = Depends(verify_token)):
    try:
        keys = SETTINGS_KEYS + PHOTO_KEYS
        to_save: dict[str, str] = {}
        for k in keys:
            if k not in (data or {}):
                continue
            v = data.get(k)
            if k in TOGGLE_KEYS:
                to_save[k] = "1" if bool(v) else "0"
            else:
                to_save[k] = "" if v is None else str(v)
        database.set_bot_config_many(to_save)
        return {"message": "Системные настройки сохранены"}
    except Exception as exc:
        logger.exception("Ошибка сохранения настроек бота")
        raise HTTPException(status_code=500, detail="Не удалось сохранить настройки") from exc