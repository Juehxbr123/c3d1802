from typing import Any

from fastapi import APIRouter, Depends

import database
from routers.auth import verify_token

router = APIRouter()

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


@router.get("/")
async def get_bot_config(payload: dict = Depends(verify_token)) -> dict[str, Any]:
    return database.get_bot_config()


@router.put("/")
async def update_bot_config(data: dict[str, str], payload: dict = Depends(verify_token)):
    for key, value in data.items():
        database.set_bot_config(key, str(value))
    return {"message": "Настройки сохранены"}


@router.get("/texts")
async def get_bot_texts(payload: dict = Depends(verify_token)):
    config = database.get_bot_config()
    return {key: config.get(key, "") for key in TEXT_KEYS}


@router.put("/texts")
async def update_bot_texts(data: dict[str, Any], payload: dict = Depends(verify_token)):
    for key in TEXT_KEYS:
        if key in data:
            database.set_bot_config(key, str(data[key]))
    return {"message": "Тексты сохранены"}


@router.get("/settings")
async def get_bot_settings(payload: dict = Depends(verify_token)):
    config = database.get_bot_config()
    keys = SETTINGS_KEYS + PHOTO_KEYS
    result = {key: config.get(key, "") for key in keys}
    for key in TOGGLE_KEYS:
        if result.get(key, "") == "":
            result[key] = True
        else:
            result[key] = str(result[key]).lower() in {"1", "true", "yes", "on"}
    return result


@router.put("/settings")
async def update_bot_settings(data: dict[str, Any], payload: dict = Depends(verify_token)):
    keys = SETTINGS_KEYS + PHOTO_KEYS
    for key in keys:
        if key in data:
            value = data[key]
            if key in TOGGLE_KEYS:
                value = "1" if bool(value) else "0"
            database.set_bot_config(key, str(value))
    return {"message": "Системные настройки сохранены"}
