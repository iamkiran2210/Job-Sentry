"""API shapes for resume ingestion, applications and candidates (responses are wrapped by success_response)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.ai_features.schemas.resume_extraction import ExtractedProfileData


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UploadItem(BaseModel):
    filename: str
    status: Literal["accepted", "duplicate", "rejected"]
    resume_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    processing_status: str | None = None
    reason_code: str | None = None
    detail: str | None = None


class UploadResult(BaseModel):
    results: list[UploadItem]


class ResumeStatusOut(BaseModel):
    resume_id: uuid.UUID
    application_id: uuid.UUID
    status: str
    attempt_count: int
    failure_code: str | None
    failure_message: str | None
    retryable: bool
    updated_at: datetime
    completed_at: datetime | None


class ExtractedProfileOut(BaseModel):
    data_origin: Literal["resume_claims_unverified"] = "resume_claims_unverified"
    resume_id: uuid.UUID
    data: ExtractedProfileData
    overall_confidence: float | None
    extraction_method: str | None
    ocr_used: bool
    ocr_confidence: float | None
    warnings: list[str]
    ai_engine: str | None
    ai_model: str | None
    prompt_version: str | None
    schema_version: int | None


class ResumeOut(_Out):
    id: uuid.UUID
    job_id: uuid.UUID
    application_id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    failure_code: str | None
    failure_message: str | None
    duplicate_of_resume_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None
    profile: ExtractedProfileOut | None = None


class ApplicationOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID | None
    status: str
    created_at: datetime
    resumes: list[ResumeOut]


class IdentitySuggestionOut(_Out):
    id: uuid.UUID
    candidate_id: uuid.UUID
    other_candidate_id: uuid.UUID
    strength: str
    reasons: list[str]
    status: str


ApplicantStatus = Literal[
    "applied",
    "processing",
    "analyzed",
    "shortlisted",
    "rejected",
    "withdrawn",
]

ApplicantResumeStatus = Literal[
    "uploaded",
    "queued",
    "extracting",
    "analyzing",
    "completed",
    "failed",
]


class ApplicationBrief(BaseModel):
    application_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    resume_id: uuid.UUID
    resume_status: str
    created_at: datetime


class ApplicantCandidateBrief(BaseModel):
    id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None


class JobApplicantOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID | None = None
    status: ApplicantStatus
    created_at: datetime
    candidate: ApplicantCandidateBrief | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    resume_id: uuid.UUID | None = None
    resume_status: ApplicantResumeStatus | None = None
    original_filename: str | None = None
    overall_confidence: float | None = None
    latest_profile: ExtractedProfileOut | None = None


class CandidateOut(BaseModel):
    id: uuid.UUID
    full_name: str | None
    email: str | None
    phone: str | None
    created_at: datetime
    applications: list[ApplicationBrief]
    latest_profile: ExtractedProfileOut | None
    identity_review: list[IdentitySuggestionOut]  # company members only


class CandidateUpdateIn(BaseModel):
    """Manual recruiter edits to a candidate's identity and extracted profile claims."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    skills: list[str] | None = None
    employment: list[dict] | None = None
    education: list[dict] | None = None
    projects: list[dict] | None = None
    certifications: list[dict] | None = None


class CandidateDeletedOut(BaseModel):
    candidate_id: uuid.UUID
    deleted: bool = True
    clean_deleted: bool = False
    applications_cleaned: int = 0
    resumes_deleted: int = 0
    scores_deleted: int = 0
    verifications_deleted: int = 0
    audit_records_deleted: int = 0


class ApplicationDeletedOut(BaseModel):
    application_id: uuid.UUID
    deleted: bool = True
    resumes_deleted: int = 0
    audit_preserved: bool = False
