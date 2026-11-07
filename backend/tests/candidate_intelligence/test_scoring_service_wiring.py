from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select

from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_requirement import JobRequirement, RequirementCategory, RequirementImportance, RequirementType
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.models import CandidateScore
from app.modules.candidate_intelligence.service import CandidateIntelligenceService, ScoringService


async def seeded_application(db_session, company_with_admin):
    company, _ = company_with_admin
    job = Job(company_id=company.id, title="Backend Engineer", description="Python APIs", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE)
    db_session.add(job)
    await db_session.flush()
    db_session.add(JobRequirement(job_id=job.id, category=RequirementCategory.SKILLS, name="Python", requirement_type=RequirementType.MANDATORY, importance=RequirementImportance.HIGH, weight=1.0, is_mandatory=True))
    await db_session.flush()
    app = Application(company_id=company.id, job_id=job.id, status="applied")
    db_session.add(app)
    await db_session.flush()
    resume = Resume(company_id=company.id, job_id=job.id, application_id=app.id, original_filename="resume.pdf", extension="pdf", content_type="application/pdf", size_bytes=10, sha256=uuid.uuid4().hex, storage_backend="local", storage_key="test/resume.pdf")
    db_session.add(resume)
    await db_session.flush()
    db_session.add(ExtractedProfile(resume_id=resume.id, company_id=company.id, source_text="Python backend engineer with APIs and services." * 8, profile_data={"skills": [{"name": "Python", "evidence": "Python"}], "employment": [], "projects": [], "education": [], "certifications": [], "contact": {}}))
    await db_session.flush()
    return app, job


@pytest.mark.asyncio
async def test_score_application_persists_complete_score(db_session, company_with_admin, monkeypatch):
    app, job = await seeded_application(db_session, company_with_admin)
    monkeypatch.setattr("app.modules.candidate_intelligence.service.build_embedding_provider", lambda cfg: SimpleNamespace(embed_text=lambda text: SimpleNamespace(vector=[1.0] * cfg.embedding_dimension, content_hash="h", model_name="fake", model_version="1", dimension=cfg.embedding_dimension)))
    monkeypatch.setattr("app.modules.candidate_intelligence.service.build_llm_analyzer", lambda cfg: SimpleNamespace())
    await ScoringService.score_application(app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session)
    row = (await db_session.execute(select(CandidateScore).where(CandidateScore.application_id == app.id))).scalar_one()
    assert row.category_detail is not None and row.score is not None and row.config_snapshot
    assert row.inputs_hash and row.score_lower_bound is not None and row.score_upper_bound is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["score_skills", "score_experience", "score_projects", "score_education", "score_certifications", "aggregate", "evaluate_mandatory"])
async def test_persisted_score_uses_pure_scorer_sentinel(db_session, company_with_admin, monkeypatch, name):
    app, job = await seeded_application(db_session, company_with_admin)
    import app.modules.candidate_intelligence.scoring.category_formulas as formulas
    sentinel = object()
    monkeypatch.setattr(formulas, name, lambda *args, **kwargs: sentinel, raising=False)
    await ScoringService.score_application(app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session)
    row = (await db_session.execute(select(CandidateScore).where(CandidateScore.application_id == app.id))).scalar_one()
    assert sentinel in (row.category_detail, row.config_snapshot, row.score)


@pytest.mark.asyncio
async def test_scoring_service_does_not_call_old_analysis_path(db_session, company_with_admin, monkeypatch):
    app, job = await seeded_application(db_session, company_with_admin)
    async def fail(*args, **kwargs):
        raise AssertionError("old path used")
    monkeypatch.setattr(CandidateIntelligenceService, "analyze", fail)
    await ScoringService.score_application(app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session)
