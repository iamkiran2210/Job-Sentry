from __future__ import annotations

import uuid

import httpx
import pytest

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_requirement import (
    JobRequirement,
    RequirementCategory,
    RequirementImportance,
    RequirementType,
)


async def _add_applicant(db_session, company_id, job_id, name: str, profile_data: dict, source_text: str):
    cand = Candidate(
        company_id=company_id,
        full_name=name,
        email=f"{name.lower().replace(' ', '.')}@example.test",
    )
    db_session.add(cand)
    await db_session.flush()
    app = Application(
        company_id=company_id,
        job_id=job_id,
        candidate_id=cand.id,
        status="applied",
    )
    db_session.add(app)
    await db_session.flush()
    resume = Resume(
        company_id=company_id,
        job_id=job_id,
        application_id=app.id,
        original_filename=f"{name.lower().replace(' ', '_')}.pdf",
        extension="pdf",
        content_type="application/pdf",
        size_bytes=2048,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_backend="local",
        storage_key=f"test/{app.id}.pdf",
        status="completed",
    )
    db_session.add(resume)
    await db_session.flush()
    db_session.add(
        ExtractedProfile(
            company_id=company_id,
            resume_id=resume.id,
            source_text=source_text,
            profile_data=profile_data,
        )
    )
    await db_session.flush()
    return app


@pytest.mark.asyncio
async def test_realistic_end_to_end_ranking_scores_all_categories_and_ranks_accurately(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Senior Backend Engineer",
        description="Build scalable Python FastAPI microservices on AWS with PostgreSQL, Redis, and Docker.",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()

    db_session.add_all(
        [
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Python",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="PostgreSQL",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Docker",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="FastAPI",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=0.40,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Redis",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.30,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="AWS (EC2, S3)",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.30,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.EXPERIENCE,
                name="3+ years of backend software engineering",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.EDUCATION,
                name="Bachelor's degree in Computer Science",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.0,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.CERTIFICATION,
                name="AWS Certified Solutions Architect",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.LOW,
                weight=0.0,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.RESPONSIBILITY,
                name="Design and build scalable REST APIs and microservices",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.0,
                is_mandatory=False,
            ),
        ]
    )
    await db_session.flush()

    strong_app = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Alice Strong",
        {
            "skills": [
                {"name": "Python 3"},
                {"name": "PostgreSQL"},
                {"name": "FastAPI"},
                {"name": "Redis"},
                {"name": "AWS"},
            ],
            "employment": [
                {
                    "title": "Senior Backend Software Engineer",
                    "company": "CloudScale Inc",
                    "start_date": "2020-01",
                    "is_current": True,
                    "description": "Backend software engineering designing and building scalable Python FastAPI REST APIs and microservices on AWS with PostgreSQL and Redis.",
                }
            ],
            "projects": [
                {
                    "name": "Distributed Task Platform",
                    "description": "Designed and built scalable REST APIs and microservices with Docker and Redis.",
                    "technologies": ["Python", "FastAPI", "Docker", "Redis"],
                }
            ],
            "education": [{"degree": "B.Tech in Computer Science", "field_of_study": "Computer Science"}],
            "certifications": [{"name": "AWS Certified Solutions Architect - Associate"}],
        },
        "Senior Backend Software Engineer building Python FastAPI REST APIs and microservices with PostgreSQL, Redis, Docker, and AWS.",
    )

    mid_app = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Bob Partial",
        {
            "skills": [{"name": "Python"}, {"name": "PostgreSQL"}],
            "employment": [
                {
                    "title": "Junior Backend Developer",
                    "company": "Startup LLC",
                    "start_date": "2025-06",
                    "end_date": "2026-06",
                    "description": "Maintained internal Python scripts and PostgreSQL queries for backend software engineering.",
                }
            ],
            "projects": [
                {
                    "name": "Inventory REST API",
                    "description": "Simple REST API in Python.",
                    "technologies": ["Python", "PostgreSQL"],
                }
            ],
            "education": [{"degree": "Associate Degree in Information Technology"}],
            "certifications": [],
        },
        "Junior Backend Developer using Python and PostgreSQL.",
    )

    weak_app = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Charlie Mismatch",
        {
            "skills": [{"name": "Java"}, {"name": "Spring Boot"}, {"name": "MySQL"}],
            "employment": [
                {
                    "title": "Manual QA Analyst",
                    "company": "Retail Co",
                    "start_date": "2023-01",
                    "is_current": True,
                    "description": "Executed manual storefront UI test checklists and filed bug tickets.",
                }
            ],
            "projects": [
                {
                    "name": "Personal Recipe Blog",
                    "description": "Static brochure website for family recipes.",
                    "technologies": ["HTML", "CSS"],
                }
            ],
            "education": [{"degree": "High School Diploma"}],
            "certifications": [{"name": "Food Safety Handler"}],
        },
        "Manual QA Analyst executing storefront UI checklists.",
    )

    rank_resp = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"force_rescore": True},
    )
    assert rank_resp.status_code == 200
    ranked = rank_resp.json()["data"]
    assert ranked["total_count"] == 3
    ids_in_order = [item["application_id"] for item in ranked["items"]]
    assert ids_in_order == [str(strong_app.id), str(mid_app.id), str(weak_app.id)]

    strong_item, mid_item, weak_item = ranked["items"]
    assert strong_item["eligibility"] == "eligible"
    assert strong_item["score"] >= 85.0
    assert strong_item["data_completeness"] == 1.0
    assert strong_item["skills_score"] >= 0.95

    assert mid_item["eligibility"] == "potentially_ineligible"
    assert 20.0 <= mid_item["score"] < strong_item["score"]

    assert weak_item["eligibility"] == "potentially_ineligible"
    assert weak_item["score"] < 15.0

    # Verify detailed analysis for Strong candidate shows all 5 categories as known
    analysis_resp = await client.get(
        f"/api/v1/applications/{strong_app.id}/analysis", headers=admin_headers
    )
    assert analysis_resp.status_code == 200
    analysis = analysis_resp.json()["data"]
    for cat in ("skills", "experience", "projects", "education", "certifications"):
        assert analysis["categories"][cat]["status"] == "known", f"{cat} should be known"
        assert float(analysis["categories"][cat]["match"]) >= 0.85

    # Verify weak candidate has known (low) experience & projects instead of unknown
    weak_analysis = (
        await client.get(f"/api/v1/applications/{weak_app.id}/analysis", headers=admin_headers)
    ).json()["data"]
    assert weak_analysis["categories"]["experience"]["status"] == "known"
    assert float(weak_analysis["categories"]["experience"]["match"]) == 0.0
    assert weak_analysis["categories"]["projects"]["status"] == "known"
    assert float(weak_analysis["categories"]["projects"]["match"]) == 0.0


