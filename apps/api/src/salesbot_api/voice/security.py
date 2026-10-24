"""Authentication for the endpoints Sarvam calls.

- API tools and hooks: `Authorization: Bearer <VOICE_TOOL_SECRET>`. Sarvam's API tool supports
  bearer auth with the token kept in its Secrets store.
- Call-completion webhooks: Sarvam's webhook_config is only a URL plus metadata (no headers,
  no documented signature), so the URL path carries VOICE_WEBHOOK_SECRET.
- Optional VOICE_IP_ALLOWLIST on both. Sarvam documents 4.213.167.70 and 35.154.84.150 for
  tool calls; whether webhooks come from the same addresses is not documented.

Every failure is a bare 401 (or 503 when not configured), never a hint about which check failed.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from salesbot_api.settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _client_ip_allowed(request: Request, settings: Settings) -> bool:
    if not settings.voice_ip_allowlist:
        return True
    allowed = {ip.strip() for ip in settings.voice_ip_allowlist.split(",") if ip.strip()}
    host = request.client.host if request.client else ""
    return host in allowed


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")


def require_tool_auth(
    request: Request, settings: SettingsDep, authorization: str = Header(default="")
) -> None:
    if settings.voice_tool_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice tools are not configured")
    expected = f"Bearer {settings.voice_tool_secret.get_secret_value()}".encode()
    if not hmac.compare_digest(authorization.encode(), expected):
        raise _unauthorized()
    if not _client_ip_allowed(request, settings):
        raise _unauthorized()


def require_webhook_token(request: Request, token: str, settings: SettingsDep) -> None:
    if settings.voice_webhook_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice webhooks not configured")
    expected = settings.voice_webhook_secret.get_secret_value().encode()
    if not hmac.compare_digest(token.encode(), expected):
        raise _unauthorized()
    if not _client_ip_allowed(request, settings):
        raise _unauthorized()


def mask_phone(phone: str | None) -> str:
    """For logs: keep the country code and last 4 digits only."""
    if not phone:
        return "-"
    return phone[:3] + "*" * max(len(phone) - 7, 0) + phone[-4:]


def normalize_phone(raw: str | None) -> str | None:
    """Caller ids arrive as +91..., 91..., 0... or 10 digits. Returns E.164 or None."""
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.strip().startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return None
