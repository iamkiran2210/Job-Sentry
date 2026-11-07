from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, Uuid, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Vector(UserDefinedType):
    """pgvector on PostgreSQL, JSON text storage on SQLite test databases."""
    cache_ok = True

    def __init__(self, dimension: int = 384): self.dimension = dimension
    def get_col_spec(self, **kw): return f"vector({self.dimension})"

    def bind_processor(self, dialect):
        if dialect.name != "postgresql":
            return None
        def serialize(value):
            if value is None or isinstance(value, str):
                return value
            return "[" + ",".join(str(float(component)) for component in value) + "]"
        return serialize

    def result_processor(self, dialect, coltype):
        if dialect.name != "postgresql":
            return None
        def deserialize(value):
            if value is None or isinstance(value, list):
                return value
            return [float(component) for component in value.strip("[]").split(",")]
        return deserialize


@compiles(Vector, "sqlite")
def _sqlite_vector(_type, _compiler, **_kw): return "JSON"


class VerificationResult(BaseModel):
    __tablename__ = "verification_results"
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    checker_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    __table_args__ = (CheckConstraint("status IN ('passed', 'needs_review', 'not_verified', 'failed')", name="ck_verification_status_valid"),
                      Index("ix_verification_application_type", "application_id", "check_type"))


class CandidateScore(BaseModel):
    __tablename__ = "candidate_scores"
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    scoring_version: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(10, 6))
    score_lower_bound: Mapped[float | None] = mapped_column(Numeric(5, 2))
    score_upper_bound: Mapped[float | None] = mapped_column(Numeric(5, 2))
    data_completeness: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    mandatory_results: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    as_of_date: Mapped[date | None] = mapped_column(Date)
    category_detail: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    eligibility: Mapped[str] = mapped_column(String(32), nullable=False)
    review_signals: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    __table_args__ = (UniqueConstraint("application_id", "job_id", "scoring_version", "inputs_hash", name="uq_candidate_score_inputs_version"),
                      CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_candidate_score_range"),
                      CheckConstraint("score_lower_bound IS NULL OR (score_lower_bound >= 0 AND score_lower_bound <= 100)", name="ck_candidate_score_lower_range"),
                      CheckConstraint("score_upper_bound IS NULL OR (score_upper_bound >= 0 AND score_upper_bound <= 100)", name="ck_candidate_score_upper_range"),
                      CheckConstraint("data_completeness >= 0 AND data_completeness <= 1", name="ck_candidate_score_completeness_range"),
                      CheckConstraint("eligibility IN ('eligible', 'needs_review', 'potentially_ineligible')", name="ck_candidate_score_eligibility_valid"),
                      Index("ix_candidate_score_company_application", "company_id", "application_id"))


class ScoreEvidenceRecord(BaseModel):
    __tablename__ = "score_evidence"
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    score_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("candidate_scores.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(10, 6))
    evidence_data: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    source_location: Mapped[str | None] = mapped_column(Text)
    matched_term: Mapped[str | None] = mapped_column(Text)
    requirement_term: Mapped[str | None] = mapped_column(Text)
    canonical_term: Mapped[str | None] = mapped_column(Text)
    alias_used: Mapped[str | None] = mapped_column(Text)
    match_type: Mapped[str | None] = mapped_column(String(32))
    compared_texts: Mapped[list | None] = mapped_column(JsonType)
    model_version: Mapped[str | None] = mapped_column(String(120))
    similarity: Mapped[float | None] = mapped_column(Numeric(10, 6))
    rationale: Mapped[str | None] = mapped_column(Text)
    supporting_quotes: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, server_default="false")
    error: Mapped[str | None] = mapped_column(String(120))
    model_name: Mapped[str | None] = mapped_column(String(120))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    is_proof: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    embedding: Mapped[list | None] = mapped_column(Vector(384))
    embedding_model_name: Mapped[str | None] = mapped_column(String(120))
    embedding_model_version: Mapped[str | None] = mapped_column(String(80))
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    embedded_text_hash: Mapped[str | None] = mapped_column(String(64))
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    llm_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    source_start: Mapped[int | None] = mapped_column(Integer)
    source_end: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("score_id", "evidence_id", name="uq_score_evidence_id"),
                      CheckConstraint("category IN ('skills', 'experience', 'projects', 'education', 'certifications')", name="ck_score_evidence_category_valid"),
                      CheckConstraint("signal_type IN ('exact_skill_match', 'alias_skill_match', 'semantic_similarity', 'llm_relevance', 'github_language_signal', 'rule_based_match')", name="ck_score_evidence_signal_type_valid"),
                      CheckConstraint("value IS NULL OR (value >= 0 AND value <= 1)", name="ck_score_evidence_value_range"),
                      CheckConstraint("similarity IS NULL OR (similarity >= -1 AND similarity <= 1)", name="ck_score_evidence_similarity_range"),
                      CheckConstraint("signal_type <> 'semantic_similarity' OR (similarity IS NOT NULL AND embedding_model IS NOT NULL AND embedding_model_version IS NOT NULL AND embedding_dim IS NOT NULL)", name="ck_score_evidence_semantic_metadata"),
                      CheckConstraint("signal_type <> 'llm_relevance' OR (llm_model IS NOT NULL AND prompt_version IS NOT NULL AND input_hash IS NOT NULL)", name="ck_score_evidence_llm_metadata"),
                      CheckConstraint("signal_type NOT IN ('exact_skill_match', 'alias_skill_match') OR (matched_term IS NOT NULL AND canonical_term IS NOT NULL)", name="ck_score_evidence_exact_terms"),
                      CheckConstraint("source_start IS NULL OR source_end IS NULL OR source_end >= source_start", name="ck_score_evidence_source_range"),
                      CheckConstraint("grounded IS NOT NULL", name="ck_score_evidence_grounded_not_null"),
                      CheckConstraint("NOT (is_proof AND signal_type IN ('semantic_similarity', 'llm_relevance'))", name="ck_score_evidence_no_semantic_proof"),
                      Index("ix_score_evidence_application_category", "application_id", "category"))


class RankingHistory(BaseModel):
    __tablename__ = "ranking_history"
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    candidate_score_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("candidate_scores.id", ondelete="SET NULL"))
    rank: Mapped[int | None] = mapped_column(Integer)
    total_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    tie_break_key: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    requirements_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    requirements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ranked_items: Mapped[list] = mapped_column(JsonType, nullable=False)
    filters_used: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    scoring_version: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    provider_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    job_requirements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    eligibility: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (UniqueConstraint("job_id", "run_id", "application_id", name="uq_ranking_history_run_application"),
                      Index("ix_ranking_history_job_created", "job_id", "created_at"),
                      Index("ix_ranking_history_job_run_rank", "job_id", "run_id", "rank"),
                      Index("ix_ranking_history_job_created_desc", "job_id", text("created_at DESC")))


class RankingRun(BaseModel):
    __tablename__ = "ranking_run"
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    counts: Mapped[dict[str, int]] = mapped_column(JsonType, nullable=False)
    filters_applied: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    job_requirements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
