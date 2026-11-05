import enum
import uuid
from typing import TYPE_CHECKING, List, Optional

from app.models.base import BaseModel
from sqlalchemy import Enum, ForeignKey, Integer, String, Text, Uuid, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.job_access import JobAccess
    from app.models.job_requirement import JobRequirement


class JobStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    ARCHIVED = "archived"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERN = "intern"


class WorkMode(str, enum.Enum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


def enum_values(enum_class):
    return [item.value for item in enum_class]


class Job(BaseModel):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_company_status", "company_id", "status"),
        Index("ix_jobs_company_created", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType, native_enum=False, values_callable=enum_values, length=30), nullable=False
    )
    work_mode: Mapped[WorkMode] = mapped_column(
        Enum(WorkMode, native_enum=False, values_callable=enum_values, length=30), nullable=False
    )
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    openings: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, values_callable=enum_values, length=30),
        default=JobStatus.DRAFT,
        nullable=False,
        index=True,
    )

    company: Mapped["Company"] = relationship("Company", back_populates="jobs", lazy="selectin")
    requirements: Mapped[List["JobRequirement"]] = relationship(
        "JobRequirement", back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    access_grants: Mapped[List["JobAccess"]] = relationship(
        "JobAccess", cascade="all, delete-orphan", lazy="raise"
    )
