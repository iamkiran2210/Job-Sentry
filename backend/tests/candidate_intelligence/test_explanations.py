from app.modules.candidate_intelligence.explanations import ExplanationOutput, keep_cited_items
from app.modules.candidate_intelligence.explanations import generate_and_store_explanation
from app.modules.candidate_intelligence.models import CandidateScore, ScoreEvidenceRecord
from app.ai_features.models.application import Application
from app.models.job import Job
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.candidate_intelligence.test_analysis_detail import seed_detail


def test_explanation_drops_items_without_evidence_from_current_score():
    output = ExplanationOutput.model_validate({
        "summary": "Persisted scores are unchanged.",
        "strengths": [
            {"text": "Supported strength", "evidence_ids": ["e1"]},
            {"text": "Uncited strength", "evidence_ids": ["other-score"]},
        ],
        "gaps": [{"text": "Mixed citations", "evidence_ids": ["other-score", "e2"]}],
    })

    assert keep_cited_items(output, {"e1", "e2"}) == {
        "summary": "Persisted scores are unchanged.",
        "strengths": [{"text": "Supported strength", "evidence_ids": ["e1"]}],
        "gaps": [{"text": "Mixed citations", "evidence_ids": ["other-score", "e2"]}],
    }


def test_explanation_with_no_valid_evidence_is_unavailable():
    output = ExplanationOutput.model_validate({
        "summary": "Unsupported.",
        "strengths": [{"text": "Unsupported", "evidence_ids": ["wrong"]}],
        "gaps": [],
    })

    assert keep_cited_items(output, {"e1"}) is None


async def test_generated_explanation_uses_persisted_data_and_caches(alembic_db):
    application_id, _ = await seed_detail(alembic_db)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)

    class FakeGenerator:
        calls = 0

        async def generate(self, payload):
            self.calls += 1
            assert "candidate" not in payload and "email" not in payload
            return ExplanationOutput.model_validate({
                "summary": "A score explanation.",
                "strengths": [
                    {"text": "Supported.", "evidence_ids": ["e1"]},
                    {"text": "Unsupported.", "evidence_ids": ["not-in-score"]},
                ],
                "gaps": [],
            })

    generator = FakeGenerator()
    async with sessions() as session:
        application = await session.get(Application, application_id)
        job = await session.get(Job, application.job_id)
        score = CandidateScore(
            company_id=application.company_id, application_id=application.id, job_id=job.id,
            scoring_version="test-v1", algorithm_version="test-v1", score=75,
            data_completeness=1, mandatory_results=[], category_detail={"skills": {"match": 0.75}},
            eligibility="eligible", review_signals=[], config_snapshot={}, inputs_hash="a" * 64,
        )
        session.add(score)
        await session.flush()
        session.add(ScoreEvidenceRecord(
            company_id=application.company_id, score_id=score.id, application_id=application.id,
            evidence_id="e1", category="skills", signal_type="exact_skill_match",
            evidence_data={"supporting_quotes": ["Built Python APIs"]}, matched_term="Python",
            requirement_term="Python", canonical_term="python", grounded=True,
        ))
        await session.flush()
        record = await generate_and_store_explanation(
            session, score.id, generator, generator_model="mock", prompt_version="test-v1",
        )
        assert record.status == "available"
        assert [item["evidence_ids"] for item in record.content["strengths"]] == [["e1"]]
        cached = await generate_and_store_explanation(
            session, score.id, generator, generator_model="mock", prompt_version="test-v1",
        )
        assert cached.id == record.id
        assert generator.calls == 1
        assert await session.scalar(select(func.count()).select_from(ScoreEvidenceRecord).where(ScoreEvidenceRecord.score_id == score.id)) == 1

        class TimeoutGenerator:
            async def generate(self, payload):
                raise TimeoutError

        failed = await generate_and_store_explanation(
            session, score.id, TimeoutGenerator(), generator_model="mock-timeout",
            prompt_version="test-v1",
        )
        assert failed.status == "failed"
        assert failed.error == "generation_timeout"
