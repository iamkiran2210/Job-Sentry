"""Configuration for Candidate Intelligence Engine (Phase 4).

All settings are environment-driven with prefix INTELLIGENCE_.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CandidateIntelligenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTELLIGENCE_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    # Versions
    scoring_version: str = "v1.4.0"
    algorithm_version: str = "v1.4.0"

    # Category Weights (must sum to 1.0)
    weight_skills: float = 0.40
    weight_experience: float = 0.25
    weight_projects: float = 0.20
    weight_education: float = 0.10
    weight_certifications: float = 0.05

    # Evidence Signal Weights
    weight_exact_match: float = 1.0
    weight_alias_match: float = 0.90
    weight_semantic_match: float = 0.65  # lower evidential weight than exact
    weight_github_language: float = 0.50
    weight_llm_relevance: float = 0.85

    # Canonical skill normalization aliases. Keep this deterministic and versioned
    # with scoring_version when changing behavior.
    skill_aliases: dict[str, str] = Field(default_factory=lambda: {
        "node.js": "nodejs", "node js": "nodejs", "node": "nodejs",
        "js": "javascript", "ts": "typescript", "postgres": "postgresql",
        "react.js": "react", "reactjs": "react", "py": "python",
    })

    # Semantic Matching Configuration
    semantic_similarity_threshold: float = 0.60
    semantic_min: float = 0.55
    semantic_full: float = 0.85
    semantic_credit_cap: float = 0.60
    semantic_similarity_bands: dict[str, float] = Field(default_factory=lambda: {
        "low": 0.60, "medium": 0.75, "high": 0.90,
    })
    semantic_model_name: str = "all-MiniLM-L6-v2"
    semantic_model_version: str = "1.0.0"
    embedding_dimension: int = 384
    embedding_provider: Literal["mock", "sentence_transformers"] = "mock"
    github_evidence_enabled: bool = False
    github_max_repositories: int = 20
    github_timeout_seconds: float = 4.0

    # LLM Relevance Analyzer Configuration
    llm_provider: Literal["mock", "pydantic_ai"] = "mock"
    llm_model: str = "heuristic"
    llm_timeout_seconds: float = 30.0
    llm_retries: int = 1
    llm_prompt_version: str = "relevance-v1"
    relevance_scores: dict[str, float] = Field(default_factory=lambda: {
        "high": 1.0, "medium": 0.6, "low": 0.25, "none": 0.0,
    })

    # Verification Configuration
    reachability_check_enabled: bool = False
    reachability_timeout_seconds: float = 2.0
    email_check_enabled: bool = True
    phone_region: str | None = None
    completeness_review_threshold: float = 0.80
    completeness_fail_threshold: float = 0.50
    timeline_overlap_tolerance_months: int = 1
    timeline_gap_threshold_months: int = 12
    duplicate_scope: Literal["job", "company"] = "company"

    # Missing Data Policy ("renormalize" or "penalize")
    missing_data_policy: str = "renormalize"
    low_completeness_threshold: float = 0.70


@lru_cache
def get_intelligence_settings() -> CandidateIntelligenceSettings:
    return CandidateIntelligenceSettings()
