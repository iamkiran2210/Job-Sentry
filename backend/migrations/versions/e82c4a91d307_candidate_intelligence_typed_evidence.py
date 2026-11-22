"""Add typed evidence metadata and ranking provenance snapshots.

Revision ID: e82c4a91d307
Revises: d6f3a810bc42
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e82c4a91d307"
down_revision = "d6f3a810bc42"
branch_labels = None
depends_on = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.add_column("candidate_scores", sa.Column("as_of_date", sa.Date(), nullable=True))
    op.add_column("ranking_history", sa.Column("config_hash", sa.String(64), nullable=True))
    op.add_column(
        "ranking_history",
        sa.Column("provider_snapshot", JsonType, nullable=False, server_default="{}"),
    )

    evidence_columns = [
        sa.Column("source_location", sa.Text(), nullable=True),
        sa.Column("matched_term", sa.Text(), nullable=True),
        sa.Column("requirement_term", sa.Text(), nullable=True),
        sa.Column("canonical_term", sa.Text(), nullable=True),
        sa.Column("alias_used", sa.Text(), nullable=True),
        sa.Column("match_type", sa.String(32), nullable=True),
        sa.Column("compared_texts", JsonType, nullable=True),
        sa.Column("model_version", sa.String(120), nullable=True),
        sa.Column("similarity", sa.Numeric(10, 6), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("supporting_quotes", JsonType, nullable=False, server_default="[]"),
        sa.Column("grounded", sa.Boolean(), nullable=True),
        sa.Column("error", sa.String(120), nullable=True),
        sa.Column("model_name", sa.String(120), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("is_proof", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]
    for column in evidence_columns:
        op.add_column("score_evidence", column)

    # d6 introduced these JSON fields before the ORM standardized PostgreSQL
    # storage on JSONB. Convert them here so a fresh database matches metadata.
    op.alter_column("candidate_scores", "mandatory_results", server_default=None)
    op.execute(
        "ALTER TABLE candidate_scores ALTER COLUMN mandatory_results TYPE JSONB USING mandatory_results::jsonb"
    )
    op.alter_column("candidate_scores", "mandatory_results", server_default=sa.text("'[]'::jsonb"))
    op.alter_column("ranking_history", "tie_break_key", server_default=None)
    op.execute(
        "ALTER TABLE ranking_history ALTER COLUMN tie_break_key TYPE JSONB USING tie_break_key::jsonb"
    )
    op.alter_column("ranking_history", "tie_break_key", server_default=sa.text("'{}'::jsonb"))
    op.execute("ALTER TABLE candidate_scores ALTER COLUMN job_id SET NOT NULL")
    op.execute("ALTER TABLE ranking_history ALTER COLUMN run_id SET NOT NULL")

    for table in ("candidate_scores", "score_evidence", "verification_results", "ranking_history"):
        op.create_index(f"ix_{table}_id", table, ["id"])
    with op.batch_alter_table("score_evidence") as batch:
        batch.create_check_constraint(
            "ck_score_evidence_value_range", "value IS NULL OR (value >= 0 AND value <= 1)"
        )
        batch.create_check_constraint(
            "ck_score_evidence_similarity_range",
            "similarity IS NULL OR (similarity >= -1 AND similarity <= 1)",
        )
    with op.batch_alter_table("candidate_scores") as batch:
        batch.create_check_constraint(
            "ck_candidate_score_range", "score IS NULL OR (score >= 0 AND score <= 100)"
        )
        batch.create_check_constraint(
            "ck_candidate_score_lower_range",
            "score_lower_bound IS NULL OR (score_lower_bound >= 0 AND score_lower_bound <= 100)",
        )
        batch.create_check_constraint(
            "ck_candidate_score_upper_range",
            "score_upper_bound IS NULL OR (score_upper_bound >= 0 AND score_upper_bound <= 100)",
        )
        batch.create_check_constraint(
            "ck_candidate_score_completeness_range",
            "data_completeness >= 0 AND data_completeness <= 1",
        )
        batch.create_check_constraint(
            "ck_candidate_score_eligibility_valid",
            "eligibility IN ('eligible', 'needs_review', 'potentially_ineligible')",
        )
    with op.batch_alter_table("verification_results") as batch:
        batch.create_check_constraint(
            "ck_verification_status_valid",
            "status IN ('passed', 'needs_review', 'not_verified', 'failed')",
        )
    with op.batch_alter_table("ranking_history") as batch:
        batch.create_unique_constraint(
            "uq_ranking_history_run_application", ["job_id", "run_id", "application_id"]
        )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION prevent_ranking_history_update() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'ranking history rows are immutable'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute(
            "CREATE TRIGGER trg_ranking_history_immutable BEFORE UPDATE ON ranking_history FOR EACH ROW EXECUTE FUNCTION prevent_ranking_history_update()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_ranking_history_immutable BEFORE UPDATE ON ranking_history BEGIN SELECT RAISE(ABORT, 'ranking history rows are immutable'); END"
        )


def downgrade():
    for table in ("candidate_scores", "score_evidence", "verification_results", "ranking_history"):
        op.drop_index(f"ix_{table}_id", table_name=table)
    op.execute("ALTER TABLE candidate_scores ALTER COLUMN job_id DROP NOT NULL")
    op.execute("ALTER TABLE ranking_history ALTER COLUMN run_id DROP NOT NULL")
    op.alter_column("ranking_history", "tie_break_key", server_default=None)
    op.execute(
        "ALTER TABLE ranking_history ALTER COLUMN tie_break_key TYPE JSON USING tie_break_key::json"
    )
    op.alter_column("ranking_history", "tie_break_key", server_default=sa.text("'{}'::json"))
    op.alter_column("candidate_scores", "mandatory_results", server_default=None)
    op.execute(
        "ALTER TABLE candidate_scores ALTER COLUMN mandatory_results TYPE JSON USING mandatory_results::json"
    )
    op.alter_column("candidate_scores", "mandatory_results", server_default=sa.text("'[]'::json"))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_ranking_history_immutable ON ranking_history")
        op.execute("DROP FUNCTION IF EXISTS prevent_ranking_history_update()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ranking_history_immutable")
    with op.batch_alter_table("ranking_history") as batch:
        batch.drop_constraint("uq_ranking_history_run_application", type_="unique")
    with op.batch_alter_table("candidate_scores") as batch:
        batch.drop_constraint("ck_candidate_score_eligibility_valid", type_="check")
        batch.drop_constraint("ck_candidate_score_completeness_range", type_="check")
        batch.drop_constraint("ck_candidate_score_upper_range", type_="check")
        batch.drop_constraint("ck_candidate_score_lower_range", type_="check")
        batch.drop_constraint("ck_candidate_score_range", type_="check")
    with op.batch_alter_table("verification_results") as batch:
        batch.drop_constraint("ck_verification_status_valid", type_="check")
    with op.batch_alter_table("score_evidence") as batch:
        batch.drop_constraint("ck_score_evidence_similarity_range", type_="check")
        batch.drop_constraint("ck_score_evidence_value_range", type_="check")
    for name in (
            "is_proof",
            "input_hash",
            "model_name",
            "error",
            "grounded",
            "supporting_quotes",
            "rationale",
            "similarity",
            "model_version",
            "compared_texts",
            "match_type",
            "alias_used",
            "canonical_term",
            "requirement_term",
            "matched_term",
            "source_location",
    ):
        op.drop_column("score_evidence", name)
    op.drop_column("ranking_history", "provider_snapshot")
    op.drop_column("ranking_history", "config_hash")
    op.drop_column("candidate_scores", "as_of_date")
