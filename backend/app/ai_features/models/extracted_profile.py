import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

JsonType = JSON().with_variant(JSONB(), "postgresql")


class ExtractedProfile(BaseModel):
    """Derived data, stored apart from the original file. Everything here is an unverified resume claim."""

    __tablename__ = "extracted_profiles"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_text: Mapped[str | None] = mapped_column(
        Text
    )  # parsed/OCR text: retry cache + evidence base
    extraction_method: Mapped[str | None] = mapped_column(String(24))
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    parse_warnings: Mapped[list | None] = mapped_column(JsonType)

    profile_data: Mapped[dict | None] = mapped_column(
        JsonType
    )  # validated + grounded ExtractedProfileData
    extraction_warnings: Mapped[list | None] = mapped_column(JsonType)
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    ai_engine: Mapped[str | None] = mapped_column(String(24))  # pydantic_ai | dspy
    ai_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(
        String(80)
    )  # includes the compiled-artifact id when used
    schema_version: Mapped[int | None] = mapped_column(Integer)
