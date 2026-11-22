from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from app.modules.candidate_intelligence.evidence.matchers import semantic_evidence
from app.modules.candidate_intelligence.interfaces import EmbeddingResult
from app.modules.candidate_intelligence.models import ScoreEvidenceRecord
from app.modules.candidate_intelligence.types import ScoreEvidence
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture
async def evidence_parents(alembic_db: AsyncEngine):
    company_id, user_id, job_id, candidate_id, application_id, score_id = (
        uuid4() for _ in range(6)
    )
    now = datetime.now(timezone.utc)
    async with alembic_db.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO job_sentry.companies (id, name, created_at, updated_at) VALUES (:id, 'Evidence Test Co', :now, :now)"
            ),
            {"id": company_id, "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO job_sentry.users (id, name, email, role, company_id, auth_provider, is_active, is_verified, created_at, updated_at) "
                "VALUES (:id, 'Evidence Admin', :email, 'ADMIN', :company, 'EMAIL', true, true, :now, :now)"
            ),
            {"id": user_id, "email": f"{user_id}@example.test", "company": company_id, "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO job_sentry.jobs (id, company_id, title, description, employment_type, work_mode, openings, status, created_at, updated_at) "
                "VALUES (:id, :company, 'Evidence Job', 'Test', 'full_time', 'remote', 1, 'draft', :now, :now)"
            ),
            {"id": job_id, "company": company_id, "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO job_sentry.candidates (id, company_id, full_name, email, normalized_email, created_at, updated_at) "
                "VALUES (:id, :company, 'Evidence Candidate', :email, :email, :now, :now)"
            ),
            {
                "id": candidate_id,
                "company": company_id,
                "email": f"candidate-{candidate_id}@example.test",
                "now": now,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO job_sentry.applications (id, company_id, job_id, candidate_id, status, created_at, updated_at) "
                "VALUES (:id, :company, :job, :candidate, 'applied', :now, :now)"
            ),
            {
                "id": application_id,
                "company": company_id,
                "job": job_id,
                "candidate": candidate_id,
                "now": now,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO job_sentry.candidate_scores "
                "(id, company_id, application_id, job_id, scoring_version, algorithm_version, category_detail, eligibility, review_signals, config_snapshot, created_at, updated_at) "
                "VALUES (:id, :company, :application, :job, 'test-v1', 'test-v1', '{}'::jsonb, 'needs_review', '[]'::jsonb, '{}'::jsonb, :now, :now)"
            ),
            {
                "id": score_id,
                "company": company_id,
                "application": application_id,
                "job": job_id,
                "now": now,
            },
        )
    return {"company_id": company_id, "application_id": application_id, "score_id": score_id}


def evidence_values(parents: dict, **overrides) -> dict:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid4(),
        "company_id": parents["company_id"],
        "score_id": parents["score_id"],
        "application_id": parents["application_id"],
        "evidence_id": f"ev-{uuid4()}",
        "category": "skills",
        "signal_type": "exact_skill_match",
        "value": 1.0,
        "evidence_data": {"source": "test"},
        "matched_term": "Python",
        "canonical_term": "python",
        "grounded": False,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return values