@pytest.mark.asyncio
async def test_preferred_skill_weights_and_skills_only_job_ranking(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Frontend Engineer",
        description="React and TypeScript frontend applications.",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all(
        [
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="React",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=0.80,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="GraphQL",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.LOW,
                weight=0.20,
                is_mandatory=False,
            ),
        ]
    )
    await db_session.flush()

    react_app = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Dana React",
        {
            "skills": [{"name": "React.js"}],
            "employment": [
                {
                    "title": "Frontend Developer",
                    "start_date": "2022-01",
                    "is_current": True,
                    "description": "Built SPAs with React and TypeScript.",
                }
            ],
            "projects": [
                {
                    "name": "Design System",
                    "description": "Component library built with React.",
                    "technologies": ["React"],
                }
            ],
            "education": [],
            "certifications": [],
        },
        "Frontend Developer built React apps.",
    )
    graphql_app = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Evan GraphQL",
        {
            "skills": [{"name": "GraphQL"}],
            "employment": [
                {
                    "title": "Data Entry Clerk",
                    "start_date": "2022-01",
                    "is_current": True,
                    "description": "Managed spreadsheets and invoices.",
                }
            ],
            "projects": [
                {
                    "name": "Budget Sheet",
                    "description": "Monthly expense spreadsheet.",
                    "technologies": ["Excel"],
                }
            ],
            "education": [],
            "certifications": [],
        },
        "Data Entry Clerk managing spreadsheets.",
    )

    resp = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": True}
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert [i["application_id"] for i in items] == [str(react_app.id), str(graphql_app.id)]
    assert items[0]["skills_score"] == pytest.approx(0.8, abs=0.01)
    assert items[1]["skills_score"] == pytest.approx(0.2, abs=0.01)
    assert items[0]["score"] > items[1]["score"]


