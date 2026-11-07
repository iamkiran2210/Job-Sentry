import uuid

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Candidate(BaseModel):
    """A person record owned by one company. Identity fields are resume CLAIMS, not verified facts."""

    __tablename__ = "candidates"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    normalized_name: Mapped[str | None] = mapped_column(String(300))
    normalized_email: Mapped[str | None] = mapped_column(String(320))
    normalized_phone: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (
        Index("ix_candidates_company_email", "company_id", "normalized_email"),
        Index("ix_candidates_company_phone", "company_id", "normalized_phone"),
        Index("ix_candidates_company_name", "company_id", "normalized_name"),
    )
