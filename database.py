import json
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings

ALLOWED_STATUSES = {"draft", "new", "submitted", "in_work", "done", "canceled"}


class DatabaseError(Exception):
    pass


def get_connection(retries: int = 20, delay: float = 1.5):
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            return pymysql.connect(
                host=settings.mysql_host,
                port=int(settings.mysql_port),
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


# -----------------------------
# Bot config (table: bot_config)
# -----------------------------

def get_bot_config() -> dict[str, str]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT config_key, config_value FROM bot_config")
        rows = cur.fetchall()
        cfg: dict[str, str] = {}
        for r in rows:
            k = str(r.get("config_key", ""))
            v = r.get("config_value")
            cfg[k] = "" if v is None else str(v)
        return cfg


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
            [(str(k), "" if v is None else str(v)) for k, v in items.items()],
        )


# -----------------------------
# Orders + chat (tables: orders, order_messages, order_files)
# -----------------------------

def _table_columns(cur, table: str) -> set[str]:
    cur.execute(f"SHOW COLUMNS FROM {table}")
    return {r["Field"] for r in cur.fetchall()}


def create_order(user_id: int, username: str | None, full_name: str | None, branch: str) -> int:
    payload = {"branch": branch}
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "orders")

        fields: list[str] = []
        values: list[Any] = []

        if "user_id" in cols:
            fields.append("user_id")
            values.append(user_id)
        if "username" in cols:
            fields.append("username")
            values.append(username)
        if "full_name" in cols:
            fields.append("full_name")
            values.append(full_name)
        if "branch" in cols:
            fields.append("branch")
            values.append(branch)
        if "status" in cols:
            fields.append("status")
            values.append("draft" if "draft" in ALLOWED_STATUSES else "new")
        if "order_payload" in cols:
            fields.append("order_payload")
            values.append(json.dumps(payload, ensure_ascii=False))
        if "updated_at" in cols:
            fields.append("updated_at")
            # NOW() без параметра

        placeholders: list[str] = []
        out_values: list[Any] = []
        for f, v in zip(fields, values, strict=False):
            if f == "updated_at":
                placeholders.append("NOW()")
            else:
                placeholders.append("%s")
                out_values.append(v)

        query = f"INSERT INTO orders ({', '.join(fields)}) VALUES ({', '.join(placeholders)})"
        cur.execute(query, tuple(out_values))
        return int(cur.lastrowid)


def update_order_contact(order_id: int, username: str | None, full_name: str | None) -> None:
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "orders")
        sets: list[str] = []
        params: list[Any] = []

        if "username" in cols:
            sets.append("username=%s")
            params.append(username)
        if "full_name" in cols:
            sets.append("full_name=%s")
            params.append(full_name)
        if "updated_at" in cols:
            sets.append("updated_at=NOW()")

        if not sets:
            return

        params.append(order_id)
        cur.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=%s", tuple(params))


def update_order_payload(order_id: int, payload: dict[str, Any], summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "orders")
        sets: list[str] = []
        params: list[Any] = []

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


def get_last_user_order(user_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT * FROM orders WHERE user_id=%s ORDER BY updated_at DESC, created_at DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_or_create_active_order(user_id: int, username: str | None, full_name: str | None) -> int:
    with db_cursor() as (_, cur):
        try:
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
        except Exception:
            # если нет колонок/таблиц — создадим новую
            pass

    return create_order(user_id, username, full_name, "dialog")


def finalize_order(order_id: int, summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "orders")
        sets: list[str] = []
        params: list[Any] = []

        if "status" in cols:
            sets.append("status=%s")
            params.append("new")
        if "summary" in cols:
            sets.append("summary=%s")
            params.append(summary)
        if "updated_at" in cols:
            sets.append("updated_at=NOW()")

        if not sets:
            return

        params.append(order_id)
        cur.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=%s", tuple(params))


def list_orders(status: str | None = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        if status:
            cur.execute(
                "SELECT * FROM orders WHERE status=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (status, limit, offset),
            )
        else:
            cur.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
        return [dict(r) for r in cur.fetchall()]


def get_orders_paginated(limit: int, offset: int, status_filter: str | None = None) -> list[dict[str, Any]]:
    return list_orders(status_filter, limit=limit, offset=offset)


def get_order_statistics() -> dict[str, int]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) AS c FROM orders")
        total = int(cur.fetchone()["c"])
        cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('new','submitted')")
        new_orders = int(cur.fetchone()["c"])
        cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('new','submitted','in_work','draft')")
        active_orders = int(cur.fetchone()["c"])
    return {"total_orders": total, "new_orders": new_orders, "active_orders": active_orders}


def get_order(order_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_order_status(order_id: int, status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError("invalid status")
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "orders")
        if "status" not in cols:
            return
        if "updated_at" in cols:
            cur.execute("UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", (status, order_id))
        else:
            cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))


