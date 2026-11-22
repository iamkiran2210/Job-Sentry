import enum
import uuid
from typing import TYPE_CHECKING

from app.models.base import BaseModel
from app.models.job import enum_values
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    String,
    Uuid,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.job import Job


class RequirementCategory(str, enum.Enum):
    SKILLS = "skills"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    RESPONSIBILITY = "responsibility"
    OTHER = "other"


class RequirementType(str, enum.Enum):
    MANDATORY = "mandatory"
    PREFERRED = "preferred"


class RequirementImportance(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class JobRequirement(BaseModel):
    __tablename__ = "job_requirements"
    __table_args__ = (
        Index("ix_job_requirements_job_type", "job_id", "requirement_type"),
        Index("ix_job_requirements_job_category", "job_id", "category"),
        CheckConstraint("weight >= 0 AND weight <= 1", name="ck_job_requirements_weight_range"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[RequirementCategory] = mapped_column(
        Enum(
            RequirementCategory,
            native_enum=False,
            values_callable=enum_values,
            length=40,
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    requirement_type: Mapped[RequirementType] = mapped_column(
        Enum(RequirementType, native_enum=False, values_callable=enum_values, length=30),
        nullable=False,
    )
    importance: Mapped[RequirementImportance] = mapped_column(
        Enum(
            RequirementImportance,
            native_enum=False,
            values_callable=enum_values,
            length=20,
        ),
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped["Job"] = relationship("Job", back_populates="requirements", lazy="selectin")
