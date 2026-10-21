"""Postgres access (psycopg 3). Schema lives in supabase/migrations; this module only reads/writes.

This connection runs as the postgres role and bypasses RLS, so every query MUST filter by
business_id explicitly. Owner-facing reads go through the admin app + RLS instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from salesbot_api.settings import Settings


class DatabaseNotConfiguredError(RuntimeError):
    pass


@contextmanager
def connect(settings: Settings, *, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """autocommit=True for code that opens its own `conn.transaction()` (booking, intake)."""
    if settings.supabase_db_url is None:
        raise DatabaseNotConfiguredError("SUPABASE_DB_URL is not set")
    with psycopg.connect(
        settings.supabase_db_url.get_secret_value(),
        row_factory=dict_row,
        connect_timeout=5,
        autocommit=autocommit,
    ) as conn:
        yield conn


def check(settings: Settings) -> str:
    """'ok', 'not_configured' or 'unreachable'. Used by /health/db."""
    try:
        with connect(settings) as conn:
            conn.execute("select 1")
        return "ok"
    except DatabaseNotConfiguredError:
        return "not_configured"
    except psycopg.OperationalError:
        return "unreachable"
