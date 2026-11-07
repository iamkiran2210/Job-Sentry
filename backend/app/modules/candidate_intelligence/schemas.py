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


class AnalysisData(BaseModel):
    application_id: UUID
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
