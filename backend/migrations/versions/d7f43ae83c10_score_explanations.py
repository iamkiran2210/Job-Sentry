"""Persist generated explanations separately from deterministic scores.

Revision ID: d7f43ae83c10
Revises: c2f6b1a8d904
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d7f43ae83c10"
down_revision = "c2f6b1a8d904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "score_explanation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_score_id", sa.Uuid(), nullable=False),
        sa.Column("generator_model", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "status IN ('available', 'pending', 'failed', 'unavailable')",
            name="ck_score_explanation_status_valid",
        ),
        sa.ForeignKeyConstraint(["candidate_score_id"], ["candidate_scores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_score_explanation_candidate_score_id", "score_explanation", ["candidate_score_id"])
    op.create_index("ix_score_explanation_score_created", "score_explanation", ["candidate_score_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_score_explanation_score_created", table_name="score_explanation")
    op.drop_index("ix_score_explanation_candidate_score_id", table_name="score_explanation")
    op.drop_table("score_explanation")
