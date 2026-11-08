from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.company import Company
from app.models.job import EmploymentType, Job, JobStatus, WorkMode
from app.models.job_requirement import JobRequirement, RequirementCategory, RequirementImportance, RequirementType
from app.models.user import AuthProvider, User, UserRole
from app.core.exceptions import NotFoundException
from app.modules.analytics.router import _scope, candidates, jobs, overview, pipeline, skills
from app.modules.candidate_intelligence.models import CandidateScore, ScoreEvidenceRecord, VerificationResult


@pytest.mark.integration
async def test_analytics_overview_and_jobs_are_sql_aggregated_and_company_scoped(alembic_db):
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    async with sessions() as session:
        company = Company(name=f"analytics-{uuid4()}")
        other_company = Company(name=f"analytics-other-{uuid4()}")
        session.add_all([company, other_company])
        await session.flush()
        user = User(
            name="Analytics recruiter", email=f"analytics-{uuid4()}@example.test",
            password_hash="test-hash", role=UserRole.ADMIN, company_id=company.id,
            auth_provider=AuthProvider.EMAIL, is_active=True, is_verified=True,
        )
        session.add(user)
        job = Job(company_id=company.id, title="Analyst", description="Analyze", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE, status=JobStatus.ACTIVE)
        other_job = Job(company_id=other_company.id, title="Private role", description="Private", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE, status=JobStatus.ACTIVE)
        session.add_all([job, other_job])
        await session.flush()
        apps = []
        for idx, status in enumerate(("applied", "analyzed", "shortlisted")):
            app = Application(company_id=company.id, job_id=job.id, status=status, created_at=now)
            session.add(app)
            await session.flush()
            apps.append(app)
        boundary = Application(
            company_id=company.id, job_id=job.id, status="withdrawn",
            created_at=datetime.combine(now.date(), time(23, 59, 59), tzinfo=timezone.utc),
        )
        session.add(boundary)
        await session.flush()
        requirement = JobRequirement(
            job_id=job.id, category=RequirementCategory.SKILLS, name="Python",
            requirement_type=RequirementType.MANDATORY, importance=RequirementImportance.HIGH,
            weight=1, is_mandatory=True,
        )
        session.add(requirement)
        resume = Resume(
            company_id=company.id, job_id=job.id, application_id=apps[0].id,
            original_filename="fictional.pdf", extension="pdf", content_type="application/pdf",
            size_bytes=10, sha256=uuid4().hex * 2, storage_backend="local", storage_key="random-key",
        )
        session.add(resume)
        await session.flush()
        session.add(ExtractedProfile(
            company_id=company.id, resume_id=resume.id,
            profile_data={"skills": [{"name": "Python", "canonical_name": "python"}]},
        ))
        outsider = Application(company_id=other_company.id, job_id=other_job.id, status="applied", created_at=now)
        session.add(outsider)
        await session.flush()
        score_rows = []
        for app, score_value, eligibility in ((apps[0], 80, "eligible"), (apps[1], 60, "needs_review")):
            score = CandidateScore(
                company_id=company.id, application_id=app.id, job_id=job.id,
                scoring_version="v1.4.0", algorithm_version="v1.4.0", score=score_value,
                data_completeness=1, mandatory_results=[], inputs_hash=uuid4().hex * 2,
                category_detail={}, eligibility=eligibility, review_signals=[], config_snapshot={},
            )
            score_rows.append(score)
            session.add(score)
        await session.flush()
        session.add(ScoreEvidenceRecord(
            company_id=company.id, score_id=score_rows[0].id, application_id=apps[0].id,
            evidence_id="analytics-python", category="skills", signal_type="exact_skill_match",
            value=1, evidence_data={}, matched_term="Python", requirement_term="Python",
            canonical_term="python", grounded=True,
        ))

        data = await overview(
            date_from=now.date(), date_to=now.date(), job_id=None, company_id=None,
            interval="day", db=session, user=user,
        )
        kpis = data["data"]["kpis"]
        assert kpis["total_applications"] == 4
        assert kpis["open_jobs"] == 1
        assert kpis["applications_per_status"]["applied"] == 1
        assert kpis["analyzed_count"] == 1 and kpis["shortlisted_count"] == 1
        assert kpis["average_latest_score"] == 70
        assert kpis["median_latest_score"] == 70
        assert kpis["share_needing_review"] == 0.5
        assert data["data"]["trend"]["items"] == [{"bucket": now.date().isoformat(), "applications": 4}]

        job_data = await jobs(
            date_from=now.date(), date_to=now.date(), job_id=None, company_id=None,
            page=1, page_size=20, sort="-applications", db=session, user=user,
        )
        assert job_data["data"]["total"] == 1
        assert job_data["data"]["items"][0]["applications"] == 4
        assert job_data["data"]["items"][0]["analyzed"] == 1
        assert job_data["data"]["items"][0]["avg_score"] == 70
        with pytest.raises(HTTPException) as bad_sort:
            await jobs(
                date_from=now.date(), date_to=now.date(), job_id=None, company_id=None,
                page=1, page_size=20, sort="company_id", db=session, user=user,
            )
        assert bad_sort.value.status_code == 422

        candidate_data = await candidates(
            date_from=now.date(), date_to=now.date(), job_id=None, company_id=None,
            db=session, user=user,
        )
        assert candidate_data["data"]["score_distribution"][-1] == {"bucket": "unscored", "count": 2}
        assert candidate_data["data"]["eligibility_distribution"] == {"eligible": 1, "needs_review": 1}
        assert candidate_data["data"]["verification_distribution"] == {"not_verified": 4}
        assert "demographics" not in str(candidate_data).casefold()

        skill_data = await skills(
            date_from=now.date(), date_to=now.date(), job_id=None, company_id=None,
            limit=20, db=session, user=user,
        )
        assert skill_data["data"]["top_candidate_skills"] == [{"skill": "python", "candidate_count": 1, "share": 1 / 4}]
        assert skill_data["data"]["top_required_skills"] == [{
            "requirement_id": str(requirement.id), "skill": "Python", "mandatory": True,
            "weight": 1.0, "coverage_rate": 1 / 4,
        }]

        pipeline_data = await pipeline(
            date_from=now.date(), date_to=now.date(), job_id=None, company_id=None,
            db=session, user=user,
        )
        assert [item["count"] for item in pipeline_data["data"]["funnel"]] == [1, 0, 1, 1, 0, 1]
        assert pipeline_data["data"]["processing_outcomes"]["succeeded"] == 0

        with pytest.raises(HTTPException) as bad_range:
            await _scope(session, user, now.date(), now.date() - timedelta(days=1), None, None)
        assert bad_range.value.status_code == 422
        with pytest.raises(NotFoundException) as cross_company:
            await _scope(session, user, now.date(), now.date(), other_job.id, None)
        with pytest.raises(HTTPException) as company_filter:
            await _scope(session, user, now.date(), now.date(), None, other_company.id)
        assert company_filter.value.status_code == 403
        with pytest.raises(HTTPException) as long_range:
            await _scope(session, user, now.date() - timedelta(days=366), now.date(), None, None)
        assert long_range.value.status_code == 422
