import json
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings

# Allowed statuses for admin panel and internal logic
ALLOWED_STATUSES = {"draft", "new", "submitted", "in_work", "done", "canceled"}


class DatabaseError(Exception):
    pass


def get_connection(retries: int = 20, delay: float = 1.5):
    """
    Create MySQL connection with small retry loop (container startup).
    """
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
    # Just validate that DB is reachable.
    with db_cursor() as (_, cur):
        cur.execute("SELECT 1")


# -----------------------------
# Bot config (DB table: bot_config)
# -----------------------------
def get_bot_config() -> dict[str, str]:
    """
    Table bot_config expected:
      config_key (PK/UNIQUE), config_value, updated_at
    """
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
# Orders (DB tables: orders, order_messages, order_files)
# -----------------------------
def create_order(user_id: int, username: str | None, full_name: str | None, branch: str) -> int:
    """
    Creates new order in status 'draft'.

    Expected orders columns:
      id, user_id, username, full_name, branch, status,
      order_payload (TEXT/JSON), summary, created_at, updated_at
    """
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO orders (user_id, username, full_name, branch, status, order_payload)
            VALUES (%s, %s, %s, %s, 'draft', %s)
            """,
            (user_id, username, full_name, branch, json.dumps({"branch": branch}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def get_last_user_order(user_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT * FROM orders WHERE user_id=%s ORDER BY updated_at DESC, created_at DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_or_create_active_order(user_id: int, username: str | None, full_name: str | None) -> int:
    """Returns last active order id for user or creates a new 'dialog' order."""
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
            VALUES (%s, %s, %s, 'dialog', 'new', %s)
            """,
            (user_id, username, full_name, json.dumps({"branch": "dialog"}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def update_order_contact(order_id: int, username: str | None, full_name: str | None) -> None:
    with db_cursor() as (_, cur):
        cur.execute(
            "UPDATE orders SET username=%s, full_name=%s, updated_at=NOW() WHERE id=%s",
            (username, full_name, order_id),
        )


def update_order_payload(order_id: int, payload: dict[str, Any], summary: str | None = None) -> None:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            UPDATE orders
            SET order_payload=%s, summary=%s, updated_at=NOW()
            WHERE id=%s
            """,
            (json.dumps(payload, ensure_ascii=False), summary, order_id),
        )


def finalize_order(order_id: int, summary: str | None = None) -> None:
    """Converts draft -> new, sets summary."""
    with db_cursor() as (_, cur):
        cur.execute("SELECT status FROM orders WHERE id=%s", (order_id,))
        row = cur.fetchone()
        if not row:
            return
        status = row.get("status")
        new_status = "new" if status in ("draft", None, "") else str(status)
        if new_status not in ALLOWED_STATUSES:
            new_status = "new"
        cur.execute(
            "UPDATE orders SET status=%s, summary=%s, updated_at=NOW() WHERE id=%s",
            (new_status, summary, order_id),
        )


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
        raise ValueError("Unknown status")
    with db_cursor() as (_, cur):
        cur.execute(
            "UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s",
            (status, order_id),
        )


def add_order_message(order_id: int, direction: str, text: str, telegram_message_id: int | None = None) -> int:
    """
    order_messages columns:
      id, order_id, direction ('in'|'out'), message_text, telegram_message_id, created_at
    """
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
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (order_id, limit),
        )
        rows = cur.fetchall()
        return [dict(r) for r in reversed(rows)]


def add_order_file(
    order_id: int,
    telegram_file_id: str,
    original_name: str | None = None,
    content_type: str | None = None,
) -> int:
    """
    order_files columns:
      id, order_id, telegram_file_id, original_name, content_type, created_at
    """
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO order_files (order_id, telegram_file_id, original_name, content_type)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, telegram_file_id, original_name, content_type),
        )
        return int(cur.lastrowid)


def list_order_files(order_id: int) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT * FROM order_files
            WHERE order_id=%s
            ORDER BY created_at DESC, id DESC
            """,
            (order_id,),
        )
        return [dict(r) for r in cur.fetchall()]
