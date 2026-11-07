import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, utc_now


class Resume(BaseModel):
    """The ORIGINAL uploaded file (metadata + storage pointer) and its background-processing state."""

    __tablename__ = "resumes"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )

    original_filename: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # display only
    extension: Mapped[str] = mapped_column(String(8), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # DETECTED, not client-declared
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default="uploaded", nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    failure_message: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duplicate_of_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid
    )  # same file hash seen earlier in this company

    __table_args__ = (
        UniqueConstraint(
            "company_id", "job_id", "sha256", name="uq_resumes_company_job_sha256"
        ),
        Index("ix_resumes_company_sha256", "company_id", "sha256"),
        CheckConstraint(
            "status in ('uploaded','queued','extracting','analyzing','completed','failed')",
            name="ck_resumes_status",
        ),
    )
