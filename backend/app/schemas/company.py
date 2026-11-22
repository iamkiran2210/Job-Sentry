import uuid
from datetime import datetime
from typing import List, Optional

from app.schemas.user import UserPublicResponse
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class CompanyCreateRequest(BaseModel):
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Company name must be at least 2 characters long")
        if len(v) > 255:
            raise ValueError("Company name cannot exceed 255 characters")
        return v


class CompanyUpdateRequest(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) < 2:
                raise ValueError("Company name must be at least 2 characters long")
            if len(v) > 255:
                raise ValueError("Company name cannot exceed 255 characters")
            return v
        return v


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompanyMembersResponse(BaseModel):
    members: List[UserPublicResponse]


class CompanyMemberGrantRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()
