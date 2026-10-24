"""Postgres connection pool (psycopg 3). One pool per process, reused across Lambda invocations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from inventory_common.config import database_dsn, settings

Conn = psycopg.Connection[dict[str, Any]]

_pool: ConnectionPool[Conn] | None = None


def get_pool() -> ConnectionPool[Conn]:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=database_dsn(),
            min_size=0 if settings.is_aws else 1,
            max_size=settings.db_pool_max,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
            check=ConnectionPool.check_connection,
        )
    return _pool


@contextmanager
def connection() -> Iterator[Conn]:
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def transaction() -> Iterator[Conn]:
    """Yield a connection inside a transaction; commits on success, rolls back on error."""
    with get_pool().connection() as conn, conn.transaction():
        yield conn
