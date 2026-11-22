import enum
import uuid

from app.models.base import BaseModel
from app.models.job import enum_values
from sqlalchemy import Enum, ForeignKey, Index, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class JobAccessLevel(str, enum.Enum):
    VIEWER = "viewer"
    EDITOR = "editor"


class JobAccess(BaseModel):
    __tablename__ = "job_access"
    __table_args__ = (
        UniqueConstraint("job_id", "user_id", name="uq_job_access_job_user"),
        Index("ix_job_access_user_job", "user_id", "job_id"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_level: Mapped[JobAccessLevel] = mapped_column(
        Enum(JobAccessLevel, native_enum=False, values_callable=enum_values, length=20),
        default=JobAccessLevel.VIEWER,
        nullable=False,
    )
    granted_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
