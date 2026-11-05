import uuid
from datetime import datetime
from typing import Literal, Optional

from app.models.job import JobStatus
from app.models.job_access import JobAccessLevel
from app.models.user import AuthProvider, UserRole
from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    name: str
    email: EmailStr


class UserResponse(BaseModel):
    """Full user response schema without sensitive fields."""
    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    company_id: Optional[uuid.UUID] = None
    auth_provider: AuthProvider
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserPublicResponse(BaseModel):
    """Public user response for company member lists."""
    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompanyAccessSummary(BaseModel):
    company_id: uuid.UUID
    company_name: str
    role: UserRole


class UserJobAccessSummary(BaseModel):
    job_id: uuid.UUID
    job_title: str
    company_id: uuid.UUID
    company_name: str
    status: JobStatus
    access_level: JobAccessLevel
    access_source: Literal["company", "job_grant"]
    granted_by_id: Optional[uuid.UUID] = None


class UserAccessOverview(BaseModel):
    company_access: Optional[CompanyAccessSummary]
    job_accesses: list[UserJobAccessSummary]
