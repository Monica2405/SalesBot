import os
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from salesbot_api.main import app
from salesbot_api.settings import Settings, get_settings

TEST_JWT_SECRET = "test-secret-at-least-32-characters-long!!"
LOCAL_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never read the developer's .env
    return Settings(_env_file=None, supabase_jwt_secret=TEST_JWT_SECRET)


@pytest.fixture
def client(settings: Settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Database fixtures (tests marked `db`). Skip without a database unless REQUIRE_DB=1 (CI).
# ---------------------------------------------------------------------------


@pytest.fixture
def db_url() -> str:
    psycopg = pytest.importorskip("psycopg")
    url = os.environ.get("SUPABASE_DB_URL") or LOCAL_DB_URL
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no database available ({exc.__class__.__name__}); run `make db-up`")
    return url


@pytest.fixture
def conn(db_url):
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        yield c


@dataclass
class Clinic:
    business_id: uuid.UUID
    dr_a: uuid.UUID
    dr_b: uuid.UUID
    client_id: uuid.UUID
    other_client_id: uuid.UUID


@pytest.fixture
def clinic(conn) -> Clinic:
    """A business with two practitioners (Mon-Sat 10:00-13:00, 30 min, break 11:30-12:00)
    and two clients. Committed so concurrency tests can see it; deleted afterwards."""
    bid = uuid.uuid4()
    conn.execute(
        "insert into public.businesses (id, name, slug, pack_id) values (%s, %s, %s, 'clinic')",
        (bid, "Test clinic", f"test-{bid.hex[:12]}"),
    )
    conn.execute("insert into public.scheduling_settings (business_id) values (%s)", (bid,))
    drs = []
    for name in ("Dr A", "Dr B"):
        pid = conn.execute(
            "insert into public.practitioners (business_id, name, consultation_minutes, "
            "first_visit_minutes) values (%s, %s, 30, 45) returning id",
            (bid, name),
        ).fetchone()["id"]
        for weekday in range(1, 7):
            conn.execute(
                "insert into public.practitioner_hours (business_id, practitioner_id, kind, "
                "weekday, start_time, end_time) values (%s, %s, 'work', %s, '10:00', '13:00'), "
                "(%s, %s, 'break', %s, '11:30', '12:00')",
                (bid, pid, weekday, bid, pid, weekday),
            )
        drs.append(pid)
    clients = []
    for ext in ("ext-1", "ext-2"):
        clients.append(
            conn.execute(
                "insert into public.clients (business_id, external_id, name, phone, "
                "whatsapp_opt_in, consent_at) values (%s, %s, 'Test Client', '+919000000001', "
                "true, now()) returning id",
                (bid, ext),
            ).fetchone()["id"]
        )
    try:
        yield Clinic(bid, drs[0], drs[1], clients[0], clients[1])
    finally:
        conn.execute("delete from public.businesses where id = %s", (bid,))
