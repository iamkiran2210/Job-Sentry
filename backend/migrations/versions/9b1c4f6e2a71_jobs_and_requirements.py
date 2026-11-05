"""Add company jobs and structured job requirements.

Revision ID: 9b1c4f6e2a71
Revises: a5475d55ef43
Create Date: 2026-11-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9b1c4f6e2a71"
down_revision: Union[str, Sequence[str], None] = "a5475d55ef43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("employment_type",
                  sa.Enum("full_time", "part_time", "contract", "temporary", "intern", name="employmenttype",
                          native_enum=False, length=30), nullable=False),
        sa.Column("work_mode", sa.Enum("onsite", "hybrid", "remote", name="workmode", native_enum=False, length=30),
                  nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("openings", sa.Integer(), nullable=False),
        sa.Column("status",
                  sa.Enum("draft", "active", "paused", "closed", "archived", name="jobstatus", native_enum=False,
                          length=30), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_company_created", "jobs", ["company_id", "created_at"], unique=False)
    op.create_index("ix_jobs_company_status", "jobs", ["company_id", "status"], unique=False)
    op.create_index(op.f("ix_jobs_company_id"), "jobs", ["company_id"], unique=False)
    op.create_index(op.f("ix_jobs_id"), "jobs", ["id"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)

    op.create_table(
        "job_requirements",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("category",
                  sa.Enum("skills", "experience", "education", "certification", "language", "responsibility", "other",
                          name="requirementcategory", native_enum=False, length=40), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("requirement_type",
                  sa.Enum("mandatory", "preferred", name="requirementtype", native_enum=False, length=30),
                  nullable=False),
        sa.Column("importance",
                  sa.Enum("low", "medium", "high", name="requirementimportance", native_enum=False, length=20),
                  nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_requirements_job_category", "job_requirements", ["job_id", "category"], unique=False)
    op.create_index("ix_job_requirements_job_type", "job_requirements", ["job_id", "requirement_type"], unique=False)
    op.create_index(op.f("ix_job_requirements_id"), "job_requirements", ["id"], unique=False)
    op.create_index(op.f("ix_job_requirements_job_id"), "job_requirements", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_requirements_job_id"), table_name="job_requirements")
    op.drop_index(op.f("ix_job_requirements_id"), table_name="job_requirements")
    op.drop_index("ix_job_requirements_job_type", table_name="job_requirements")
    op.drop_index("ix_job_requirements_job_category", table_name="job_requirements")
    op.drop_table("job_requirements")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_company_id"), table_name="jobs")
    op.drop_index("ix_jobs_company_status", table_name="jobs")
    op.drop_index("ix_jobs_company_created", table_name="jobs")
    op.drop_table("jobs")
