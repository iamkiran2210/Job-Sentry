"""Shared lightweight Pydantic output schemas for analysis, explanation, and verification AI tasks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRelevanceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rating: Literal["high", "medium", "low", "none", "insufficient_information"]
    rationale: str
    supporting_quotes: list[str]


class ExplanationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=600)
    evidence_ids: list[str]


class ExplanationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=600)
    strengths: list[ExplanationItem]
    gaps: list[ExplanationItem]


class ProjectLinkAIVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal[
        "consistent",
        "partially_consistent",
        "inconsistent",
        "parked_or_error",
        "insufficient_content",
    ]
    relevance_score: float = Field(ge=0.0, le=1.0)
    matched_claims: list[str] = Field(default_factory=list, max_length=12)
    discrepancies: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(max_length=320)


class GitHubProfileAIVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["consistent", "partially_consistent", "inconsistent", "sparse_profile"]
    alignment_score: float = Field(ge=0.0, le=1.0)
    verified_languages: list[str] = Field(default_factory=list, max_length=15)
    verified_projects: list[str] = Field(default_factory=list, max_length=10)
    discrepancies: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(max_length=320)


class PortfolioAIVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal[
        "consistent",
        "partially_consistent",
        "inconsistent",
        "parked_or_error",
        "insufficient_content",
    ]
    alignment_score: float = Field(ge=0.0, le=1.0)
    matched_skills: list[str] = Field(default_factory=list, max_length=15)
    matched_projects: list[str] = Field(default_factory=list, max_length=10)
    matched_roles: list[str] = Field(default_factory=list, max_length=6)
    discrepancies: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(max_length=320)


class LinkedInProfileAIVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["consistent", "partially_consistent", "inconsistent", "sparse_profile"]
    alignment_score: float = Field(ge=0.0, le=1.0)
    name_match: Literal["match", "partial", "mismatch", "unknown"] = "unknown"
    timeline_alignment: Literal["aligned", "minor_differences", "conflicts", "unknown"] = "unknown"
    matched_companies: list[str] = Field(default_factory=list, max_length=10)
    matched_roles: list[str] = Field(default_factory=list, max_length=10)
    matched_education: list[str] = Field(default_factory=list, max_length=6)
    matched_certifications: list[str] = Field(default_factory=list, max_length=8)
    matched_projects: list[str] = Field(default_factory=list, max_length=8)
    matched_skills: list[str] = Field(default_factory=list, max_length=15)
    discrepancies: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(max_length=320)


class DecisionAgentPanelItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: Literal["balanced", "bar_raiser", "growth_potential", "risk_guardian"]
    decision: Literal["strong_advance", "advance", "review", "hold", "pass"]
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(max_length=220)
    next_step: str = Field(max_length=120)
    key_factors: list[str] = Field(default_factory=list, max_length=3)
    risk_flags: list[str] = Field(default_factory=list, max_length=3)


class DecisionAgentPanelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[DecisionAgentPanelItem] = Field(min_length=1, max_length=4)
