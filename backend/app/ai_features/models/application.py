import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Application(BaseModel):
    """Links one candidate to one job. candidate_id stays NULL until resume extraction resolves identity.
    Phase 5 owns the status lifecycle; new applications enter as applied and workers record processing."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_applications_candidate_job"),
        CheckConstraint(
            "status IN ('applied', 'processing', 'analyzed', 'shortlisted', 'rejected', 'withdrawn')",
            name="ck_applications_status_valid",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("candidates.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="applied", server_default=text("'applied'"), nullable=False
    )
