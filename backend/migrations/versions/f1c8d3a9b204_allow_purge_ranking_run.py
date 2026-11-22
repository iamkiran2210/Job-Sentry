"""Allow transaction-scoped purge deletion on ranking_run when deleting all jobs in Data Explorer.

Revision ID: f1c8d3a9b204
Revises: e9b2c4d7a103
"""

from alembic import op

revision = "f1c8d3a9b204"
down_revision = "e9b2c4d7a103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ranking_run_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('job_sentry.allow_candidate_purge', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'ranking runs are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ranking_run_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ranking runs are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
