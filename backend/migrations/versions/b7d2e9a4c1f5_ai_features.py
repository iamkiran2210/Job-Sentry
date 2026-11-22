"""resume ingestion: candidates, applications, resumes, extracted_profiles, identity_suggestions

Revision ID: b7d2e9a4c1f5
Revises: 4c8d6f1a2e73
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7d2e9a4c1f5"
down_revision = "4c8d6f1a2e73"  # company_and_job_access (current head per PROJECT_GUIDE.md); verify with `alembic heads`
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _base():
    return [
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _fk(name, target, nullable=False, ondelete="CASCADE", index=True):
    return sa.Column(
        name,
        sa.Uuid,
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


def upgrade() -> None:
    op.create_table(
        "candidates",
        *_base(),
        _fk("company_id", "companies.id"),
        sa.Column("full_name", sa.String(300)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(64)),
        sa.Column("normalized_name", sa.String(300)),
        sa.Column("normalized_email", sa.String(320)),
        sa.Column("normalized_phone", sa.String(20)),
    )
    op.create_index("ix_candidates_company_email", "candidates", ["company_id", "normalized_email"])
    op.create_index("ix_candidates_company_phone", "candidates", ["company_id", "normalized_phone"])
    op.create_index("ix_candidates_company_name", "candidates", ["company_id", "normalized_name"])

    op.create_table(
        "applications",
        *_base(),
        _fk("company_id", "companies.id"),
        _fk("job_id", "jobs.id"),
        _fk("candidate_id", "candidates.id", nullable=True, ondelete="SET NULL"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("candidate_id", "job_id", name="uq_applications_candidate_job"),
    )

    op.create_table(
        "resumes",
        *_base(),
        _fk("company_id", "companies.id"),
        _fk("job_id", "jobs.id"),
        _fk("application_id", "applications.id"),
        _fk("uploaded_by", "users.id", nullable=True, ondelete="SET NULL", index=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(8), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_backend", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(32)),
        sa.Column("failure_code", sa.String(32)),
        sa.Column("failure_message", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duplicate_of_resume_id", sa.Uuid),
        sa.UniqueConstraint("company_id", "job_id", "sha256", name="uq_resumes_company_job_sha256"),
        sa.CheckConstraint(
            "status in ('uploaded','queued','extracting','analyzing','completed','failed')",
            name="ck_resumes_status",
        ),
    )
    op.create_index("ix_resumes_company_sha256", "resumes", ["company_id", "sha256"])

    op.create_table(
        "extracted_profiles",
        *_base(),
        sa.Column(
            "resume_id",
            sa.Uuid,
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        _fk("company_id", "companies.id"),
        sa.Column("source_text", sa.Text),
        sa.Column("extraction_method", sa.String(24)),
        sa.Column("page_count", sa.Integer),
        sa.Column("ocr_used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ocr_confidence", sa.Float),
        sa.Column("parse_warnings", JSON),
        sa.Column("profile_data", JSON),
        sa.Column("extraction_warnings", JSON),
        sa.Column("overall_confidence", sa.Float),
        sa.Column("ai_engine", sa.String(24)),
        sa.Column("ai_model", sa.String(120)),
        sa.Column("prompt_version", sa.String(80)),
        sa.Column("schema_version", sa.Integer),
    )

    op.create_table(
        "identity_suggestions",
        *_base(),
        _fk("company_id", "companies.id"),
        _fk("candidate_id", "candidates.id"),
        _fk("other_candidate_id", "candidates.id"),
        sa.Column("source_resume_id", sa.Uuid),
        sa.Column("strength", sa.String(10), nullable=False),
        sa.Column("reasons", JSON, nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.UniqueConstraint("candidate_id", "other_candidate_id", name="uq_identity_pair"),
        sa.CheckConstraint("candidate_id <> other_candidate_id", name="ck_identity_distinct"),
    )


def downgrade() -> None:
    for t in (
        "identity_suggestions",
        "extracted_profiles",
        "resumes",
        "applications",
        "candidates",
    ):
        op.drop_table(t)
