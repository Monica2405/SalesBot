"""Server settings, read from env / the repo-root .env. Empty values count as unset."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: Literal["local", "staging", "production"] = "local"
    secret_key: SecretStr | None = None
    log_level: str = "INFO"

    # Supabase. The service role key bypasses RLS: server-side only.
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_db_url: SecretStr | None = None
    supabase_jwt_secret: SecretStr | None = None

    telephony_provider: Literal["mock", "plivo", "exotel"] = "mock"

    # Client intake (docs/INTAKE_CONTRACT.md). Shared with the owner of the registration form.
    intake_adapter: Literal["hmac_webhook"] = "hmac_webhook"
    intake_hmac_secret: SecretStr | None = None

    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None

    whatsapp_provider: str = "mock"
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None

    hubspot_enabled: bool = False
    hubspot_access_token: SecretStr | None = None

    call_max_seconds: int = 600
    default_business_usage_cap_minutes: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
