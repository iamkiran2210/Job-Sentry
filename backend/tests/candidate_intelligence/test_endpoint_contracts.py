from __future__ import annotations

import uuid

import httpx
import pytest
from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.core.security import create_access_token
from app.models.company import Company
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_access import JobAccess, JobAccessLevel
from app.models.user import User, UserRole
from app.modules.candidate_intelligence.models import (
    CandidateScore,
    RankingHistory,
    RankingRun,
    ScoreEvidenceRecord,
    VerificationResult,
)
from app.modules.candidate_intelligence.service import CandidateIntelligenceService, ScoringService
from fastapi import HTTPException
from sqlalchemy import func, select


async def make_job_application(db_session, company, profile_data=None):
    job = Job(
        company_id=company.id,
        title="Contract role",
        description="Build software",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    application = Application(company_id=company.id, job_id=job.id, status="applied")
    db_session.add(application)
    await db_session.flush()
    if profile_data is not None:
        resume = Resume(
            company_id=company.id,
            job_id=job.id,
            application_id=application.id,
            original_filename="candidate.pdf",
            extension="pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256=uuid.uuid4().hex,
            storage_backend="local",
            storage_key="test/candidate.pdf",
        )
        db_session.add(resume)
        await db_session.flush()
        db_session.add(
            ExtractedProfile(
                company_id=company.id,
                resume_id=resume.id,
                source_text="Backend developer built APIs.",
                profile_data=profile_data,
            )
        )
        await db_session.flush()
    return job, application


@pytest.mark.asyncio
async def test_post_verify_records_all_checks_returns_disclaimer_and_masks_contact(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    raw_email, raw_phone = "private.candidate@example.com", "+14155552671"
    _, application = await make_job_application(
        db_session,
        company,
        {
            "skills": ["Python"],
            "employment": [],
            "education": [],
            "projects": [],
            "certifications": [],
            "contact": {"email": {"value": raw_email}, "phone": {"value": raw_phone}},
        },
    )
    response = await client.post(
        f"/api/v1/applications/{application.id}/verify", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert {row["check_type"] for row in data["checks"]} >= {
        "email_syntax",
        "phone_format",
        "resume_completeness",
        "timeline_consistency",
        "duplicate_signal",
    }
    assert "do not prove identity, employment or skill" in data["disclaimer"]
    assert raw_email not in response.text and raw_phone not in response.text
    phone = next(row for row in data["checks"] if row["check_type"] == "phone_format")
    assert phone["details"]["normalized_e164"].endswith("2671")
    assert "14155552671" not in phone["details"]["normalized_e164"]
    assert await db_session.scalar(
        select(func.count())
        .select_from(VerificationResult)
        .where(VerificationResult.application_id == application.id)
    ) == len(data["checks"])


@pytest.mark.asyncio
async def test_get_analysis_before_scoring_is_read_only_and_has_not_scored_contract(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, monkeypatch
):
    company, admin = company_with_admin
    _, application = await make_job_application(db_session, company)
    before = (
        await db_session.scalar(select(func.count()).select_from(CandidateScore)),
        await db_session.scalar(select(func.count()).select_from(ScoreEvidenceRecord)),
    )

    async def fail(*args, **kwargs):
        raise AssertionError("GET analysis attempted to score")

    monkeypatch.setattr(ScoringService, "score_application", staticmethod(fail))
    response = await client.get(
        f"/api/v1/applications/{application.id}/analysis", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["score"] is None and data["evidence"] == [] and data["status_note"] == "not_scored"
    after = (
        await db_session.scalar(select(func.count()).select_from(CandidateScore)),
        await db_session.scalar(select(func.count()).select_from(ScoreEvidenceRecord)),
    )
    assert after == before


@pytest.mark.asyncio
async def test_get_ranking_and_history_are_read_only_and_return_empty_without_a_run(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, monkeypatch
):
    company, _ = company_with_admin
    job, _ = await make_job_application(db_session, company)

    async def fail(*args, **kwargs):
        raise AssertionError("GET route attempted to score")

    monkeypatch.setattr(ScoringService, "score_application", staticmethod(fail))
    before = await db_session.scalar(select(func.count()).select_from(RankingRun))
    ranking = await client.get(f"/api/v1/jobs/{job.id}/ranking", headers=admin_headers)
    history = await client.get(f"/api/v1/jobs/{job.id}/ranking/history", headers=admin_headers)
    assert (
            ranking.status_code == 200
            and ranking.json()["data"]["run_id"] is None
            and ranking.json()["data"]["items"] == []
    )
    assert history.status_code == 200 and history.json()["data"]["items"] == []
    assert await db_session.scalar(select(func.count()).select_from(RankingRun)) == before


@pytest.mark.asyncio
async def test_post_rank_creates_run_and_returns_versions(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job, application = await make_job_application(db_session, company)
    response = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"application_ids": [str(application.id)], "force_rescore": False},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert (
            data["run_id"]
            and data["count"] == 1
            and data["scoring_version"]
            and data["algorithm_version"]
    )
    assert data["items"][0]["application_id"] == str(application.id)
    run = await db_session.scalar(
        select(RankingRun).where(RankingRun.run_id == uuid.UUID(data["run_id"]))
    )
    assert run is not None and run.counts == {"scored": 1, "skipped": 0, "failed": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"application_ids": [str(uuid.uuid4())]},
        {"scoring_version": "unknown-version"},
        {"unexpected": "extra"},
    ],
)
async def test_post_rank_rejects_out_of_job_ids_unknown_version_and_extra_fields(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, body
):
    company, _ = company_with_admin
    job, _ = await make_job_application(db_session, company)
    response = await client.post(f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json=body)
    assert response.status_code == 422
    if "application_ids" in body:
        assert body["application_ids"][0] in response.text


@pytest.mark.asyncio
async def test_post_rank_returns_409_when_job_lock_is_contended(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, monkeypatch
):
    company, _ = company_with_admin
    job, _ = await make_job_application(db_session, company)

    async def locked(*args, **kwargs):
        raise HTTPException(
            status_code=409, detail="A ranking run is already in progress for this job"
        )

    monkeypatch.setattr(CandidateIntelligenceService, "rank", staticmethod(locked))
    response = await client.post(f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={})
    assert response.status_code == 409
    assert "already in progress" in response.text


@pytest.mark.asyncio
async def test_ranking_filters_scores_pagination_unknown_run_and_history_contract(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, user = company_with_admin
    job, application = await make_job_application(db_session, company)
    ranked = await client.post(f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={})
    assert ranked.status_code == 200
    run_id = ranked.json()["data"]["run_id"]
    page = await client.get(
        f"/api/v1/jobs/{job.id}/ranking",
        headers=admin_headers,
        params={"run_id": run_id, "page": 1, "page_size": 1},
    )
    assert page.status_code == 200
    pdata = page.json()["data"]
    assert pdata["run_id"] == run_id and pdata["scoring_version"] and pdata["algorithm_version"]
    assert pdata["filters_applied"] == {}
    unknown = await client.get(
        f"/api/v1/jobs/{job.id}/ranking",
        headers=admin_headers,
        params={"run_id": str(uuid.uuid4())},
    )
    assert unknown.status_code == 404
    invalid = await client.get(
        f"/api/v1/jobs/{job.id}/ranking",
        headers=admin_headers,
        params={"min_score": 90, "max_score": 10},
    )
    assert invalid.status_code == 422
    for params in (
            {"min_score": -1},
            {"max_score": 101},
            {"eligibility": "unknown"},
            {"verification_status": "unknown"},
            {"page_size": 101},
    ):
        assert (
                   await client.get(f"/api/v1/jobs/{job.id}/ranking", headers=admin_headers, params=params)
               ).status_code == 422
    history = await client.get(f"/api/v1/jobs/{job.id}/ranking/history", headers=admin_headers)
    assert history.status_code == 200
    run_summary = history.json()["data"]["items"][0]
    assert run_summary["run_id"] == run_id and run_summary["job_id"] == str(job.id)
    assert run_summary["triggered_by"] == str(user.id)


@pytest.mark.asyncio
async def test_resources_are_company_scoped_and_missing_resources_return_404(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    own_job, _ = await make_job_application(db_session, company)
    other_company = Company(name="Separate Company")
    db_session.add(other_company)
    await db_session.flush()
    other_job, other_application = await make_job_application(db_session, other_company)
    for url in (
            f"/api/v1/applications/{other_application.id}/analysis",
            f"/api/v1/jobs/{other_job.id}/ranking",
            f"/api/v1/jobs/{uuid.uuid4()}/ranking/history",
    ):
        response = await client.get(url, headers=admin_headers)
        assert response.status_code == 404
    assert (
               await client.get(f"/api/v1/jobs/{own_job.id}/ranking", headers=admin_headers)
           ).status_code == 200


@pytest.mark.asyncio
async def test_viewer_access_cannot_run_verify_or_rank(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, admin = company_with_admin
    own_job, app = await make_job_application(db_session, company)
    foreign_company = Company(name="External Company")
    db_session.add(foreign_company)
    await db_session.flush()
    job, application = await make_job_application(db_session, foreign_company)
    viewer = User(
        name="Viewer",
        email=f"viewer-{uuid.uuid4()}@example.test",
        role=UserRole.RECRUITER,
        company_id=company.id,
    )
    db_session.add(viewer)
    await db_session.flush()
    db_session.add(
        JobAccess(
            job_id=job.id,
            user_id=viewer.id,
            access_level=JobAccessLevel.VIEWER,
            granted_by_id=admin.id,
        )
    )
    await db_session.commit()
    viewer_headers = {
        "Authorization": f"Bearer {create_access_token(subject=str(viewer.id), role=viewer.role.value, company_id=str(company.id))}"
    }
    assert (
               await client.post(f"/api/v1/applications/{application.id}/verify", headers=viewer_headers)
           ).status_code == 403
    assert (
               await client.post(f"/api/v1/jobs/{job.id}/rank", headers=viewer_headers, json={})
           ).status_code == 403


@pytest.mark.asyncio
async def test_decision_agents_endpoint_and_ranking_decision_filters(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job, application = await make_job_application(db_session, company)

    # 1. List available decision agents
    agents_resp = await client.get("/api/v1/decision-agents", headers=admin_headers)
    assert agents_resp.status_code == 200
    agents_data = agents_resp.json()["data"]
    assert agents_data["default_agent"] == "balanced"
    assert {a["id"] for a in agents_data["agents"]} == {
        "balanced",
        "bar_raiser",
        "growth_potential",
        "risk_guardian",
    }

    # 2. Rank job -> every ranked item includes decision + all 4 agent_decisions
    ranked = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"decision_agent": "bar_raiser"},
    )
    assert ranked.status_code == 200
    rdata = ranked.json()["data"]
    assert rdata["decision_agent"] == "bar_raiser"
    assert len(rdata["items"]) == 1
    item = rdata["items"][0]
    assert item["decision"]["agent_id"] == "bar_raiser"
    assert set(item["agent_decisions"].keys()) == {
        "balanced",
        "bar_raiser",
        "growth_potential",
        "risk_guardian",
    }

    # 3. Switching decision_agent via GET /ranking query param switches projected decision
    switched = await client.get(
        f"/api/v1/jobs/{job.id}/ranking",
        headers=admin_headers,
        params={"decision_agent": "risk_guardian"},
    )
    assert switched.status_code == 200
    sdata = switched.json()["data"]
    assert sdata["decision_agent"] == "risk_guardian"
    assert sdata["items"][0]["decision"]["agent_id"] == "risk_guardian"
    chosen_outcome = sdata["items"][0]["decision"]["decision"]

    # 4. Filtering by decision outcome matches or excludes cleanly
    matched = await client.get(
        f"/api/v1/jobs/{job.id}/ranking",
        headers=admin_headers,
        params={"decision_agent": "risk_guardian", "decision": chosen_outcome},
    )
    assert matched.status_code == 200
    assert matched.json()["data"]["total_count"] == 1

    # 5. Analysis endpoint also exposes decision and agent_decisions
    analysis = await client.get(
        f"/api/v1/applications/{application.id}/analysis", headers=admin_headers
    )
    assert analysis.status_code == 200
    adata = analysis.json()["data"]
    assert adata["decision"] is not None
    assert set(adata["agent_decisions"].keys()) == {
        "balanced",
        "bar_raiser",
        "growth_potential",
        "risk_guardian",
    }

    # 6. Configurable threshold + optional auto-apply + candidate notification endpoint
    auto_rank = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={
            "decision_agent": "balanced",
            "min_accept_threshold": 60.0,
            "auto_apply_decisions": True,
        },
    )
    assert auto_rank.status_code == 200
    ardata = auto_rank.json()["data"]
    assert ardata["min_accept_threshold"] == 60.0
    assert ardata["items"][0]["decision"]["threshold_outcome"] in {"accept", "reject", "review"}

    notify = await client.post(
        f"/api/v1/applications/{application.id}/notify",
        headers=admin_headers,
        json={"outcome": "shortlisted", "include_score": True},
    )
    assert notify.status_code == 200
    ndata = notify.json()["data"]
    assert ndata["application_id"] == str(application.id)
    assert "Contract role" in ndata["subject"]
