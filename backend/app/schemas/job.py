import math
import uuid
from datetime import datetime
from typing import Optional

from app.models.job import EmploymentType, JobStatus, WorkMode
from app.models.job_access import JobAccessLevel
from app.models.job_requirement import (
    RequirementCategory,
    RequirementImportance,
    RequirementType,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class JobCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    department: Optional[str] = Field(default=None, max_length=255)
    employment_type: EmploymentType
    work_mode: WorkMode
    location: Optional[str] = Field(default=None, max_length=255)
    openings: int = Field(default=1, ge=1)

    @field_validator("title", "description", "department", "location")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if value is not None else value

    @field_validator("title", "description")
    @classmethod
    def require_nonempty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class JobUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, min_length=1)
    department: Optional[str] = Field(default=None, max_length=255)
    employment_type: Optional[EmploymentType] = None
    work_mode: Optional[WorkMode] = None
    location: Optional[str] = Field(default=None, max_length=255)
    openings: Optional[int] = Field(default=None, ge=1)

    @field_validator("title", "description", "department", "location")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if value is not None else value

    @field_validator("title", "description")
    @classmethod
    def require_nonempty_text(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value:
            raise ValueError("Value cannot be blank")
        return value

    @model_validator(mode="after")
    def disallow_null_required_fields(self):
        for field in (
                "title",
                "description",
                "employment_type",
                "work_mode",
                "openings",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class JobResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    description: str
    department: Optional[str]
    employment_type: EmploymentType
    work_mode: WorkMode
    location: Optional[str]
    openings: int
    status: JobStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobRequirementFields(BaseModel):
    category: RequirementCategory
    name: str = Field(min_length=1, max_length=255)
    requirement_type: RequirementType
    importance: RequirementImportance
    weight: float = Field(default=0.0, ge=0, le=1)
    is_mandatory: bool

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Requirement name cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_type_weight(self):
        if self.requirement_type == RequirementType.MANDATORY:
            if not self.is_mandatory or self.weight > 0:
                raise ValueError(
                    "Mandatory requirements must set is_mandatory=true and weight must be greater than 0"
                )

        return self


class JobRequirementCreateRequest(JobRequirementFields):
    pass


class JobRequirementUpdateRequest(BaseModel):
    category: Optional[RequirementCategory] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    requirement_type: Optional[RequirementType] = None
    importance: Optional[RequirementImportance] = None
    weight: Optional[float] = Field(default=None, ge=0, le=1)
    is_mandatory: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Requirement name cannot be blank")
        return value

    @model_validator(mode="after")
    def disallow_null_values(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class JobRequirementResponse(JobRequirementFields):
    id: uuid.UUID
    job_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RequirementExtractionRequest(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1)

    @field_validator("description")
    @classmethod
    def trim_description(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Description cannot be blank")
        return value


class RequirementExtractionSuggestions(BaseModel):
    suggestions: list[JobRequirementFields]

    @model_validator(mode="after")
    def validate_preference_weights(self):
        total = sum(
            requirement.weight
            for requirement in self.suggestions
            if requirement.requirement_type == RequirementType.PREFERRED
        )
        if total != 0 and not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
            pass

        return self


class JobAccessGrantRequest(BaseModel):
    email: EmailStr
    access_level: JobAccessLevel = JobAccessLevel.VIEWER

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class JobAccessResponse(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    access_level: JobAccessLevel
    granted_by_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
