import json
import os
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings

ALLOWED_STATUSES = {"draft", "new", "submitted", "in_work", "done", "canceled"}
ALLOWED_STATUSES = {"draft", "new", "in_work", "done", "canceled"}


class DatabaseError(Exception):
    pass


def get_connection(retries: int = 10, delay: float = 2.0):
    last_error = None
    for _ in range(retries):
        try:
            return pymysql.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_db,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=False,
            )
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
    raise DatabaseError(f"Cannot connect to DB: {last_error}")


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db_if_needed() -> None:
    with db_cursor() as (_, cur):
        cur.execute("SELECT 1")


def create_order(user_id: int, username: str | None, full_name: str | None, branch: str) -> int:
    with db_cursor() as (_, cur):
        try:
            cur.execute(
                """
                INSERT INTO orders (user_id, username, full_name, branch, status, order_payload)
                VALUES (%s, %s, %s, %s, 'draft', JSON_OBJECT())
                """,
                (user_id, username, full_name, branch),
            )
        except Exception:
            cur.execute(
                """
                INSERT INTO orders (user_id, username, full_name, branch, status)
                VALUES (%s, %s, %s, %s, 'new')
                """,
                (user_id, username, full_name, branch),
            )
        cur.execute(
            """
            INSERT INTO orders (user_id, username, full_name, branch, status, order_payload)
            VALUES (%s, %s, %s, %s, 'draft', JSON_OBJECT())
            """,
            (user_id, username, full_name, branch),
        )
        return cur.lastrowid


def update_order_payload(order_id: int, payload: dict[str, Any], summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cur.execute(
            "UPDATE orders SET order_payload=%s, summary=%s, updated_at=NOW() WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), summary, order_id),
        )


def finalize_order(order_id: int, summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        try:
            cur.execute("UPDATE orders SET status='new', summary=%s, updated_at=NOW() WHERE id=%s", (summary, order_id))
        except Exception:
            cur.execute("UPDATE orders SET status='submitted', updated_at=NOW() WHERE id=%s", (order_id,))
        cur.execute("UPDATE orders SET status='new', summary=%s, updated_at=NOW() WHERE id=%s", (summary, order_id))


def get_bot_config() -> dict[str, str]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT config_key, config_value FROM bot_config")
        return {row["config_key"]: row["config_value"] for row in cur.fetchall()}


def set_bot_config(key: str, value: str) -> None:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO bot_config (config_key, config_value)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=NOW()
            """,
            (key, value),
        )


def list_orders(status: str | None = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    where = "WHERE status=%s" if status else ""
    params: list[Any] = [status] if status else []
    params.extend([limit, offset])
    with db_cursor() as (_, cur):
        cur.execute(
            f"SELECT * FROM orders {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params),
        )
        return cur.fetchall()


def get_order(order_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
        return cur.fetchone()


def update_order_status(order_id: int, status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError("Unknown status")
    with db_cursor() as (_, cur):
        cur.execute("UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", (status, order_id))


def add_order_message(order_id: int, direction: str, text: str, telegram_message_id: int | None = None) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO order_messages (order_id, direction, message_text, telegram_message_id)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, direction, text, telegram_message_id),
        )
        return cur.lastrowid


def list_order_messages(order_id: int, limit: int = 30) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT * FROM order_messages
            WHERE order_id=%s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (order_id, limit),
        )
        rows = cur.fetchall()
        rows.reverse()
        return rows


def add_order_file(
    order_id: int,
    file_id: str,
    filename: str,
    mime: str | None,
    size: int | None,
    telegram_message_id: int | None = None,
    local_path: str | None = None,
) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO order_files (order_id, telegram_file_id, telegram_message_id, original_name, mime_type, file_size, local_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (order_id, file_id, telegram_message_id, filename, mime, size, local_path),
        )
        return cur.lastrowid


def list_order_files(order_id: int) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM order_files WHERE order_id=%s ORDER BY created_at ASC", (order_id,))
        return cur.fetchall()


def get_order_statistics() -> dict[str, int]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) AS c FROM orders")
        total = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status='new'")
        new_orders = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('new','in_work')")
        active = cur.fetchone()["c"]
        return {"total_orders": total, "new_orders": new_orders, "active_orders": active}


def get_orders_paginated(limit: int, offset: int, status_filter: str | None = None):
    return list_orders(status_filter, limit, offset)



def get_orders_paginated(limit: int, offset: int, status_filter: str | None = None):
    return list_orders(status_filter, limit, offset)


def get_last_user_order(user_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT * FROM orders WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        return cur.fetchone()


def find_or_create_active_order(user_id: int, username: str | None, full_name: str | None) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT id FROM orders WHERE user_id=%s AND status IN ('draft','new','in_work') ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO orders (user_id, username, full_name, branch, status, order_payload) VALUES (%s,%s,%s,'dialog','draft',JSON_OBJECT())",
            (user_id, username, full_name),
        )
        return cur.lastrowid
