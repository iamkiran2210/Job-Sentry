"""Allow transaction-scoped candidate clean-purge deletion on append-only history tables.

Revision ID: e9b2c4d7a103
Revises: d7f43ae83c10
"""

from alembic import op

revision = "e9b2c4d7a103"
down_revision = "d7f43ae83c10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ranking_history_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('job_sentry.allow_candidate_purge', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'ranking history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_application_status_history_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('job_sentry.allow_candidate_purge', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'application status history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ranking_history_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ranking history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_application_status_history_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'application status history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
