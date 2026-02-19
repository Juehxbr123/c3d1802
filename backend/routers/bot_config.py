from typing import Any

from fastapi import APIRouter, Depends

import database
from routers.auth import verify_token

router = APIRouter()


@router.get("/")
async def get_bot_config(payload: dict = Depends(verify_token)) -> dict[str, Any]:
    return database.get_bot_config()


@router.put("/")
async def update_bot_config(data: dict[str, str], payload: dict = Depends(verify_token)):
    for key, value in data.items():
        database.set_bot_config(key, value)
    return {"message": "Настройки сохранены"}
