"""CRM adapter. HubSpot is optional and off unless HUBSPOT_ENABLED=true.

Supabase is the system of record. The CRM is a mirror for businesses that already use one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from salesbot_api.settings import Settings


class CRMContact(BaseModel):
    lead_id: UUID
    business_id: UUID
    name: str | None = None
    phone: str | None = None
    stage: str
    source: str
    properties: dict[str, Any] = Field(default_factory=dict)


class CRMAdapter(ABC):
    name: str

    @abstractmethod
    async def upsert_contact(self, contact: CRMContact) -> str | None:
        """Create/update the contact and return the CRM's id (None when disabled)."""


class NoopCRM(CRMAdapter):
    name = "none"

    async def upsert_contact(self, contact: CRMContact) -> str | None:
        return None


class HubSpotCRM(CRMAdapter):
    """TODO: implement with HubSpot CRM v3 contacts API (upsert by phone) + deal stage sync."""

    name = "hubspot"

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    async def upsert_contact(self, contact: CRMContact) -> str | None:
        raise NotImplementedError("HubSpot adapter not built yet")


def get_crm(settings: Settings) -> CRMAdapter:
    if not settings.hubspot_enabled:
        return NoopCRM()
    if settings.hubspot_access_token is None:
        raise ValueError("HUBSPOT_ENABLED=true but HUBSPOT_ACCESS_TOKEN is empty")
    return HubSpotCRM(settings.hubspot_access_token.get_secret_value())
