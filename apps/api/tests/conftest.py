import pytest
from fastapi.testclient import TestClient

from salesbot_api.main import app
from salesbot_api.settings import Settings, get_settings

TEST_JWT_SECRET = "test-secret-at-least-32-characters-long!!"


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