async def _assert_constraint(
        alembic_db: AsyncEngine, parents: dict, expected_constraint: str, **overrides
):
    with pytest.raises(IntegrityError) as exc_info:
        async with alembic_db.begin() as conn:
            await conn.execute(
                insert(ScoreEvidenceRecord).values(**evidence_values(parents, **overrides))
            )
    error = exc_info.value.orig
    constraint = getattr(error, "constraint_name", None)
    if constraint is None and getattr(error, "__cause__", None) is not None:
        constraint = getattr(error.__cause__, "constraint_name", None)
    assert constraint == expected_constraint, (
        f"expected violated constraint {expected_constraint}, got {constraint}"
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "category", ["invalid", "role"], ids=["invalid-category", "unsupported-category"]
)
async def test_invalid_evidence_category_is_rejected(alembic_db, evidence_parents, category):
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_category_valid", category=category
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_invalid_evidence_signal_type_is_rejected(alembic_db, evidence_parents):
    await _assert_constraint(
        alembic_db,
        evidence_parents,
        "ck_score_evidence_signal_type_valid",
        signal_type="made_up_signal",
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize("value", [-0.01, 1.01], ids=["below-zero", "above-one"])
async def test_evidence_value_outside_unit_interval_is_rejected(
        alembic_db, evidence_parents, value
):
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_value_range", value=value
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "similarity", [-1.1, 1.1], ids=["below-cosine-range", "above-cosine-range"]
)
async def test_evidence_similarity_outside_cosine_range_is_rejected(
        alembic_db, evidence_parents, similarity
):
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_similarity_range", similarity=similarity
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "similarity", [-1.0, 0.0, 1.0], ids=["negative-one", "zero", "positive-one"]
)
async def test_evidence_similarity_cosine_endpoints_are_accepted(
        alembic_db, evidence_parents, similarity
):
    values = evidence_values(
        evidence_parents,
        signal_type="semantic_similarity",
        value=0.0,
        similarity=similarity,
        embedding_model="test-embedder",
        embedding_model_version="v1",
        embedding_dim=384,
    )
    async with alembic_db.begin() as conn:
        await conn.execute(insert(ScoreEvidenceRecord).values(**values))


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "signal_type", ["semantic_similarity", "llm_relevance"], ids=["semantic", "llm"]
)
async def test_non_proof_evidence_cannot_be_marked_as_proof(
        alembic_db, evidence_parents, signal_type
):
    fields = (
        {
            "similarity": 0.5,
            "embedding_model": "test-embedder",
            "embedding_model_version": "v1",
            "embedding_dim": 384,
        }
        if signal_type == "semantic_similarity"
        else {"llm_model": "test-llm", "prompt_version": "p1", "input_hash": "a" * 64}
    )
    await _assert_constraint(
        alembic_db,
        evidence_parents,
        "ck_score_evidence_no_semantic_proof",
        signal_type=signal_type,
        is_proof=True,
        **fields,
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "field", ["similarity", "embedding_model", "embedding_model_version", "embedding_dim"]
)
async def test_semantic_evidence_requires_embedding_metadata(alembic_db, evidence_parents, field):
    fields = {
        "signal_type": "semantic_similarity",
        "value": 0.1,
        "similarity": 0.7,
        "embedding_model": "test-embedder",
        "embedding_model_version": "v1",
        "embedding_dim": 384,
    }
    fields[field] = None
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_semantic_metadata", **fields
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize("field", ["llm_model", "prompt_version", "input_hash"])
async def test_llm_evidence_requires_model_prompt_and_input_hash(
        alembic_db, evidence_parents, field
):
    fields = {
        "signal_type": "llm_relevance",
        "llm_model": "test-llm",
        "prompt_version": "p1",
        "input_hash": "a" * 64,
    }
    fields[field] = None
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_llm_metadata", **fields
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "signal_type", ["exact_skill_match", "alias_skill_match"], ids=["exact", "alias"]
)
@pytest.mark.parametrize("field", ["matched_term", "canonical_term"])
async def test_exact_and_alias_evidence_require_matched_and_canonical_terms(
        alembic_db, evidence_parents, signal_type, field
):
    await _assert_constraint(
        alembic_db,
        evidence_parents,
        "ck_score_evidence_exact_terms",
        signal_type=signal_type,
        **{field: None},
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_evidence_source_end_cannot_precede_source_start(alembic_db, evidence_parents):
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_source_range", source_start=8, source_end=7
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_evidence_grounded_cannot_be_null(alembic_db, evidence_parents):
    await _assert_constraint(
        alembic_db, evidence_parents, "ck_score_evidence_grounded_not_null", grounded=None
    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "signal_type",
    [
        "exact_skill_match",
        "alias_skill_match",
        "semantic_similarity",
        "llm_relevance",
        "github_language_signal",
        "rule_based_match",
    ],
)
async def test_each_evidence_signal_type_accepts_a_valid_row(
        alembic_db, evidence_parents, signal_type
):
    fields = {"signal_type": signal_type}
    if signal_type in {"exact_skill_match", "alias_skill_match"}:
        fields.update(matched_term="Python", canonical_term="python")
    if signal_type == "semantic_similarity":
        fields.update(
            value=0.6,
            similarity=0.9,
            embedding_model="test-embedder",
            embedding_model_version="v1",
            embedding_dim=384,
        )
    if signal_type == "llm_relevance":
        fields.update(value=0.8, llm_model="test-llm", prompt_version="p1", input_hash="b" * 64)
    async with alembic_db.begin() as conn:
        await conn.execute(
            insert(ScoreEvidenceRecord).values(**evidence_values(evidence_parents, **fields))
        )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_every_score_evidence_field_round_trips_as_a_database_column(
        alembic_db, evidence_parents
):
    evidence = ScoreEvidence(
        evidence_id=f"roundtrip-{uuid4()}",
        category="skills",
        signal_type="semantic_similarity",
        value=0.5,
        source_location="resume:line-2",
        matched_term="Python",
        requirement_term="Python",
        canonical_term="python",
        alias_used=None,
        match_type="semantic",
        compared_texts=("Python", "built Python systems"),
        model_version="v1",
        similarity=0.75,
        rationale="interpretable",
        supporting_quotes=("built Python systems",),
        grounded=False,
        error=None,
        model_name="legacy-model",
        input_hash="c" * 64,
        embedding=tuple([0.0] * 383 + [1.0]),
        embedding_model="test-embedder",
        embedding_model_version="v1",
        embedding_dim=384,
        llm_model=None,
        prompt_version=None,
        source_start=10,
        source_end=20,
    )
    columns = set(ScoreEvidenceRecord.__table__.columns.keys())
    assert set(evidence.__dataclass_fields__) <= columns
    now = datetime.now(timezone.utc)
    values = evidence.__dict__.copy()
    values.update(
        id=uuid4(),
        company_id=evidence_parents["company_id"],
        score_id=evidence_parents["score_id"],
        application_id=evidence_parents["application_id"],
        evidence_data={"roundtrip": True},
        is_proof=False,
        created_at=now,
        updated_at=now,
        embedding=list(evidence.embedding),
        embedding_model_name=evidence.embedding_model,
        embedding_dimension=evidence.embedding_dim,
    )
    async with alembic_db.begin() as conn:
        await conn.execute(insert(ScoreEvidenceRecord).values(**values))
        result = await conn.execute(
            text(
                "SELECT evidence_id, category, signal_type, value, source_location, matched_term, requirement_term, "
                "canonical_term, alias_used, match_type, compared_texts::text, model_version, similarity, rationale, "
                "supporting_quotes::text, grounded, error, model_name, input_hash, embedding_model, "
                "embedding_model_version, embedding_dim, llm_model, prompt_version, source_start, source_end, "
                "vector_dims(embedding), embedding::text AS embedding_text FROM job_sentry.score_evidence WHERE evidence_id = :evidence_id"
            ),
            {"evidence_id": evidence.evidence_id},
        )
        row = result.mappings().one()
    assert row["evidence_id"] == evidence.evidence_id
    assert row["category"] == evidence.category
    assert row["signal_type"] == evidence.signal_type
    assert float(row["value"]) == evidence.value
    assert row["source_location"] == evidence.source_location
    assert row["matched_term"] == evidence.matched_term
    assert row["requirement_term"] == evidence.requirement_term
    assert row["canonical_term"] == evidence.canonical_term
    assert row["alias_used"] == evidence.alias_used
    assert row["match_type"] == evidence.match_type
    assert "Python" in row["compared_texts"]
    assert row["model_version"] == evidence.model_version
    assert float(row["similarity"]) == evidence.similarity
    assert row["rationale"] == evidence.rationale
    assert "built Python systems" in row["supporting_quotes"]
    assert row["grounded"] is evidence.grounded
    assert row["error"] == evidence.error
    assert row["model_name"] == evidence.model_name
    assert row["input_hash"] == evidence.input_hash
    assert row["embedding_model"] == evidence.embedding_model
    assert row["embedding_model_version"] == evidence.embedding_model_version
    assert row["embedding_dim"] == evidence.embedding_dim == 384
    assert row["llm_model"] == evidence.llm_model
    assert row["prompt_version"] == evidence.prompt_version
    assert row["source_start"] == evidence.source_start
    assert row["source_end"] == evidence.source_end
    assert row["vector_dims"] == 384
    vector = [float(item) for item in row["embedding_text"].strip("[]").split(",")]
    assert len(vector) == 384
    assert vector[-1] == 1.0


def test_semantic_similarity_credit_is_clamped_and_capped():
    class FixedEmbeddingProvider:
        model_name = "fixed"
        model_version = "v1"

        def embed_text(self, text: str):
            vectors = {"opposite": [1.0, 0.0], "negative": [-0.5, 3**0.5 / 2], "same": [1.0, 0.0]}
            vector = vectors[text]
            return EmbeddingResult(vector, self.model_name, self.model_version, len(vector), text)

        def embed_batch(self, texts: list[str]):
            return [self.embed_text(text) for text in texts]

    provider = FixedEmbeddingProvider()
    negative = semantic_evidence("opposite", "negative", provider, threshold=0.5)
    full_match = semantic_evidence("opposite", "same", provider, threshold=0.5)
    assert negative.similarity == pytest.approx(-0.5)
    assert negative.value == 0.0
    assert full_match.similarity == pytest.approx(1.0)
    assert full_match.value == 0.60
