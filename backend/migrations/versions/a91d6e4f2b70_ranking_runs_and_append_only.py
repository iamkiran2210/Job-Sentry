"""Add ranking runs, provenance columns, and append-only history.

Revision ID: a91d6e4f2b70
Revises: f4a1b2c3d5e6
"""
from alembic import op
import sqlalchemy as sa


revision = "a91d6e4f2b70"
down_revision = "f4a1b2c3d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranking_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("filters_applied", sa.JSON(), nullable=False),
        sa.Column("scoring_version", sa.String(80), nullable=False),
        sa.Column("algorithm_version", sa.String(80), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_model_version", sa.String(80), nullable=False),
        sa.Column("llm_model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("job_requirements_hash", sa.String(64), nullable=False),
        sa.Column("scoring_config_hash", sa.String(64), nullable=False),
        sa.Column("triggered_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_ranking_run_run_id"),
    )
    op.create_index("ix_ranking_run_job_id", "ranking_run", ["job_id"])

    additions = (
        ("embedding_model", sa.String(120)),
        ("embedding_model_version", sa.String(80)),
        ("llm_model", sa.String(120)),
        ("prompt_version", sa.String(80)),
        ("job_requirements_hash", sa.String(64)),
        ("scoring_config_hash", sa.String(64)),
        ("eligibility", sa.String(32)),
        ("verification_status", sa.String(20)),
    )
    for name, type_ in additions:
        op.add_column("ranking_history", sa.Column(name, type_, nullable=True))

    # Backfill historical provenance from snapshots, preserving existing rows.
    # The immutable predecessor trigger forbids these one-time additive updates.
    op.execute("DROP TRIGGER IF EXISTS trg_ranking_history_immutable ON ranking_history")
    op.execute(sa.text("""
        UPDATE ranking_history rh SET
          embedding_model = COALESCE(provider_snapshot->>'embedding_model', 'unknown'),
          embedding_model_version = COALESCE(provider_snapshot->>'embedding_version', 'unknown'),
          llm_model = COALESCE(provider_snapshot->>'llm_model', 'unknown'),
          prompt_version = COALESCE(provider_snapshot->>'llm_prompt_version', 'unknown'),
          job_requirements_hash = COALESCE(requirements_hash, ''),
          scoring_config_hash = COALESCE(config_hash, ''),
          eligibility = COALESCE((SELECT item->>'eligibility' FROM jsonb_array_elements(ranked_items::jsonb) item
                                  WHERE item->>'application_id' = rh.application_id::text LIMIT 1), 'needs_review'),
          verification_status = COALESCE((SELECT item->'verification_statuses'->>0 FROM jsonb_array_elements(ranked_items::jsonb) item
                                         WHERE item->>'application_id' = rh.application_id::text LIMIT 1), 'not_verified')
    """))
    for name, type_ in additions:
        op.alter_column("ranking_history", name, existing_type=type_, nullable=False)

    op.create_index("ix_ranking_history_job_created_desc", "ranking_history", ["job_id", sa.text("created_at DESC")])

    op.execute("""
        CREATE FUNCTION reject_ranking_history_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ranking history is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER ranking_history_append_only
        BEFORE UPDATE OR DELETE ON ranking_history
        FOR EACH ROW EXECUTE FUNCTION reject_ranking_history_mutation()
    """)
    op.execute("""
        CREATE FUNCTION reject_ranking_run_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ranking runs are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER ranking_run_append_only
        BEFORE UPDATE OR DELETE ON ranking_run
        FOR EACH ROW EXECUTE FUNCTION reject_ranking_run_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ranking_run_append_only ON ranking_run")
    op.execute("DROP TRIGGER IF EXISTS ranking_history_append_only ON ranking_history")
    op.execute("DROP FUNCTION IF EXISTS reject_ranking_run_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reject_ranking_history_mutation()")
    op.execute("""
        CREATE TRIGGER trg_ranking_history_immutable
        BEFORE UPDATE ON ranking_history
        FOR EACH ROW EXECUTE FUNCTION prevent_ranking_history_update()
    """)
    op.drop_index("ix_ranking_history_job_created_desc", table_name="ranking_history")
    for name in ("verification_status", "eligibility", "scoring_config_hash", "job_requirements_hash", "prompt_version", "llm_model", "embedding_model_version", "embedding_model"):
        op.drop_column("ranking_history", name)
    op.drop_index("ix_ranking_run_job_id", table_name="ranking_run")
    op.drop_table("ranking_run")
