"""HTTP contracts for the candidate intelligence API."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.utils.responses import ApiResponse


VerificationStatus = Literal["passed", "needs_review", "not_verified", "failed"]
Eligibility = Literal["eligible", "needs_review", "potentially_ineligible"]


class VerificationCheck(BaseModel):
    check_type: str
    status: VerificationStatus
    signal: str
    details: dict[str, Any] = Field(default_factory=dict)


class VerifyData(BaseModel):
    overall_status: VerificationStatus
    checks: list[VerificationCheck]
    disclaimer: str


class CategoryAnalysis(BaseModel):
    status: Literal["known", "unknown", "not_applicable"]
    match: float | None = None
    weight: float
    weighted_contribution: float | None = None
    components: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CandidateDetail(BaseModel):
    id: UUID | None
    display_name: str | None
    email: str | None
    phone: str | None
    links: dict[str, str | None]
    profile: dict[str, Any]


class ResumeDetail(BaseModel):
    file_name: str
    content_type: str
    size_bytes: int
    page_count: int | None
    uploaded_at: str
    parse_status: str
    parser_version: str | None
    extraction_version: str | int | None
    content_hash_prefix: str


class ApplicationDetail(BaseModel):
    id: UUID
    job_id: UUID
    job_title: str
    status: str
    status_history: list[dict[str, Any]]


class ScoreDetail(BaseModel):
    total: float | None
    lower_bound: float | None
    upper_bound: float | None
    data_completeness: float
    eligibility: Eligibility
    mandatory_results: list[dict[str, Any]]
    review_signals: list[str]
    categories: dict[str, CategoryAnalysis]
    rank: int | None
    ranking_run_id: UUID | None


class VerificationDetail(BaseModel):
    overall_status: VerificationStatus
    checks: list[VerificationCheck]


class ExplanationDetail(BaseModel):
    deterministic_summary: list[str]
    ai_summary: dict[str, Any] | None
    ai_status: Literal["available", "pending", "failed", "unavailable"]
    disclaimer: str


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_ids: list[UUID] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def unique_application_ids(self):
        if len(set(self.application_ids)) != len(self.application_ids):
            raise ValueError("application_ids must be unique")
        return self


class ComparisonData(BaseModel):
    applications: list[dict[str, Any]]
    categories: dict[str, list[dict[str, Any]]]
    skill_coverage: list[dict[str, Any]]
    mandatory_coverage: list[dict[str, Any]]
    differences: list[dict[str, Any]]
    disclaimers: list[str]


CompareResponse = ApiResponse[ComparisonData]


class AnalysisData(BaseModel):
    application_id: UUID
    status_note: str | None = None
    score_id: UUID | None
    score: float | None
    score_percent: float | None
    score_lower_bound: float | None
    score_upper_bound: float | None
    data_completeness: float | None
    mandatory_results: list[dict[str, Any]]
    categories: dict[str, CategoryAnalysis]
    eligibility: Eligibility | None
    review_signals: list[str]
    evidence: list[dict[str, Any]]
    analysis_summary: dict[str, str]
    verification: list[VerificationCheck]
    scoring_version: str | None
    algorithm_version: str | None
    config_snapshot: dict[str, Any] | None
    candidate: CandidateDetail
    resume: ResumeDetail | None
    application: ApplicationDetail
    verification_detail: VerificationDetail
    score_detail: ScoreDetail | None
    evidence_groups: list[dict[str, Any]]
    explanation: ExplanationDetail


class RankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    eligibility: Eligibility | None = None
    min_score: float | None = Field(default=None, ge=0, le=100)
    max_score: float | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    verification_status: VerificationStatus | None = None
    scoring_version: str | None = None
    application_ids: list[UUID] | None = None
    force_rescore: bool = False

    @model_validator(mode="after")
    def validate_score_range(self):
        if self.min_score is not None and self.max_score is not None and self.min_score > self.max_score:
            raise ValueError("min_score must be less than or equal to max_score")
        return self


class RankedItem(BaseModel):
    application_id: UUID
    application_created_at: str
    score: float | None
    eligibility: Eligibility
    skills_score: float | None = None
    data_completeness: float
    status: str
    verification_statuses: list[str] = Field(default_factory=list)
    rank: int


class RankData(BaseModel):
    run_id: UUID
    count: int
    total_count: int
    offset: int
    limit: int
    scoring_version: str
    algorithm_version: str
    config_hash: str | None = None
    provider_snapshot: dict[str, Any] = Field(default_factory=dict)
    items: list[RankedItem]


class RankingPage(BaseModel):
    run_id: UUID | None
    total_count: int
    offset: int
    limit: int
    items: list[RankedItem]
    scoring_version: str | None = None
    algorithm_version: str | None = None
    filters_applied: dict[str, Any] = Field(default_factory=dict)


class RankingRunSummary(BaseModel):
    run_id: UUID
    job_id: UUID
    job_requirements_hash: str
    filters_applied: dict[str, Any]
    scoring_version: str
    algorithm_version: str
    config_hash: str | None = None
    provider_snapshot: dict[str, Any] = Field(default_factory=dict)
    triggered_by: UUID | None
    created_at: str
    count: int


class RankingHistoryPage(BaseModel):
    items: list[RankingRunSummary]
    offset: int
    limit: int


VerifyResponse = ApiResponse[VerifyData]
AnalysisResponse = ApiResponse[AnalysisData]
RankResponse = ApiResponse[RankData]
RankingResponse = ApiResponse[RankingPage]
RankingHistoryResponse = ApiResponse[RankingHistoryPage]
