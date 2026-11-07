"""Candidate intelligence evidence, scores, verification, and ranking history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


class Vector384(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return "vector(384)"

revision = "c4e91a72b603"
down_revision = "b7d2e9a4c1f5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    has_vector = False
    if is_pg:
        # Managed PostgreSQL installations often omit the pgvector package.
        # Do not abort the whole Phase 4 migration in that case: persist
        # embeddings as JSONB until the server supports the extension.
        available = bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
        )).scalar()
        if available:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
            has_vector = True
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    vector_type = Vector384()
    if not has_vector:
        vector_type = json_type

    op.create_table("verification_results",
        sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("check_type", sa.String(48), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("signal", sa.Text(), nullable=False), sa.Column("details", json_type, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_verification_results_company_id", "verification_results", ["company_id"])
    op.create_index("ix_verification_results_application_id", "verification_results", ["application_id"])
    op.create_index("ix_verification_application_type", "verification_results", ["application_id", "check_type"])

    op.create_table("candidate_scores",
        sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("scoring_version", sa.String(80), nullable=False), sa.Column("algorithm_version", sa.String(80), nullable=False),
        sa.Column("score", sa.Numeric(10, 6)), sa.Column("category_detail", json_type, nullable=False), sa.Column("eligibility", sa.String(32), nullable=False),
        sa.Column("review_signals", json_type, nullable=False), sa.Column("config_snapshot", json_type, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "scoring_version", name="uq_candidate_score_application_version"))
    op.create_index("ix_candidate_scores_company_id", "candidate_scores", ["company_id"])
    op.create_index("ix_candidate_scores_application_id", "candidate_scores", ["application_id"])
    op.create_index("ix_candidate_score_company_application", "candidate_scores", ["company_id", "application_id"])

    op.create_table("score_evidence",
        sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("score_id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.String(64), nullable=False), sa.Column("category", sa.String(40), nullable=False), sa.Column("signal_type", sa.String(48), nullable=False),
        sa.Column("value", sa.Numeric(10, 6)), sa.Column("evidence_data", json_type, nullable=False), sa.Column("embedding", vector_type),
        sa.Column("embedding_model_name", sa.String(120)), sa.Column("embedding_model_version", sa.String(80)), sa.Column("embedding_dimension", sa.Integer()), sa.Column("embedded_text_hash", sa.String(64)),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["score_id"], ["candidate_scores.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("score_id", "evidence_id", name="uq_score_evidence_id"))
    op.create_index("ix_score_evidence_company_id", "score_evidence", ["company_id"])
    op.create_index("ix_score_evidence_score_id", "score_evidence", ["score_id"])
    op.create_index("ix_score_evidence_application_id", "score_evidence", ["application_id"])
    op.create_index("ix_score_evidence_application_category", "score_evidence", ["application_id", "category"])
    if has_vector:
        op.execute("CREATE INDEX ix_score_evidence_embedding_hnsw ON score_evidence USING hnsw (embedding vector_cosine_ops)")

    op.create_table("ranking_history",
        sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("job_id", sa.Uuid(), nullable=False), sa.Column("requirements_snapshot", json_type, nullable=False),
        sa.Column("requirements_hash", sa.String(64), nullable=False), sa.Column("ranked_items", json_type, nullable=False), sa.Column("filters_used", json_type, nullable=False),
        sa.Column("scoring_version", sa.String(80), nullable=False), sa.Column("algorithm_version", sa.String(80), nullable=False), sa.Column("config_snapshot", json_type, nullable=False), sa.Column("triggered_by", sa.Uuid()),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_ranking_history_company_id", "ranking_history", ["company_id"])
    op.create_index("ix_ranking_history_job_id", "ranking_history", ["job_id"])
    op.create_index("ix_ranking_history_job_created", "ranking_history", ["job_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    op.drop_index("ix_ranking_history_job_created", table_name="ranking_history")
    op.drop_index("ix_ranking_history_job_id", table_name="ranking_history")
    op.drop_index("ix_ranking_history_company_id", table_name="ranking_history")
    op.drop_table("ranking_history")
    if bind.dialect.name == "postgresql": op.execute("DROP INDEX IF EXISTS ix_score_evidence_embedding_hnsw")
    op.drop_index("ix_score_evidence_application_category", table_name="score_evidence")
    op.drop_index("ix_score_evidence_application_id", table_name="score_evidence")
    op.drop_index("ix_score_evidence_score_id", table_name="score_evidence")
    op.drop_index("ix_score_evidence_company_id", table_name="score_evidence")
    op.drop_table("score_evidence")
    op.drop_index("ix_candidate_score_company_application", table_name="candidate_scores")
    op.drop_index("ix_candidate_scores_application_id", table_name="candidate_scores")
    op.drop_index("ix_candidate_scores_company_id", table_name="candidate_scores")
    op.drop_table("candidate_scores")
    op.drop_index("ix_verification_application_type", table_name="verification_results")
    op.drop_index("ix_verification_results_application_id", table_name="verification_results")
    op.drop_index("ix_verification_results_company_id", table_name="verification_results")
    op.drop_table("verification_results")
    # The extension may be shared by other applications; leave it installed.
