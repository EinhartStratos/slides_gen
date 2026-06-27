from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
import logging

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import Settings


logger = logging.getLogger(__name__)


class MySQLDatabase:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def connection(self) -> Iterator[pymysql.Connection]:
        conn = pymysql.connect(
            host=self.settings.db_host,
            port=self.settings.db_port,
            user=self.settings.db_user,
            password=self.settings.db_password,
            database=self.settings.db_schema,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            with self.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 AS ok")
                    return bool(cursor.fetchone())
        except Exception as exc:
            logger.warning("数据库健康检查失败: %s", exc)
            return False

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        print(sql)
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                print(cursor.fetchone())
                return cursor.fetchone()

    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                return list(cursor.fetchall())

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> int:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                return cursor.execute(sql, params or ())
