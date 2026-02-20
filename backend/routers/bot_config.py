from typing import Any

from fastapi import APIRouter, Depends
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import database
from routers.auth import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)

TEXT_KEYS = [
    "welcome_menu_msg",
    "about_text",
    "about_equipment_text",
    "about_projects_text",
    "about_contacts_text",
    "about_map_text",
    "text_print_tech",
    "text_scan_type",
    "text_idea_type",
    "text_select_material",
    "text_describe_material",
    "text_attach_file",
    "text_print_tech",
    "text_select_material",
    "text_describe_material",
    "text_attach_file",
    "text_scan_type",
    "text_idea_type",
    "text_describe_task",
    "text_result_prefix",
    "text_price_note",
    "text_submit_ok",
    "text_submit_fail",
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
    keys = SETTINGS_KEYS + PHOTO_KEYS
    return {key: config.get(key, "") for key in keys}


@router.put("/settings")
async def update_bot_settings(data: dict[str, Any], payload: dict = Depends(verify_token)):
    keys = SETTINGS_KEYS + PHOTO_KEYS
    for key in keys:
        if key in data:
            database.set_bot_config(key, str(data[key]))
    return {"message": "Системные настройки сохранены"}


def _subset(cfg: dict[str, str], keys: list[str]) -> dict[str, str]:
    return {k: cfg.get(k, "") for k in keys}


@router.get("/texts")
async def get_texts(payload: dict = Depends(verify_token)):
    cfg = database.get_bot_config()
    return _subset(cfg, TEXT_KEYS)


@router.put("/texts")
async def put_texts(body: dict[str, Any], payload: dict = Depends(verify_token)):
    try:
        to_save: dict[str, str] = {}
        for k in TEXT_KEYS:
            if k in body:
                v = body.get(k)
                to_save[k] = "" if v is None else str(v)
        database.set_bot_config_many(to_save)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Ошибка сохранения текстов бота")
        raise HTTPException(status_code=500, detail="Не удалось сохранить тексты") from exc


@router.get("/settings")
async def get_settings(payload: dict = Depends(verify_token)):
    cfg = database.get_bot_config()
    keys = SETTINGS_KEYS + PHOTO_KEYS
    return _subset(cfg, keys)


@router.put("/settings")
async def put_settings(body: dict[str, Any], payload: dict = Depends(verify_token)):
    try:
        keys = SETTINGS_KEYS + PHOTO_KEYS
        to_save: dict[str, str] = {}
        for k in keys:
            if k in body:
                v = body.get(k)
                to_save[k] = "" if v is None else str(v)
        database.set_bot_config_many(to_save)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Ошибка сохранения настроек бота")
        raise HTTPException(status_code=500, detail="Не удалось сохранить настройки") from exc