def add_order_message(
    order_id: int,
    direction: str,
    text: str,
    telegram_message_id: int | None = None,
) -> None:
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "order_messages")

        fields: list[str] = []
        placeholders: list[str] = []
        params: list[Any] = []

        if "order_id" in cols:
            fields.append("order_id")
            placeholders.append("%s")
            params.append(order_id)
        if "direction" in cols:
            fields.append("direction")
            placeholders.append("%s")
            params.append(direction)

        # разные схемы: message_text или text
        if "message_text" in cols:
            fields.append("message_text")
            placeholders.append("%s")
            params.append(text)
        elif "text" in cols:
            fields.append("text")
            placeholders.append("%s")
            params.append(text)

        if telegram_message_id is not None and "telegram_message_id" in cols:
            fields.append("telegram_message_id")
            placeholders.append("%s")
            params.append(telegram_message_id)

        if "created_at" in cols:
            fields.append("created_at")
            placeholders.append("NOW()")

        if not fields:
            return

        cur.execute(
            f"INSERT INTO order_messages ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
            tuple(params),
        )


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
        rows = [dict(r) for r in cur.fetchall()]

    # привести к ожидаемым ключам (message_text)
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        if "message_text" not in r and "text" in r:
            r["message_text"] = r.get("text")
        out.append(r)
    return out


def add_order_file(
    order_id: int,
    telegram_file_id: str,
    original_name: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    telegram_message_id: int | None = None,
    local_path: str | None = None,
) -> None:
    with db_cursor() as (_, cur):
        cols = _table_columns(cur, "order_files")

        fields: list[str] = []
        placeholders: list[str] = []
        params: list[Any] = []

        if "order_id" in cols:
            fields.append("order_id")
            placeholders.append("%s")
            params.append(order_id)

        if "telegram_file_id" in cols:
            fields.append("telegram_file_id")
            placeholders.append("%s")
            params.append(telegram_file_id)

        if original_name is not None:
            if "original_name" in cols:
                fields.append("original_name")
                placeholders.append("%s")
                params.append(original_name)
            elif "file_name" in cols:
                fields.append("file_name")
                placeholders.append("%s")
                params.append(original_name)

        if mime_type is not None and "mime_type" in cols:
            fields.append("mime_type")
            placeholders.append("%s")
            params.append(mime_type)

        if file_size is not None and "file_size" in cols:
            fields.append("file_size")
            placeholders.append("%s")
            params.append(file_size)

        if telegram_message_id is not None and "telegram_message_id" in cols:
            fields.append("telegram_message_id")
            placeholders.append("%s")
            params.append(telegram_message_id)

        if local_path is not None and "local_path" in cols:
            fields.append("local_path")
            placeholders.append("%s")
            params.append(local_path)

        if "created_at" in cols:
            fields.append("created_at")
            placeholders.append("NOW()")

        if not fields:
            return

        cur.execute(
            f"INSERT INTO order_files ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
            tuple(params),
        )


def list_order_files(order_id: int) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM order_files WHERE order_id=%s ORDER BY created_at DESC", (order_id,))
        rows = [dict(r) for r in cur.fetchall()]

    # привести к ожидаемым ключам (original_name)
    for r in rows:
        if "original_name" not in r and "file_name" in r:
            r["original_name"] = r.get("file_name")
    return rows
