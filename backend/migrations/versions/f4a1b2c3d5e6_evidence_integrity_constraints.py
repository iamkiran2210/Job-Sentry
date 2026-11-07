"""Add explicit evidence metadata and integrity constraints.

Revision ID: f4a1b2c3d5e6
Revises: e82c4a91d307
"""
from alembic import op
import sqlalchemy as sa


revision = "f4a1b2c3d5e6"
down_revision = "e82c4a91d307"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("score_evidence", sa.Column("embedding_model", sa.String(120), nullable=True))
    op.add_column("score_evidence", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.add_column("score_evidence", sa.Column("llm_model", sa.String(120), nullable=True))
    op.add_column("score_evidence", sa.Column("prompt_version", sa.String(80), nullable=True))
    op.add_column("score_evidence", sa.Column("source_start", sa.Integer(), nullable=True))
    op.add_column("score_evidence", sa.Column("source_end", sa.Integer(), nullable=True))

    # Legacy evidence did not record a grounding decision. Treat absence as
    # ungrounded; the NOT VALID checks below preserve old rows while enforcing
    # the new contract for every subsequent insert/update.
    op.execute("UPDATE score_evidence SET grounded = false WHERE grounded IS NULL")

    constraints = {
        "ck_score_evidence_category_valid": "category IN ('skills', 'experience', 'projects', 'education', 'certifications')",
        "ck_score_evidence_signal_type_valid": "signal_type IN ('exact_skill_match', 'alias_skill_match', 'semantic_similarity', 'llm_relevance', 'github_language_signal', 'rule_based_match')",
        "ck_score_evidence_semantic_metadata": "signal_type <> 'semantic_similarity' OR (similarity IS NOT NULL AND embedding_model IS NOT NULL AND embedding_model_version IS NOT NULL AND embedding_dim IS NOT NULL)",
        "ck_score_evidence_llm_metadata": "signal_type <> 'llm_relevance' OR (llm_model IS NOT NULL AND prompt_version IS NOT NULL AND input_hash IS NOT NULL)",
        "ck_score_evidence_exact_terms": "signal_type NOT IN ('exact_skill_match', 'alias_skill_match') OR (matched_term IS NOT NULL AND canonical_term IS NOT NULL)",
        "ck_score_evidence_source_range": "source_start IS NULL OR source_end IS NULL OR source_end >= source_start",
        "ck_score_evidence_grounded_not_null": "grounded IS NOT NULL",
        "ck_score_evidence_no_semantic_proof": "NOT (is_proof AND signal_type IN ('semantic_similarity', 'llm_relevance'))",
    }
    for name, expression in constraints.items():
        op.execute(
            f"ALTER TABLE score_evidence ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID"
        )


def downgrade() -> None:
    for name in (
        "ck_score_evidence_no_semantic_proof",
        "ck_score_evidence_source_range",
        "ck_score_evidence_grounded_not_null",
        "ck_score_evidence_exact_terms",
        "ck_score_evidence_llm_metadata",
        "ck_score_evidence_semantic_metadata",
        "ck_score_evidence_signal_type_valid",
        "ck_score_evidence_category_valid",
    ):
        op.drop_constraint(name, "score_evidence", type_="check")
    for name in ("source_end", "source_start", "prompt_version", "llm_model", "embedding_dim", "embedding_model"):
        op.drop_column("score_evidence", name)
