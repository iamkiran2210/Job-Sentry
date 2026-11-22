import uuid

from app.models.base import BaseModel
from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")


class IdentitySuggestion(BaseModel):
    """Possible same-person pairs that need HUMAN review. Never merged automatically."""

    __tablename__ = "identity_suggestions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    other_candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_resume_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    strength: Mapped[str] = mapped_column(String(10), nullable=False)  # strong | weak
    reasons: Mapped[list] = mapped_column(JsonType, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)

    __table_args__ = (
        UniqueConstraint("candidate_id", "other_candidate_id", name="uq_identity_pair"),
        CheckConstraint("candidate_id <> other_candidate_id", name="ck_identity_distinct"),
    )
