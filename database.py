import json
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings

ALLOWED_STATUSES = {"draft", "new", "submitted", "in_work", "done", "canceled"}
ACTIVE_STATUSES = {"draft", "new", "submitted", "in_work"}


class DatabaseError(Exception):
    pass


def get_connection(retries: int = 10, delay: float = 2.0):
    last_error = None
def get_connection(retries: int = 20, delay: float = 1.5):
    last_error: Exception | None = None
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
        cur.execute("SHOW COLUMNS FROM orders")
        columns = {row["Field"]: row for row in cur.fetchall()}

        fields: list[str] = []
        values: list[Any] = []

        if "user_id" in columns:
            fields.append("user_id")
            values.append(user_id)
        if "username" in columns:
            fields.append("username")
            values.append(username)
        if "full_name" in columns:
            fields.append("full_name")
            values.append(full_name)
        if "branch" in columns:
            fields.append("branch")
            values.append(branch)

        status_value = "new"
        status_info = columns.get("status", {}).get("Type", "") if "status" in columns else ""
        if "draft" in status_info:
            status_value = "draft"
        if "status" in columns:
            fields.append("status")
            values.append(status_value)

        placeholders = ["%s"] * len(fields)
        if "order_payload" in columns:
            fields.append("order_payload")
            placeholders.append("JSON_OBJECT()")

        query = f"INSERT INTO orders ({', '.join(fields)}) VALUES ({', '.join(placeholders)})"
        cur.execute(query, tuple(values))
        return cur.lastrowid


def update_order_payload(order_id: int, payload: dict[str, Any], summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cur.execute("SHOW COLUMNS FROM orders")
        cols = {row["Field"] for row in cur.fetchall()}
        sets = []
        params: list[Any] = []
# -----------------------------
# Bot config
# -----------------------------
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


def set_bot_config_many(items: dict[str, str]) -> None:
    if not items:
        return
    with db_cursor() as (_, cur):
        cur.executemany(
            """
            INSERT INTO bot_config (config_key, config_value)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=NOW()
            """,
            [(k, v) for k, v in items.items()],
        )


# -----------------------------
# Orders
# -----------------------------
def create_order(user_id: int, username: str | None, full_name: str | None, branch: str) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO orders (user_id, username, full_name, branch, status, order_payload)
            VALUES (%s, %s, %s, %s, 'draft', JSON_OBJECT())
            """,
            (user_id, username, full_name, branch),
        )
        return int(cur.lastrowid)

        if "order_payload" in cols:
            sets.append("order_payload=%s")
            params.append(json.dumps(payload, ensure_ascii=False))
        if "summary" in cols:
            sets.append("summary=%s")
            params.append(summary)
        if "updated_at" in cols:
            sets.append("updated_at=NOW()")

        if not sets:
            return

        params.append(order_id)
        cur.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=%s", tuple(params))


def finalize_order(order_id: int, summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        try:
            cur.execute("UPDATE orders SET status='new', summary=%s, updated_at=NOW() WHERE id=%s", (summary, order_id))
        except Exception:
            cur.execute("UPDATE orders SET status='submitted', updated_at=NOW() WHERE id=%s", (order_id,))
def find_or_create_active_order(user_id: int, username: str | None, full_name: str | None) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT id FROM orders
            WHERE user_id=%s AND status IN ('draft','new','submitted','in_work')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])

        cur.execute(
            """
            INSERT INTO orders (user_id, username, full_name, branch, status, order_payload)
            VALUES (%s, %s, %s, 'dialog', 'new', JSON_OBJECT())
            """,
            (user_id, username, full_name),
        )
        return int(cur.lastrowid)


def update_order_payload(order_id: int, payload: dict[str, Any], summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cur.execute(
            "UPDATE orders SET order_payload=%s, summary=%s, updated_at=NOW() WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), summary, order_id),
        )


def finalize_order(order_id: int, summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cur.execute("SELECT config_key, config_value FROM bot_config")
        return {row["config_key"]: row["config_value"] for row in cur.fetchall()}
        try:
            cur.execute(
                "UPDATE orders SET status='new', summary=%s, updated_at=NOW() WHERE id=%s",
                (summary, order_id),
            )
        except Exception:
            cur.execute(
                "UPDATE orders SET status='submitted', summary=%s, updated_at=NOW() WHERE id=%s",
                (summary, order_id),
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
        return list(cur.fetchall())


def list_orders(status: str | None = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    where = "WHERE status=%s" if status else ""
    params: list[Any] = [status] if status else []
def get_orders_paginated(limit: int, offset: int, status_filter: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE status=%s" if status_filter else ""
    params: list[Any] = [status_filter] if status_filter else []
    params.extend([limit, offset])
    with db_cursor() as (_, cur):
        cur.execute(
            f"SELECT * FROM orders {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params),
        )
        return list(cur.fetchall())


def get_order_statistics() -> dict[str, int]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) AS cnt FROM orders")
        total = int(cur.fetchone()["cnt"])

        cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status IN ('new','submitted')")
        new_orders = int(cur.fetchone()["cnt"])

        cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status IN ('new','submitted','in_work')")
        active_orders = int(cur.fetchone()["cnt"])

    return {"total_orders": total, "new_orders": new_orders, "active_orders": active_orders}


def get_order(order_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_order_status(order_id: int, status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError("Unknown status")
    with db_cursor() as (_, cur):
        cur.execute("UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", (status, order_id))


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
# -----------------------------
# Messages
# -----------------------------
def add_order_message(order_id: int, direction: str, text: str, telegram_message_id: int | None = None) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO order_messages (order_id, direction, message_text, telegram_message_id)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, direction, text, telegram_message_id),
        )
        return int(cur.lastrowid)


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
        rows = list(cur.fetchall())
        rows.reverse()
        return rows


# -----------------------------
# Files
# -----------------------------
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
            INSERT INTO order_files
              (order_id, telegram_file_id, telegram_message_id, original_name, mime_type, file_size, local_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (order_id, file_id, telegram_message_id, filename, mime, size, local_path),
        )
        return int(cur.lastrowid)

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


def get_last_user_order(user_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT * FROM orders WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        return cur.fetchone()


def find_or_create_active_order(user_id: int, username: str | None, full_name: str | None) -> int:
    with db_cursor() as (_, cur):
        try:
            cur.execute(
                "SELECT id FROM orders WHERE user_id=%s AND status IN ('draft','new','in_work') ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
        except Exception:
            pass

        return create_order(user_id, username, full_name, "dialog")

def list_order_files(order_id: int) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT * FROM order_files
            WHERE order_id=%s
            ORDER BY created_at DESC
            """,
            (order_id,),
        )
        return list(cur.fetchall())
