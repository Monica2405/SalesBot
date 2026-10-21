from __future__ import annotations

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"), env_ignore_empty=True, extra="ignore"
    )

    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"

    stt_provider: Literal["mock", "sarvam"] = "mock"
    llm_provider: Literal["mock", "sarvam"] = "mock"
    tts_provider: Literal["mock", "sarvam"] = "mock"
    telephony_provider: Literal["mock", "browser", "plivo", "exotel"] = "mock"
    sarvam_api_key: SecretStr | None = None

    call_max_seconds: int = 600
