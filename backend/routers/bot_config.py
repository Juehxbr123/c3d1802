from typing import Any

from fastapi import APIRouter, Depends

import database
from routers.auth import verify_token

router = APIRouter()

TEXT_KEYS = [
    "welcome_menu_msg",
    "about_text",
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

SETTINGS_KEYS = [
    "orders_chat_id",
    "manager_username",
    "placeholder_photo_path",
]


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
    return {key: config.get(key, "") for key in SETTINGS_KEYS + PHOTO_KEYS}


@router.put("/settings")
async def update_bot_settings(data: dict[str, Any], payload: dict = Depends(verify_token)):
    for key in SETTINGS_KEYS + PHOTO_KEYS:
        if key in data:
            database.set_bot_config(key, str(data[key]))
    return {"message": "Системные настройки сохранены"}
