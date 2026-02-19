import logging
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import database
from config import settings
from routers.auth import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)

STATUS_MAP = {
    "draft": "Черновик",
    "new": "Новая заявка",
    "submitted": "Новая заявка",
    "in_work": "В работе",
    "done": "Готово",
    "canceled": "Отменено",
}

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
    try:
        offset = (page - 1) * limit
        orders = database.get_orders_paginated(limit, offset, status_filter)
        for order in orders:
            order["status_label"] = STATUS_MAP.get(order.get("status"), order.get("status"))
        return orders
    except Exception as exc:
        logger.exception("Ошибка получения списка заявок")
        raise HTTPException(status_code=500, detail="Ошибка получения списка заявок") from exc


    offset = (page - 1) * limit
    orders = database.get_orders_paginated(limit, offset, status_filter)
    for order in orders:
        order["status_label"] = STATUS_MAP.get(order["status"], order["status"])
    return orders


@router.get("/stats")
async def get_order_stats(payload: dict = Depends(verify_token)):
    try:
        return database.get_order_statistics()
    except Exception as exc:
        logger.exception("Ошибка получения статистики")
        return {"total_orders": 0, "new_orders": 0, "active_orders": 0}


    return database.get_order_statistics()


@router.get("/{order_id}")
async def get_order(order_id: int, payload: dict = Depends(verify_token)):
    order = database.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    order["status_label"] = STATUS_MAP.get(order.get("status"), order.get("status"))
    order["status_label"] = STATUS_MAP.get(order["status"], order["status"])
    return order


@router.put("/{order_id}")
async def update_order(order_id: int, order_update: OrderUpdate, payload: dict = Depends(verify_token)):
    current_order = database.get_order(order_id)
    if not current_order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if order_update.status:
        try:
            database.update_order_status(order_id, order_update.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Недопустимый статус") from exc
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
                if file_info.status_code == 200:
                    data = file_info.json().get("result", {})
                    if data.get("file_path"):
                        file_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{data['file_path']}"
            except Exception:
                logger.exception("Ошибка резолва telegram file_id")
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
    if order.get("status") == "canceled":
        raise HTTPException(status_code=400, detail="Нельзя отправить сообщение для отменённой заявки")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "http://bot:8081/internal/sendMessage",
                headers={"X-Internal-Key": settings.internal_api_key},
                json={"user_id": order["user_id"], "text": body.text, "order_id": order_id},
            )
    except Exception as exc:
        logger.exception("Ошибка вызова bot internal API")
        raise HTTPException(status_code=400, detail="Не удалось отправить сообщение в Telegram") from exc

    if response.status_code >= 400:
        detail = "Не удалось отправить сообщение в Telegram"
        try:
            detail = response.json().get("error", detail)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=detail)

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
