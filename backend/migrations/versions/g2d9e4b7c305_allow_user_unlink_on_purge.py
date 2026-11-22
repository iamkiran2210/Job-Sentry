"""Allow transaction-scoped user unlink (SET NULL on triggered_by) during account deletion.

Revision ID: g2d9e4b7c305
Revises: f1c8d3a9b204
"""

from alembic import op

revision = "g2d9e4b7c305"
down_revision = "f1c8d3a9b204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ranking_history_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF current_setting('job_sentry.allow_candidate_purge', true) = 'on' THEN
              RETURN OLD;
            END IF;
          ELSIF TG_OP = 'UPDATE' THEN
            IF current_setting('job_sentry.allow_candidate_purge', true) = 'on'
               AND NEW.triggered_by IS NULL
               AND NEW.id = OLD.id
               AND NEW.application_id IS NOT DISTINCT FROM OLD.application_id
               AND NEW.job_id = OLD.job_id
               AND NEW.total_score IS NOT DISTINCT FROM OLD.total_score
               AND NEW.rank IS NOT DISTINCT FROM OLD.rank THEN
              RETURN NEW;
            END IF;
          END IF;
          RAISE EXCEPTION 'ranking history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ranking_run_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF current_setting('job_sentry.allow_candidate_purge', true) = 'on' THEN
              RETURN OLD;
            END IF;
          ELSIF TG_OP = 'UPDATE' THEN
            IF current_setting('job_sentry.allow_candidate_purge', true) = 'on'
               AND NEW.triggered_by IS NULL
               AND NEW.id = OLD.id
               AND NEW.job_id = OLD.job_id THEN
              RETURN NEW;
            END IF;
          END IF;
          RAISE EXCEPTION 'ranking runs are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
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
