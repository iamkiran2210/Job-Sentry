"""Add score input fingerprints and per-application ranking run fields."""
from alembic import op
import sqlalchemy as sa

revision = "d6f3a810bc42"
down_revision = "c4e91a72b603"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("verification_results", sa.Column("checker_version", sa.String(40), nullable=False, server_default="v1"))
    op.add_column("candidate_scores", sa.Column("job_id", sa.Uuid(), nullable=True))
    op.add_column("candidate_scores", sa.Column("score_lower_bound", sa.Numeric(5, 2)))
    op.add_column("candidate_scores", sa.Column("score_upper_bound", sa.Numeric(5, 2)))
    op.add_column("candidate_scores", sa.Column("data_completeness", sa.Numeric(4, 3), nullable=False, server_default="0"))
    op.add_column("candidate_scores", sa.Column("mandatory_results", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("candidate_scores", sa.Column("inputs_hash", sa.String(64), nullable=False, server_default=""))
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE candidate_scores s SET job_id = a.job_id FROM applications a WHERE s.application_id = a.id"))
    op.create_foreign_key("fk_candidate_scores_job_id_jobs", "candidate_scores", "jobs", ["job_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_candidate_scores_job_id", "candidate_scores", ["job_id"])
    with op.batch_alter_table("candidate_scores") as batch:
        batch.drop_constraint("uq_candidate_score_application_version", type_="unique")
        batch.create_unique_constraint("uq_candidate_score_inputs_version", ["application_id", "job_id", "scoring_version", "inputs_hash"])

    op.add_column("ranking_history", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.add_column("ranking_history", sa.Column("application_id", sa.Uuid(), nullable=True))
    op.add_column("ranking_history", sa.Column("candidate_score_id", sa.Uuid(), nullable=True))
    op.add_column("ranking_history", sa.Column("rank", sa.Integer()))
    op.add_column("ranking_history", sa.Column("total_score", sa.Numeric(5, 2)))
    op.add_column("ranking_history", sa.Column("tie_break_key", sa.JSON(), nullable=False, server_default="{}"))
    bind.execute(sa.text("UPDATE ranking_history SET run_id = id"))
    op.create_foreign_key("fk_ranking_history_application_id_applications", "ranking_history", "applications", ["application_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_ranking_history_candidate_score_id_candidate_scores", "ranking_history", "candidate_scores", ["candidate_score_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_ranking_history_run_id", "ranking_history", ["run_id"])
    op.create_index("ix_ranking_history_application_id", "ranking_history", ["application_id"])
    op.create_index("ix_ranking_history_job_run_rank", "ranking_history", ["job_id", "run_id", "rank"])


def downgrade():
    op.drop_index("ix_ranking_history_job_run_rank", table_name="ranking_history")
    op.drop_index("ix_ranking_history_application_id", table_name="ranking_history")
    op.drop_index("ix_ranking_history_run_id", table_name="ranking_history")
    op.drop_constraint("fk_ranking_history_candidate_score_id_candidate_scores", "ranking_history", type_="foreignkey")
    op.drop_constraint("fk_ranking_history_application_id_applications", "ranking_history", type_="foreignkey")
    op.drop_column("ranking_history", "tie_break_key")
    op.drop_column("ranking_history", "total_score")
    op.drop_column("ranking_history", "rank")
    op.drop_column("ranking_history", "candidate_score_id")
    op.drop_column("ranking_history", "application_id")
    op.drop_column("ranking_history", "run_id")
    with op.batch_alter_table("candidate_scores") as batch:
        batch.drop_constraint("uq_candidate_score_inputs_version", type_="unique")
        batch.create_unique_constraint("uq_candidate_score_application_version", ["application_id", "scoring_version"])
    op.drop_index("ix_candidate_scores_job_id", table_name="candidate_scores")
    op.drop_constraint("fk_candidate_scores_job_id_jobs", "candidate_scores", type_="foreignkey")
    op.drop_column("candidate_scores", "inputs_hash")
    op.drop_column("candidate_scores", "mandatory_results")
    op.drop_column("candidate_scores", "data_completeness")
    op.drop_column("candidate_scores", "score_upper_bound")
    op.drop_column("candidate_scores", "score_lower_bound")
    op.drop_column("candidate_scores", "job_id")
    op.drop_column("verification_results", "checker_version")
