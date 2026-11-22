"""ORM -> response-schema helpers shared by the resume and candidate routers."""

from __future__ import annotations

from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.ai_features.schemas.resume import (
    ExtractedProfileOut,
    ResumeOut,
    ResumeStatusOut,
)
from app.ai_features.schemas.resume_extraction import ExtractedProfileData


def profile_out(p: ExtractedProfile) -> ExtractedProfileOut:
    return ExtractedProfileOut(
        resume_id=p.resume_id,
        data=ExtractedProfileData.model_validate(p.profile_data),
        overall_confidence=p.overall_confidence,
        extraction_method=p.extraction_method,
        ocr_used=p.ocr_used,
        ocr_confidence=p.ocr_confidence,
        warnings=[*(p.parse_warnings or []), *(p.extraction_warnings or [])],
        ai_engine=p.ai_engine,
        ai_model=p.ai_model,
        prompt_version=p.prompt_version,
        schema_version=p.schema_version,
    )


def resume_out(r: Resume, p: ExtractedProfile | None = None) -> ResumeOut:
    out = ResumeOut.model_validate(r)
    out.profile = profile_out(p) if p else None
    return out


def status_out(r: Resume) -> ResumeStatusOut:
    return ResumeStatusOut(
        resume_id=r.id,
        application_id=r.application_id,
        status=r.status,
        attempt_count=r.attempt_count,
        failure_code=r.failure_code,
        failure_message=r.failure_message,
        retryable=r.status in ("failed", "uploaded"),
        updated_at=r.updated_at,
        completed_at=r.completed_at,
    )
