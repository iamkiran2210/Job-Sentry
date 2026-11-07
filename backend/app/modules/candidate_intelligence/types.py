"""Shared plain data types for the independently testable intelligence layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal, Mapping
from datetime import date
from types import MappingProxyType


VerificationStatus = Literal["passed", "needs_review", "not_verified", "failed"]


@dataclass(frozen=True)
class ScoringInputs:
    """Allowlisted immutable candidate/job data; identity/proxy fields have no slots."""
    skills: tuple[Mapping[str, Any], ...]
    experience: tuple[Mapping[str, Any], ...]
    projects: tuple[Mapping[str, Any], ...]
    education: tuple[Mapping[str, Any], ...]
    certifications: tuple[Mapping[str, Any], ...]
    requirements: tuple[Mapping[str, Any], ...]
    as_of: date

    def __post_init__(self) -> None:
        for field_name in ("skills", "experience", "projects", "education", "certifications", "requirements"):
            object.__setattr__(self, field_name, tuple(_freeze(item) for item in getattr(self, field_name)))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


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
    embedding: tuple[float, ...] | None = None
    embedding_model: str | None = None
    embedding_model_version: str | None = None
    embedding_dim: int | None = None
    llm_model: str | None = None
    prompt_version: str | None = None
    source_start: int | None = None
    source_end: int | None = None


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
