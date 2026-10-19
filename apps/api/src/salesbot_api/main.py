"""SalesBot HTTP API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status

from salesbot_api import db
from salesbot_api.auth import AuthUser, current_user
from salesbot_api.settings import Settings, get_settings
from salesbot_core.packs import load_all_packs

app = FastAPI(title="SalesBot API", version="0.1.0")

SettingsDep = Annotated[Settings, Depends(get_settings)]


@app.get("/health")
def health(settings: SettingsDep) -> dict[str, str]:
    """Liveness. Never touches the database so it works with no DB configured."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/db")
def health_db(settings: SettingsDep) -> dict[str, str]:
    return {"database": db.check(settings)}


@app.get("/packs")
def list_packs() -> list[dict[str, Any]]:
    return [
        {"id": p.id, "name": p.name, "version": p.version, "languages": p.languages}
        for p in load_all_packs().values()
    ]


@app.get("/me")
def me(user: Annotated[AuthUser, Depends(current_user)]) -> dict[str, Any]:
    return {"id": str(user.id), "email": user.email}


# --- Webhooks (stubs). Provider choices are open decisions; see docs/DECISIONS.md. ---


@app.post("/webhooks/telephony/{provider}", status_code=status.HTTP_202_ACCEPTED)
def telephony_webhook(provider: str, settings: SettingsDep) -> dict[str, str]:
    # TODO: verify the provider's request signature, then hand the call to the voice agent.
    if provider != settings.telephony_provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown telephony provider")
    if provider != "mock":
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"{provider} webhook not built yet")
    return {"status": "accepted"}


@app.post("/webhooks/whatsapp")
def whatsapp_webhook() -> None:
    # TODO: verify signature, record inbound message as a lead touch.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "WhatsApp provider not decided")


@app.get("/integrations/google/callback")
def google_oauth_callback() -> None:
    # TODO: exchange code for tokens, store refresh token server-side per business.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Google Calendar OAuth not built yet")
