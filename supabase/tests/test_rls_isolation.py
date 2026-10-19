"""Cross-business RLS isolation, executed against a real Supabase Postgres.

Locally this SKIPS when no database is reachable (local DB is deferred, see docs/DECISIONS.md).
CI starts local Supabase and sets REQUIRE_DB=1, which turns the skip into a failure.
"""

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.db

LOCAL_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
SQL = (Path(__file__).parent / "rls_isolation.sql").read_text(encoding="utf-8")


@pytest.fixture
def conn():
    url = os.environ.get("SUPABASE_DB_URL") or LOCAL_DB_URL
    try:
        c = psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no database available ({exc.__class__.__name__}); run `make db-up`")
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def test_owner_cannot_access_other_business(conn):
    # Runs in one transaction; the fixture rolls it back so no fixtures leak.
    conn.execute(SQL)
