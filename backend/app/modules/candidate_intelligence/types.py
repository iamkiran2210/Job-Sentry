"""Shared plain data types for the independently testable intelligence layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal
from datetime import date


VerificationStatus = Literal["passed", "needs_review", "not_verified", "failed"]


@dataclass(frozen=True)
class ScoringInputs:
    """Allowlisted immutable candidate/job data; identity/proxy fields have no slots."""
    skills: tuple[dict[str, Any], ...]
    experience: tuple[dict[str, Any], ...]
    projects: tuple[dict[str, Any], ...]
    education: tuple[dict[str, Any], ...]
    certifications: tuple[dict[str, Any], ...]
    requirements: tuple[dict[str, Any], ...]
    as_of: date


@dataclass(frozen=True)
class ScoreEvidence:
    evidence_id: str
    category: str
    signal_type: str
    value: float | None
    source_location: str | None = None
    matched_term: str | None = None
    requirement_term: str | None = None
    canonical_term: str | None = None
    alias_used: str | None = None
    match_type: str | None = None
    compared_texts: tuple[str, str] | None = None
    model_version: str | None = None
    similarity: float | None = None
    rationale: str | None = None
    supporting_quotes: tuple[str, ...] = ()
    grounded: bool | None = None
    error: str | None = None
    model_name: str | None = None
    input_hash: str | None = None


@dataclass(frozen=True)
class CategoryMatch:
    category: str
    score: Decimal | None
    status: Literal["known", "unknown", "not_applicable"] = "unknown"
    evidence_ids: tuple[str, ...] = ()
    confidence: Decimal = Decimal("0")
    coverage: Decimal = Decimal("0")


@dataclass(frozen=True)
class MandatoryResult:
    requirement_id: str
    status: Literal["met", "not_met", "unknown"]
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal | None
    score_lower_bound: Decimal | None
    score_upper_bound: Decimal | None
    categories: dict[str, CategoryMatch]
    data_completeness: Decimal
    eligibility: Literal["eligible", "needs_review", "potentially_ineligible"]
    mandatory_results: tuple[MandatoryResult, ...]
    review_signals: tuple[str, ...]
    config_snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResultData:
    check_type: str
    status: VerificationStatus
    signal: str
    details: dict[str, Any] = field(default_factory=dict)
