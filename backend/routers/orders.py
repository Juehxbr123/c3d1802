import json

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import database
from config import settings
from routers.auth import verify_token

router = APIRouter()

STATUS_MAP = {
    "draft": "Черновик",
    "new": "Новая заявка",
    "in_work": "В работе",
    "done": "Готово",
    "canceled": "Отменено",
}


class OrderUpdate(BaseModel):
    status: str | None = None


class MessageCreate(BaseModel):
    text: str


@router.get("/")
async def get_orders(page: int = 1, limit: int = 20, status_filter: str | None = None, payload: dict = Depends(verify_token)):
    offset = (page - 1) * limit
    orders = database.get_orders_paginated(limit, offset, status_filter)
    for order in orders:
        order["status_label"] = STATUS_MAP.get(order["status"], order["status"])
    return orders


@router.get("/stats")
async def get_order_stats(payload: dict = Depends(verify_token)):
    return database.get_order_statistics()


@router.get("/{order_id}")
async def get_order(order_id: int, payload: dict = Depends(verify_token)):
    order = database.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    order["status_label"] = STATUS_MAP.get(order["status"], order["status"])
    return order


@router.put("/{order_id}")
async def update_order(order_id: int, order_update: OrderUpdate, payload: dict = Depends(verify_token)):
    current_order = database.get_order(order_id)
    if not current_order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if order_update.status:
        database.update_order_status(order_id, order_update.status)
    return {"message": "Заявка обновлена"}


@router.get("/{order_id}/files")
async def get_order_files(order_id: int, payload: dict = Depends(verify_token)):
    files = database.list_order_files(order_id)
    result = []
    async with httpx.AsyncClient(timeout=20) as client:
        for item in files:
            file_url = None
            try:
                file_info = await client.get(
                    f"https://api.telegram.org/bot{settings.bot_token}/getFile",
                    params={"file_id": item["telegram_file_id"]},
                )
                data = file_info.json().get("result", {})
                if data.get("file_path"):
                    file_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{data['file_path']}"
            except Exception:
                file_url = None
            result.append({**item, "file_url": file_url})
    return {"files": result}


@router.get("/{order_id}/messages")
async def get_messages(order_id: int, payload: dict = Depends(verify_token)):
    return {"messages": database.list_order_messages(order_id, 30)}


@router.post("/{order_id}/messages")
async def send_message(order_id: int, body: MessageCreate, payload: dict = Depends(verify_token)):
    order = database.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if order["status"] == "canceled":
        raise HTTPException(status_code=400, detail="Нельзя отправить сообщение для отменённой заявки")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "http://bot:8081/internal/sendMessage",
            headers={"X-Internal-Key": settings.internal_api_key},
            json={"user_id": order["user_id"], "text": body.text, "order_id": order_id},
        )

    if response.status_code >= 400:
        detail = response.json().get("error", "Не удалось отправить сообщение в Telegram")
        raise HTTPException(status_code=400, detail=detail)

    return {"message": "Сообщение отправлено"}
