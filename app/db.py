"""Kết nối sqlite3 (thư viện chuẩn, không ORM)."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from .config import settings


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """Dependency của FastAPI: mỗi request một kết nối."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def one(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
