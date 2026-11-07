import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Application(BaseModel):
    """Links one candidate to one job. candidate_id stays NULL until resume extraction resolves identity.
    Phase 5 owns the full status lifecycle; Phase 3 only uses 'processing' -> 'applied'."""

    __tablename__ = "applications"

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
        String(20), default="processing", nullable=False
    )

    # NULLs are distinct, so unlinked applications never collide; a candidate can apply to a job once.
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", name="uq_applications_candidate_job"
        ),
    )
