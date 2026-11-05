import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import AuthProvider, UserRole


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
