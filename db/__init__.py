from __future__ import annotations

import os
from contextlib import AbstractContextManager
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from psycopg2.pool import ThreadedConnectionPool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://devint:changeme_in_production@postgres:5432/dev_intelligence")

_pool: ThreadedConnectionPool | None = None


def _normalize_sql(sql: str) -> str:
    return sql.replace("?", "%s")


class CompatRow(dict):
    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CompatCursor:
    def __init__(self, raw_cursor: psycopg2.extensions.cursor):
        self._cursor = raw_cursor

    def execute(self, sql: str, params: Any = None) -> "CompatCursor":
        self._cursor.execute(_normalize_sql(sql), params)
        return self

    def fetchone(self) -> CompatRow | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return CompatRow(row)
        return CompatRow(dict(row))

    def fetchall(self) -> list[CompatRow]:
        rows = self._cursor.fetchall()
        return [CompatRow(dict(row)) if not isinstance(row, dict) else CompatRow(row) for row in rows]

    def close(self) -> None:
        self._cursor.close()


class CompatConnection(AbstractContextManager["CompatConnection"]):
    def __init__(self, raw_connection: psycopg2.extensions.connection):
        self._raw_connection = raw_connection

    def cursor(self) -> CompatCursor:
        raw_cursor = self._raw_connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return CompatCursor(raw_cursor)

    def execute(self, sql: str, params: Any = None) -> CompatCursor:
        cursor = self.cursor()
        return cursor.execute(sql, params)

    def commit(self) -> None:
        self._raw_connection.commit()

    def rollback(self) -> None:
        self._raw_connection.rollback()

    def close(self) -> None:
        release_connection(self._raw_connection)

    def __enter__(self) -> "CompatConnection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(2, 10, DATABASE_URL)
    return _pool


def get_connection() -> CompatConnection:
    raw_connection = get_pool().getconn()
    raw_connection.autocommit = False
    return CompatConnection(raw_connection)


def release_connection(raw_connection: psycopg2.extensions.connection) -> None:
    get_pool().putconn(raw_connection)


class db_cursor:
    def __init__(self):
        self.conn: CompatConnection | None = None
        self.cursor: CompatCursor | None = None

    def __enter__(self) -> CompatCursor:
        self.conn = get_connection()
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        assert self.conn is not None
        assert self.cursor is not None
        try:
            self.cursor.close()
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()
