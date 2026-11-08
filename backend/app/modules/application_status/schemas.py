from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ApplicationStatusValue = Literal[
    "applied", "processing", "analyzed", "shortlisted", "rejected", "withdrawn"
]


class ApplicationStatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatusValue
    reason: str | None = Field(default=None, max_length=1000)


class StatusHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    job_id: UUID
    company_id: UUID
    from_status: str | None
    to_status: str
    actor_type: Literal["user", "system"]
    actor_user_id: UUID | None
    reason: str | None
    request_id: UUID | None
    created_at: datetime


class ApplicationStatusPage(BaseModel):
    items: list[StatusHistoryEntry]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
