"""Sarvam Voice Agents HTTP clients, each behind an interface with a mock.

Request shapes are from docs.sarvam.ai (read 2026-10-23):
- Instant outbound: POST https://apps.sarvam.ai/api/outbounds/v1/orgs/{org_id}/workspaces/
  {workspace_id}/outbounds, header X-API-Key, body {app_config: {app_id, app_version,
  connection_config: {connection_id, agent_phone_number}, agent_variables, app_overrides:
  {initial_language_name}}, user_config: {user_phone_number}, webhook_config: {url, metadata}}
  -> {attempt_id}. SPENDS CREDITS when the call connects.
- Get transcript (Analytics, read-only, not billed): GET https://apps.sarvam.ai/api/analytics/
  v1/{org_id}/{workspace_id}/{app_id}/transcripts/{interaction_id}, header X-API-Key
  -> {interaction_id, messages: [{turn_id, role, content, language_name}]}.

Nothing here is called unless the matching settings are filled in. Outbound calls are only
placed through salesbot_api.voice.outbound, which applies the opt-in, window, attempt and
spend checks first.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from salesbot_api.settings import Settings
from salesbot_api.voice.security import mask_phone

log = logging.getLogger("salesbot.voice")
BASE = "https://apps.sarvam.ai/api"
TIMEOUT = httpx.Timeout(10.0)


class SarvamNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutboundRequest:
    to_number: str
    agent_variables: dict[str, Any]
    webhook_url: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Sarvam language name, e.g. "Hindi"
    initial_language: str | None = None


class OutboundCallAdapter(ABC):
    name: str
    places_real_calls: bool

    @abstractmethod
    def place(self, request: OutboundRequest) -> str:
        """Start the call. Returns Sarvam's attempt_id."""


class DryRunOutboundAdapter(OutboundCallAdapter):
    """Logs what would be called. Never dials, never spends credits."""

    name = "dry_run"
    places_real_calls = False

    def __init__(self) -> None:
        self.placed: list[OutboundRequest] = []

    def place(self, request: OutboundRequest) -> str:
        self.placed.append(request)
        log.info(
            "DRY RUN outbound call: would call %s (language %s, purpose %s)",
            mask_phone(request.to_number),
            request.initial_language,
            request.metadata.get("purpose"),
        )
        return f"dry-run-{uuid4()}"


class SarvamOutboundAdapter(OutboundCallAdapter):
    """Sarvam instant outbound. Every connected call spends credits."""

    name = "sarvam"
    places_real_calls = True

    def __init__(self, settings: Settings) -> None:
        missing = [
            n
            for n in (
                "sarvam_voice_api_key",
                "sarvam_org_id",
                "sarvam_workspace_id",
                "sarvam_app_id",
                "sarvam_app_version",
                "sarvam_connection_id",
                "sarvam_agent_phone_number",
            )
            if getattr(settings, n) in (None, "")
        ]
        if missing:
            raise SarvamNotConfiguredError(f"missing settings: {', '.join(missing)}")
        self._s = settings

    def place(self, request: OutboundRequest) -> str:
        s = self._s
        if s.sarvam_voice_api_key is None:
            raise SarvamNotConfiguredError("SARVAM_VOICE_API_KEY is not set")
        app_config: dict[str, Any] = {
            "app_id": s.sarvam_app_id,
            "app_version": s.sarvam_app_version,
            "connection_config": {
                "connection_id": s.sarvam_connection_id,
                "agent_phone_number": s.sarvam_agent_phone_number,
            },
            "agent_variables": request.agent_variables,
        }
        if request.initial_language:
            app_config["app_overrides"] = {"initial_language_name": request.initial_language}
        body: dict[str, Any] = {
            "app_config": app_config,
            "user_config": {"user_phone_number": request.to_number},
        }
        if request.webhook_url:
            body["webhook_config"] = {"url": request.webhook_url, "metadata": request.metadata}
        url = (
            f"{BASE}/outbounds/v1/orgs/{quote(s.sarvam_org_id or '')}"
            f"/workspaces/{quote(s.sarvam_workspace_id or '')}/outbounds"
        )
        response = httpx.post(
            url,
            json=body,
            headers={"X-API-Key": s.sarvam_voice_api_key.get_secret_value()},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return str(response.json()["attempt_id"])


class AnalyticsClient(ABC):
    @abstractmethod
    def turn_languages(self, interaction_id: str) -> list[str]:
        """Language of each turn, in order (Sarvam names, e.g. "Hindi")."""


class NoAnalytics(AnalyticsClient):
    def turn_languages(self, interaction_id: str) -> list[str]:
        return []


class SarvamAnalytics(AnalyticsClient):
    """Read-only Analytics API. Not billed per Sarvam's pricing page."""

    def __init__(self, settings: Settings) -> None:
        if not (
            settings.sarvam_voice_api_key
            and settings.sarvam_org_id
            and settings.sarvam_workspace_id
            and settings.sarvam_app_id
        ):
            raise SarvamNotConfiguredError("Sarvam Analytics settings are missing")
        self._s = settings

    def turn_languages(self, interaction_id: str) -> list[str]:
        s = self._s
        if s.sarvam_voice_api_key is None:
            raise SarvamNotConfiguredError("SARVAM_VOICE_API_KEY is not set")
        url = (
            f"{BASE}/analytics/v1/{quote(s.sarvam_org_id or '')}/"
            f"{quote(s.sarvam_workspace_id or '')}/{quote(s.sarvam_app_id or '')}/transcripts/"
            f"{quote(interaction_id, safe='')}"
        )
        response = httpx.get(
            url, headers={"X-API-Key": s.sarvam_voice_api_key.get_secret_value()}, timeout=TIMEOUT
        )
        response.raise_for_status()
        return [m["language_name"] for m in response.json().get("messages", [])]


def analytics_client(settings: Settings) -> AnalyticsClient:
    try:
        return SarvamAnalytics(settings)
    except SarvamNotConfiguredError:
        return NoAnalytics()


def recording_ref(app_id: str | None, interaction_id: str) -> str:
    """How to fetch Sarvam's recording later (Analytics Get recording). We store this, not
    the audio."""
    return f"sarvam:analytics/{app_id or '-'}/recordings/{interaction_id}"