@pytest.mark.asyncio
async def test_experience_claims_satisfy_mandatory_years_when_employment_dates_absent(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Python Engineer",
        description="Python backend systems",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        JobRequirement(
            job_id=job.id,
            category=RequirementCategory.EXPERIENCE,
            name="4+ years of Python backend",
            requirement_type=RequirementType.MANDATORY,
            importance=RequirementImportance.HIGH,
            weight=0.0,
            is_mandatory=True,
        )
    )
    await db_session.flush()

    app = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Fay Claim",
        {
            "skills": [{"name": "Python"}],
            "employment": [],
            "experience_claims": [
                {
                    "statement": "5+ years of Python backend engineering",
                    "area": "Python backend",
                    "years": 5.0,
                }
            ],
            "projects": [],
            "education": [],
            "certifications": [],
        },
        "5+ years of Python backend engineering.",
    )

    resp = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": True}
    )
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["application_id"] == str(app.id)
    assert item["eligibility"] == "eligible"
    assert item["score"] == 100.0


@pytest.mark.asyncio
async def test_individual_ranking_rescores_only_target_and_preserves_peers_while_force_all_rescores_everyone(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, monkeypatch
):
    from sqlalchemy import select
    from app.modules.candidate_intelligence.models import RankingRun
    from app.modules.candidate_intelligence.service import ScoringService

    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Backend Developer",
        description="Python and Docker",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all(
        [
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Python",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Docker",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=1.0,
                is_mandatory=False,
            ),
        ]
    )
    await db_session.flush()

    app1 = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Grace First",
        {
            "skills": [{"name": "Python"}],
            "employment": [],
            "projects": [],
            "education": [],
            "certifications": [],
        },
        "Python developer.",
    )
    app2 = await _add_applicant(
        db_session,
        company.id,
        job.id,
        "Henry Second",
        {
            "skills": [{"name": "Java"}],
            "employment": [],
            "projects": [],
            "education": [],
            "certifications": [],
        },
        "Java developer.",
    )

    # Initial full run scores both
    first = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": False}
    )
    assert first.status_code == 200
    assert [i["application_id"] for i in first.json()["data"]["items"]] == [
        str(app1.id),
        str(app2.id),
    ]

    # Upgrade app2's profile to have both Python and Docker
    profile2 = (
        await db_session.execute(
            select(ExtractedProfile)
            .join(Resume, Resume.id == ExtractedProfile.resume_id)
            .where(Resume.application_id == app2.id)
        )
    ).scalar_one()
    profile2.profile_data = {
        **profile2.profile_data,
        "skills": [{"name": "Python"}, {"name": "Docker"}],
    }
    await db_session.flush()

    scored_ids: list[uuid.UUID] = []
    orig_score = ScoringService.score_application

    async def spy_score(application_id, *args, **kwargs):
        scored_ids.append(application_id)
        return await orig_score(application_id, *args, **kwargs)

    monkeypatch.setattr(ScoringService, "score_application", staticmethod(spy_score))

    # 1. Rank specific individual (app2 only)
    indiv = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"application_ids": [str(app2.id)], "force_rescore": True},
    )
    assert indiv.status_code == 200
    assert scored_ids == [app2.id]
    indiv_data = indiv.json()["data"]
    assert indiv_data["total_count"] == 2
    assert [i["application_id"] for i in indiv_data["items"]] == [str(app2.id), str(app1.id)]
    indiv_run = await db_session.scalar(
        select(RankingRun).where(RankingRun.run_id == uuid.UUID(indiv_data["run_id"]))
    )
    assert indiv_run.counts == {"scored": 1, "skipped": 1, "failed": 0}

    # GET /ranking still shows both applicants with updated rank order
    page = await client.get(f"/api/v1/jobs/{job.id}/ranking", headers=admin_headers)
    assert page.status_code == 200
    assert [i["application_id"] for i in page.json()["data"]["items"]] == [
        str(app2.id),
        str(app1.id),
    ]

    # 2. Force re-score everyone separately
    scored_ids.clear()
    forced_all = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"force_rescore": True},
    )
    assert forced_all.status_code == 200
    assert set(scored_ids) == {app1.id, app2.id}
    all_run = await db_session.scalar(
        select(RankingRun).where(RankingRun.run_id == uuid.UUID(forced_all.json()["data"]["run_id"]))
    )
    assert all_run.counts == {"scored": 2, "skipped": 0, "failed": 0}
