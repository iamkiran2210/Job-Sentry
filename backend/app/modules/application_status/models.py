from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import BaseModel


class ApplicationStatusHistory(BaseModel):
    __tablename__ = "application_status_history"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'system')", name="ck_application_status_actor_type"
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('applied', 'processing', 'analyzed', 'shortlisted', 'rejected', 'withdrawn')",
            name="ck_application_status_from_valid",
        ),
        CheckConstraint(
            "to_status IN ('applied', 'processing', 'analyzed', 'shortlisted', 'rejected', 'withdrawn')",
            name="ck_application_status_to_valid",
        ),
        Index("ix_application_status_history_application_created", "application_id", "created_at"),
        Index("ix_application_status_history_company_created", "company_id", "created_at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Keep the immutable actor id even if the user account is later removed.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ApplicationStatusLegacyBackup(Base):
    """Temporary historical values retained so the status migration can downgrade exactly."""

    __tablename__ = "application_status_legacy_backup"
    __table_args__ = {"info": {"migration_support_table": True}}

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
