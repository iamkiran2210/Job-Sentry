"""Add the application status workflow and immutable history.

Revision ID: c2f6b1a8d904
Revises: a91d6e4f2b70
"""
from alembic import op
import sqlalchemy as sa


revision = "c2f6b1a8d904"
down_revision = "a91d6e4f2b70"
branch_labels = None
depends_on = None


STATUSES = "'applied', 'processing', 'analyzed', 'shortlisted', 'rejected', 'withdrawn'"


def upgrade() -> None:
    # Preserve exact pre-workflow values so downgrade can restore legacy rows.
    op.create_table(
        "application_status_legacy_backup",
        sa.Column("application_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
    )
    op.execute(
        "INSERT INTO application_status_legacy_backup (application_id, status) "
        "SELECT id, status FROM applications"
    )
    op.execute(
        """UPDATE applications SET status = CASE lower(status)
            WHEN 'processing' THEN 'processing'
            WHEN 'analyzing' THEN 'processing'
            WHEN 'analyzed' THEN 'analyzed'
            WHEN 'completed' THEN 'analyzed'
            WHEN 'shortlisted' THEN 'shortlisted'
            WHEN 'rejected' THEN 'rejected'
            WHEN 'withdrawn' THEN 'withdrawn'
            ELSE 'applied' END"""
    )
    op.alter_column(
        "applications", "status", existing_type=sa.String(20),
        server_default=sa.text("'applied'"), existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_applications_status_valid", "applications", f"status IN ({STATUSES})"
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_type", sa.String(10), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system')", name="ck_application_status_actor_type"
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({STATUSES})",
            name="ck_application_status_from_valid",
        ),
        sa.CheckConstraint(
            f"to_status IN ({STATUSES})", name="ck_application_status_to_valid"
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_status_history_application_created",
        "application_status_history", ["application_id", "created_at"],
    )
    op.create_index(
        "ix_application_status_history_company_created",
        "application_status_history", ["company_id", "created_at"],
    )
    op.execute("""
        CREATE FUNCTION reject_application_status_history_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'application status history is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER application_status_history_append_only
        BEFORE UPDATE OR DELETE ON application_status_history
        FOR EACH ROW EXECUTE FUNCTION reject_application_status_history_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS application_status_history_append_only ON application_status_history")
    op.execute("DROP FUNCTION IF EXISTS reject_application_status_history_mutation()")
    op.drop_table("application_status_history")
    op.drop_constraint("ck_applications_status_valid", "applications", type_="check")
    op.alter_column("applications", "status", existing_type=sa.String(20), server_default=None)
    op.execute(
        "UPDATE applications SET status = b.status FROM application_status_legacy_backup b "
        "WHERE applications.id = b.application_id"
    )
    op.execute(
        """UPDATE applications SET status = CASE status
            WHEN 'processing' THEN 'processing' ELSE 'applied' END
            WHERE id NOT IN (SELECT application_id FROM application_status_legacy_backup)"""
    )
    op.drop_table("application_status_legacy_backup")
