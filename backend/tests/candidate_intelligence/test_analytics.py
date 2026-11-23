from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.core.exceptions import NotFoundException
from app.models.company import Company
from app.models.job import EmploymentType, Job, JobStatus, WorkMode
from app.models.job_requirement import (
    JobRequirement,
    RequirementCategory,
    RequirementImportance,
    RequirementType,
)
from app.models.user import AuthProvider, User, UserRole
from app.modules.analytics.router import _scope, candidates, jobs, overview, pipeline, skills
from app.modules.candidate_intelligence.models import (
    CandidateScore,
    ScoreEvidenceRecord,
    VerificationResult,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker


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
            name="Analytics recruiter",
            email=f"analytics-{uuid4()}@example.test",
            password_hash="test-hash",
            role=UserRole.ADMIN,
            company_id=company.id,
            auth_provider=AuthProvider.EMAIL,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        job = Job(
            company_id=company.id,
            title="Analyst",
            description="Analyze",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
            status=JobStatus.ACTIVE,
        )
        other_job = Job(
            company_id=other_company.id,
            title="Private role",
            description="Private",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
            status=JobStatus.ACTIVE,
        )
        session.add_all([job, other_job])
        await session.flush()
        apps = []
        for idx, status in enumerate(("applied", "analyzed", "shortlisted")):
            app = Application(company_id=company.id, job_id=job.id, status=status, created_at=now)
            session.add(app)
            await session.flush()
            apps.append(app)
        boundary = Application(
            company_id=company.id,
            job_id=job.id,
            status="withdrawn",
            created_at=datetime.combine(now.date(), time(23, 59, 59), tzinfo=timezone.utc),
        )
        session.add(boundary)
        await session.flush()
        requirement = JobRequirement(
            job_id=job.id,
            category=RequirementCategory.SKILLS,
            name="Python",
            requirement_type=RequirementType.MANDATORY,
            importance=RequirementImportance.HIGH,
            weight=1,
            is_mandatory=True,
        )
        session.add(requirement)
        resume = Resume(
            company_id=company.id,
            job_id=job.id,
            application_id=apps[0].id,
            original_filename="fictional.pdf",
            extension="pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256=uuid4().hex * 2,
            storage_backend="local",
            storage_key="random-key",
        )
        session.add(resume)
        await session.flush()
        session.add(
            ExtractedProfile(
                company_id=company.id,
                resume_id=resume.id,
                profile_data={"skills": [{"name": "Python", "canonical_name": "python"}]},
            )
        )
        outsider = Application(
            company_id=other_company.id, job_id=other_job.id, status="applied", created_at=now
        )
        session.add(outsider)
        await session.flush()
        score_rows = []
        for app, score_value, eligibility in (
                (apps[0], 80, "eligible"),
                (apps[1], 60, "needs_review"),
        ):
            score = CandidateScore(
                company_id=company.id,
                application_id=app.id,
                job_id=job.id,
                scoring_version="v1.4.0",
                algorithm_version="v1.4.0",
                score=score_value,
                data_completeness=1,
                mandatory_results=[],
                inputs_hash=uuid4().hex * 2,
                category_detail={},
                eligibility=eligibility,
                review_signals=[],
                config_snapshot={},
            )
            score_rows.append(score)
            session.add(score)
        await session.flush()
        session.add(
            ScoreEvidenceRecord(
                company_id=company.id,
                score_id=score_rows[0].id,
                application_id=apps[0].id,
                evidence_id="analytics-python",
                category="skills",
                signal_type="exact_skill_match",
                value=1,
                evidence_data={},
                matched_term="Python",
                requirement_term="Python",
                canonical_term="python",
                grounded=True,
            )
        )

        data = await overview(
            date_from=now.date(),
            date_to=now.date(),
            job_id=None,
            company_id=None,
            interval="day",
            db=session,
            user=user,
        )
        kpis = data["data"]["kpis"]
        assert kpis["total_applications"] == 4
        assert kpis["open_jobs"] == 1
        assert kpis["applications_per_status"]["applied"] == 1
        assert kpis["analyzed_count"] == 1 and kpis["shortlisted_count"] == 1
        assert kpis["average_latest_score"] == 70
        assert kpis["median_latest_score"] == 70
        assert kpis["share_needing_review"] == 0.5
        assert data["data"]["trend"]["items"] == [
            {"bucket": now.date().isoformat(), "applications": 4}
        ]

        job_data = await jobs(
            date_from=now.date(),
            date_to=now.date(),
            job_id=None,
            company_id=None,
            page=1,
            page_size=20,
            sort="-applications",
            db=session,
            user=user,
        )
        assert job_data["data"]["total"] == 1
        assert job_data["data"]["items"][0]["applications"] == 4
        assert job_data["data"]["items"][0]["analyzed"] == 1
        assert job_data["data"]["items"][0]["avg_score"] == 70
        with pytest.raises(HTTPException) as bad_sort:
            await jobs(
                date_from=now.date(),
                date_to=now.date(),
                job_id=None,
                company_id=None,
                page=1,
                page_size=20,
                sort="company_id",
                db=session,
                user=user,
            )
        assert bad_sort.value.status_code == 422

        candidate_data = await candidates(
            date_from=now.date(),
            date_to=now.date(),
            job_id=None,
            company_id=None,
            db=session,
            user=user,
        )
        assert candidate_data["data"]["score_distribution"][-1] == {
            "bucket": "unscored",
            "count": 2,
        }
        assert candidate_data["data"]["eligibility_distribution"] == {
            "eligible": 1,
            "needs_review": 1,
        }
        assert candidate_data["data"]["verification_distribution"] == {"not_verified": 4}
        assert "demographics" not in str(candidate_data).casefold()

        skill_data = await skills(
            date_from=now.date(),
            date_to=now.date(),
            job_id=None,
            company_id=None,
            limit=20,
            db=session,
            user=user,
        )
        assert skill_data["data"]["top_candidate_skills"] == [
            {"skill": "python", "candidate_count": 1, "share": 1 / 4}
        ]
        assert skill_data["data"]["top_required_skills"] == [
            {
                "requirement_id": str(requirement.id),
                "skill": "Python",
                "mandatory": True,
                "weight": 1.0,
                "coverage_rate": 1 / 4,
            }
        ]

        pipeline_data = await pipeline(
            date_from=now.date(),
            date_to=now.date(),
            job_id=None,
            company_id=None,
            db=session,
            user=user,
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


@pytest.mark.asyncio
async def test_deleted_candidates_applications_and_jobs_excluded_from_kpis(
        client, db_session, company_with_admin, admin_headers
):
    """Deleting a candidate (tombstone or purge), application, or job removes its details from all KPI endpoints."""
    from app.ai_features.models.candidate import Candidate

    company, _ = company_with_admin
    job_a = Job(
        company_id=company.id,
        title="Backend KPI Role",
        description="Python FastAPI services",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
        status=JobStatus.ACTIVE,
    )
    job_b = Job(
        company_id=company.id,
        title="ML KPI Role",
        description="PyTorch models",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
        status=JobStatus.ACTIVE,
    )
    db_session.add_all([job_a, job_b])
    await db_session.flush()
    db_session.add_all(
        [
            JobRequirement(
                job_id=job_a.id,
                category=RequirementCategory.SKILLS,
                name="Python",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=1.0,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job_b.id,
                category=RequirementCategory.SKILLS,
                name="PyTorch",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=1.0,
                is_mandatory=False,
            ),
        ]
    )
    await db_session.flush()

    async def _seed(job_obj, full_name, email, skill_name):
        cand = Candidate(company_id=company.id, full_name=full_name, email=email)
        db_session.add(cand)
        await db_session.flush()
        app_row = Application(
            company_id=company.id, job_id=job_obj.id, candidate_id=cand.id, status="applied"
        )
        db_session.add(app_row)
        await db_session.flush()
        resume = Resume(
            company_id=company.id,
            job_id=job_obj.id,
            application_id=app_row.id,
            original_filename=f"{full_name.lower().replace(' ', '_')}.pdf",
            extension="pdf",
            content_type="application/pdf",
            size_bytes=256,
            sha256=uuid4().hex * 2,
            storage_backend="local",
            storage_key=f"kpi-test/{app_row.id}.pdf",
            status="completed",
        )
        db_session.add(resume)
        await db_session.flush()
        db_session.add(
            ExtractedProfile(
                company_id=company.id,
                resume_id=resume.id,
                source_text=f"{full_name} {skill_name}",
                extraction_method="pdf_text",
                overall_confidence=0.9,
                profile_data={
                    "full_name": {"value": full_name, "confidence": 0.9},
                    "contact": {"email": {"value": email, "confidence": 0.9}},
                    "skills": [{"name": skill_name, "canonical_name": skill_name.lower()}],
                    "employment": [],
                    "education": [],
                    "projects": [],
                    "certifications": [],
                },
            )
        )
        await db_session.flush()
        return cand, app_row

    cand1, app1 = await _seed(job_a, "Alice One", "alice1@example.test", "Python")
    cand2, app2 = await _seed(job_a, "Bob Two", "bob2@example.test", "Rust")
    cand3, app3 = await _seed(job_b, "Cara Three", "cara3@example.test", "PyTorch")

    # Rank both jobs so RankingHistory + CandidateScore exist (triggering audit tombstones on soft delete)
    assert (
               await client.post(
                   f"/api/v1/jobs/{job_a.id}/rank", headers=admin_headers, json={"force_rescore": True}
               )
           ).status_code == 200
    assert (
               await client.post(
                   f"/api/v1/jobs/{job_b.id}/rank", headers=admin_headers, json={"force_rescore": True}
               )
           ).status_code == 200

    ov0 = (await client.get("/api/v1/analytics/overview", headers=admin_headers)).json()["data"]
    assert ov0["kpis"]["total_applications"] == 3
    assert ov0["kpis"]["open_jobs"] == 2

    # 1. Soft-delete ranked candidate 1 (creates audit tombstone) -> MUST disappear from all KPIs!
    r_del_c1 = await client.delete(f"/api/v1/candidates/{cand1.id}", headers=admin_headers)
    assert r_del_c1.status_code == 200

    ov1 = (await client.get("/api/v1/analytics/overview", headers=admin_headers)).json()["data"]
    assert ov1["kpis"]["total_applications"] == 2
    assert ov1["kpis"]["withdrawn_count"] == 0
    jobs1 = (await client.get("/api/v1/analytics/jobs", headers=admin_headers)).json()["data"]
    job_a_row = next(item for item in jobs1["items"] if item["id"] == str(job_a.id))
    assert job_a_row["applications"] == 1
    assert job_a_row["withdrawn"] == 0
    pipe1 = (await client.get("/api/v1/analytics/pipeline", headers=admin_headers)).json()["data"]
    assert sum(step["count"] for step in pipe1["funnel"]) == 2
    cands1 = (await client.get("/api/v1/analytics/candidates", headers=admin_headers)).json()["data"]
    assert sum(b["count"] for b in cands1["score_distribution"]) == 2
    skills1 = (await client.get("/api/v1/analytics/skills", headers=admin_headers)).json()["data"]
    assert all(s["skill"] != "python" for s in skills1["top_candidate_skills"])

    # 2. Soft-delete ranked application 2 -> MUST disappear from all KPIs!
    r_del_a2 = await client.delete(f"/api/v1/applications/{app2.id}", headers=admin_headers)
    assert r_del_a2.status_code == 200
    ov2 = (await client.get("/api/v1/analytics/overview", headers=admin_headers)).json()["data"]
    assert ov2["kpis"]["total_applications"] == 1
    assert ov2["kpis"]["withdrawn_count"] == 0

    # 3. Clean-delete active job_b (?purge=true) -> job & its application MUST disappear from all KPIs!
    r_del_jb = await client.delete(f"/api/v1/jobs/{job_b.id}?purge=true", headers=admin_headers)
    assert r_del_jb.status_code == 200
    assert r_del_jb.json()["data"]["jobs_deleted"] == 1
    assert r_del_jb.json()["data"]["applications_deleted"] == 1

    ov3 = (await client.get("/api/v1/analytics/overview", headers=admin_headers)).json()["data"]
    assert ov3["kpis"]["total_applications"] == 0
    assert ov3["kpis"]["open_jobs"] == 1
    assert ov3["kpis"]["average_latest_score"] == 0
    jobs3 = (await client.get("/api/v1/analytics/jobs", headers=admin_headers)).json()["data"]
    assert jobs3["total"] == 1
    assert all(item["id"] != str(job_b.id) for item in jobs3["items"])
    skills3 = (await client.get("/api/v1/analytics/skills", headers=admin_headers)).json()["data"]
    assert skills3["top_candidate_skills"] == []


@pytest.mark.asyncio
async def test_weekly_trend_includes_final_partial_week_bucket(
    client, db_session, company_with_admin, admin_headers
):
    """Weekly trend must include the end-date's week even when end.weekday() < start.weekday()."""
    from datetime import date

    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Trend Test Role",
        description="Test weekly trend",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
        status=JobStatus.ACTIVE,
    )
    db_session.add(job)
    await db_session.flush()

    # 2026-11-23 is a Monday; 89 days earlier is 2026-08-26 (Wednesday).
    # Previously, advancing +7 from Wednesday skipped Monday 2026-11-23!
    end_d = date(2026, 11, 23)
    start_d = end_d - timedelta(days=89)
    app_on_end = Application(
        company_id=company.id,
        job_id=job.id,
        status="applied",
        created_at=datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(app_on_end)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/analytics/overview?date_from={start_d.isoformat()}&date_to={end_d.isoformat()}&interval=week",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["trend"]["items"]
    assert items[-1] == {"bucket": "2026-11-23", "applications": 1}
    assert sum(i["applications"] for i in items) == 1
