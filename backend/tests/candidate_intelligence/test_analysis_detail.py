from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.company import Company
from app.models.job import EmploymentType, Job, WorkMode
from app.modules.candidate_intelligence.models import CandidateScore, ScoreEvidenceRecord, VerificationResult
from app.modules.candidate_intelligence.schemas import AnalysisData
from app.modules.candidate_intelligence.service import CandidateIntelligenceService, ScoringService


async def seed_detail(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        company = Company(name=f"analysis-{uuid.uuid4()}")
        session.add(company)
        await session.flush()
        job = Job(company_id=company.id, title="Backend engineer", description="Python APIs", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE)
        candidate = Candidate(company_id=company.id, full_name="Ada Example", email="ada@example.test", phone="+14155552671")
        session.add_all([job, candidate])
        await session.flush()
        application = Application(company_id=company.id, job_id=job.id, candidate_id=candidate.id, status="applied")
        session.add(application)
        await session.flush()
        resume = Resume(
            company_id=company.id, job_id=job.id, application_id=application.id,
            original_filename="Ada Resume.pdf", extension="pdf", content_type="application/pdf",
            size_bytes=512, sha256="abcdef0123456789" * 4, storage_backend="local",
            storage_key="private/random-key", status="completed",
        )
        session.add(resume)
        await session.flush()
        session.add(ExtractedProfile(
            company_id=company.id, resume_id=resume.id, source_text="untrusted resume source",
            extraction_method="pdf_text", schema_version=3, profile_data={
                "full_name": {"value": "Ada Example"},
                "gender": "must not appear", "age": 37, "date_of_birth": "1989-01-01",
                "photo": "private-photo", "nationality": "private-nationality",
                "ethnicity": "private-ethnicity", "religion": "private-religion",
                "marital_status": "private-marital", "address": "private-address",
                "contact": {
                    "email": {"value": "ada@example.test"},
                    "phone": {"value": "+14155552671"},
                    "github_url": {"value": "https://github.com/ada"},
                    "portfolio_url": {"value": "https://ada.example.test"},
                },
                "skills": [{"name": "Python", "evidence": "Built Python APIs"}],
                "employment": [{"title": "Backend Engineer", "company": "Example Co", "start_date": "2020-01", "description": "Built APIs", "location": "private-address"}],
                "education": [{"institution": "Example University", "degree": "BSc", "field_of_study": "Computer Science"}],
                "projects": [{"name": "API", "description": "Built APIs", "technologies": ["Python"]}],
                "certifications": [{"name": "Cloud Engineer", "issuer": "Example"}],
            },
        ))
        session.add(VerificationResult(
            company_id=company.id, application_id=application.id, check_type="email_format",
            status="passed", signal="Email format is valid.",
            details={"email": "ada@example.test", "normalized_phone": "+14155552671"},
        ))
        await session.commit()
        return application.id, candidate.id


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_analysis_returns_full_detail_and_does_not_write_or_score(alembic_db, monkeypatch):
    application_id, _ = await seed_detail(alembic_db)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        before = (
            await session.scalar(select(func.count()).select_from(CandidateScore)),
            await session.scalar(select(func.count()).select_from(ScoreEvidenceRecord)),
        )
        async def fail_scoring(*args, **kwargs):
            raise AssertionError("GET analysis must not score")
        monkeypatch.setattr(ScoringService, "score_application", fail_scoring)

        data = await CandidateIntelligenceService.analyze(session, application_id)
        AnalysisData.model_validate(data)
        assert data["status_note"] == "not_scored"
        assert data["score"] is None
        assert data["evidence"] == []
        assert data["candidate"]["display_name"] == "Ada Example"
        assert data["candidate"]["email"] != "ada@example.test"
        assert data["candidate"]["phone"].endswith("2671")
        assert data["verification_detail"]["checks"][0]["details"] == {
            "email": "a***@example.test", "normalized_phone": "***2671",
        }
        assert data["resume"]["content_hash_prefix"] == "abcdef012345"
        assert data["application"]["status"] == "applied"
        assert data["score_detail"] is None
        assert data["explanation"]["deterministic_summary"] == []
        assert data["explanation"]["ai_status"] == "unavailable"
        serialized = str(data)
        for protected in (
            "must not appear", "private-nationality", "private-ethnicity",
            "private-religion", "private-marital", "private-address", "private-photo",
        ):
            assert protected not in serialized
        after = (
            await session.scalar(select(func.count()).select_from(CandidateScore)),
            await session.scalar(select(func.count()).select_from(ScoreEvidenceRecord)),
        )
        assert after == before

        full_detail = await CandidateIntelligenceService.analyze(session, application_id, pii_access=True)
        assert full_detail["candidate"]["email"] == "ada@example.test"
        assert full_detail["candidate"]["phone"] == "+14155552671"
        assert full_detail["verification_detail"]["checks"][0]["details"] == {
            "email": "a***@example.test", "normalized_phone": "***2671",
        }
