import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings

ALLOWED_STATUSES = {"new", "filling", "submitted", "in_work", "done", "canceled"}


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
        except Exception as exc:  # noqa: BLE001
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


def cancel_old_filling_orders(user_id: int) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            "UPDATE orders SET status='canceled', updated_at=NOW() WHERE user_id=%s AND status='filling'",
            (user_id,),
        )
        return cur.rowcount


def create_order(user_id: int, username: str | None, full_name: str | None, branch: str) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO orders (user_id, username, full_name, branch, status)
            VALUES (%s, %s, %s, %s, 'filling')
            """,
            (user_id, username, full_name, branch),
        )
        return cur.lastrowid


def update_order_field(order_id: int, field_name: str, value: str) -> None:
    allowed = {
        "step_type",
        "step_dimensions",
        "step_conditions",
        "step_urgency",
        "step_comment",
        "scan_object",
        "scan_dimensions",
        "scan_location",
        "scan_details",
        "idea_description",
        "idea_references",
        "idea_dimensions",
    }
    if field_name not in allowed:
        raise ValueError(f"Field is not allowed: {field_name}")

    with db_cursor() as (_, cur):
        query = f"UPDATE orders SET {field_name}=%s, updated_at=NOW() WHERE id=%s"
        cur.execute(query, (value, order_id))


def finalize_order(order_id: int) -> None:
    with db_cursor() as (_, cur):
        cur.execute("UPDATE orders SET status='submitted', updated_at=NOW() WHERE id=%s", (order_id,))


def get_bot_config() -> dict[str, str]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT config_key, config_value FROM bot_config")
        rows = cur.fetchall()
        return {row["config_key"]: row["config_value"] for row in rows}


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


def list_orders(filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    filters = filters or {}
    where = []
    params: list[Any] = []

    if filters.get("status"):
        where.append("status=%s")
        params.append(filters["status"])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with db_cursor() as (_, cur):
        cur.execute(
            f"SELECT * FROM orders {where_sql} ORDER BY created_at DESC LIMIT 500",
            tuple(params),
        )
        return cur.fetchall()


def get_order(order_id: int) -> dict[str, Any] | None:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
        return cur.fetchone()


def add_order_file(order_id: int, file_id: str, filename: str, mime: str | None, size: int | None) -> int:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO order_files (order_id, telegram_file_id, original_name, mime_type, file_size)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (order_id, file_id, filename, mime, size),
        )
        return cur.lastrowid


def list_order_files(order_id: int) -> list[dict[str, Any]]:
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM order_files WHERE order_id=%s ORDER BY created_at ASC", (order_id,))
        return cur.fetchall()


def update_order_status(order_id: int, status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError("Unknown status")

    with db_cursor() as (_, cur):
        cur.execute("UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", (status, order_id))		
