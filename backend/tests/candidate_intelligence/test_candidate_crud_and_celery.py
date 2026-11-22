from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.ai_features.ai.errors import AIError, AIErrorKind
from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.ai_features.resumes.llm import AIProfileProvider, reset_provider_cooldown
from app.models.job import EmploymentType, Job, WorkMode
from app.modules.candidate_intelligence.models import RankingHistory


async def _seed_candidate_with_app(db_session, company_id, job_id, name="Asha Rao", email="asha@example.test"):
    cand = Candidate(
        company_id=company_id,
        full_name=name,
        email=email,
        phone="+14155552671",
    )
    db_session.add(cand)
    await db_session.flush()
    app = Application(company_id=company_id, job_id=job_id, candidate_id=cand.id, status="applied")
    db_session.add(app)
    await db_session.flush()
    resume = Resume(
        company_id=company_id,
        job_id=job_id,
        application_id=app.id,
        original_filename="asha.pdf",
        extension="pdf",
        content_type="application/pdf",
        size_bytes=512,
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
            source_text="Asha Rao Python developer",
            extraction_method="pdf_text",
            overall_confidence=0.85,
            profile_data={
                "full_name": {"value": name, "confidence": 0.9, "evidence": name},
                "contact": {
                    "email": {"value": email, "confidence": 0.95, "evidence": email},
                },
                "skills": [{"name": "Python", "confidence": 0.9, "evidence": "Python"}],
                "employment": [],
                "education": [],
                "projects": [],
                "certifications": [],
            },
        )
    )
    await db_session.flush()
    return cand, app


@pytest.mark.asyncio
async def test_update_candidate_details_syncs_identity_and_profile(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Backend Engineer",
        description="Python services",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    cand, app = await _seed_candidate_with_app(db_session, company.id, job.id)

    resp = await client.patch(
        f"/api/v1/candidates/{cand.id}",
        headers=admin_headers,
        json={
            "full_name": "Asha K. Rao",
            "email": "asha.updated@example.test",
            "phone": "+14155559999",
            "location": "Bengaluru, IN",
            "github_url": "https://github.com/asharao",
            "portfolio_url": "https://asharao.dev",
            "summary": "Senior distributed systems engineer.",
            "skills": ["Python", "FastAPI", "Kubernetes"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["full_name"] == "Asha K. Rao"
    assert data["email"] == "asha.updated@example.test"
    assert data["phone"] == "+14155559999"
    prof = data["latest_profile"]["data"]
    assert prof["contact"]["github_url"]["value"] == "https://github.com/asharao"
    assert prof["contact"]["portfolio_url"]["value"] == "https://asharao.dev"
    assert prof["contact"]["location"]["value"] == "Bengaluru, IN"
    assert prof["summary"] == "Senior distributed systems engineer."
    assert [s["name"] for s in prof["skills"]] == ["Python", "FastAPI", "Kubernetes"]

    # Confirm updated details propagate to /applications/{id}/analysis
    analysis = (
        await client.get(f"/api/v1/applications/{app.id}/analysis", headers=admin_headers)
    ).json()["data"]
    assert analysis["candidate"]["display_name"] == "Asha K. Rao"
    assert analysis["candidate"]["links"]["github_url"] == "https://github.com/asharao"
    assert analysis["candidate"]["links"]["portfolio_url"] == "https://asharao.dev"


@pytest.mark.asyncio
async def test_delete_candidate_works_before_and_after_ranking_preserving_audit_history(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Platform Engineer",
        description="Build platforms",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    cand_unranked, _ = await _seed_candidate_with_app(
        db_session, company.id, job.id, "Unranked User", "unranked@example.test"
    )
    cand_ranked, app_ranked = await _seed_candidate_with_app(
        db_session, company.id, job.id, "Ranked User", "ranked@example.test"
    )

    # 1. Delete unranked candidate
    del1 = await client.delete(f"/api/v1/candidates/{cand_unranked.id}", headers=admin_headers)
    assert del1.status_code == 200
    assert del1.json()["data"]["deleted"] is True
    assert (
               await client.get(f"/api/v1/candidates/{cand_unranked.id}", headers=admin_headers)
           ).status_code == 404

    # 2. Rank remaining candidate so append-only ranking_history references app_ranked
    ranked = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": True}
    )
    assert ranked.status_code == 200
    history_before = await db_session.scalar(
        select(func.count()).select_from(RankingHistory).where(RankingHistory.job_id == job.id)
    )
    assert history_before >= 1

    # 3. Delete ranked candidate — must succeed without violating append-only trigger!
    del2 = await client.delete(f"/api/v1/candidates/{cand_ranked.id}", headers=admin_headers)
    assert del2.status_code == 200
    assert del2.json()["data"]["deleted"] is True
    assert (
               await client.get(f"/api/v1/candidates/{cand_ranked.id}", headers=admin_headers)
           ).status_code == 404

    # Immutable ranking_history preserved, and candidate is hidden from job applicants & new ranking runs
    history_after = await db_session.scalar(
        select(func.count()).select_from(RankingHistory).where(RankingHistory.job_id == job.id)
    )
    assert history_after == history_before
    applicants = (
        await client.get(f"/api/v1/jobs/{job.id}/applicants", headers=admin_headers)
    ).json()["data"]
    assert applicants == []


@pytest.mark.asyncio
async def test_ai_profile_provider_cooldown_fast_fails_after_429(monkeypatch):
    reset_provider_cooldown()
    cloud_calls = 0

    class FailingExtractor:
        model_label = "google:gemini-quota-test"

        async def run(self, text: str):
            nonlocal cloud_calls
            cloud_calls += 1
            raise AIError(AIErrorKind.UNAVAILABLE, detail="HTTP 429", retryable=True)

    monkeypatch.setattr("app.ai_features.resumes.llm.get_extractor", lambda name: FailingExtractor())
    provider = AIProfileProvider()

    r1 = await provider.extract_profile(resume_text="Jane Doe\njane@example.com\nSkills\nPython, SQL")
    r2 = await provider.extract_profile(resume_text="John Smith\njohn@example.com\nSkills\nGo, Docker")

    # First call hits cloud (429) and falls back; second call skips cloud immediately via cooldown!
    assert cloud_calls == 1
    assert r1.model == "heuristic"
    assert r2.model == "heuristic"
    reset_provider_cooldown()


@pytest.mark.asyncio
async def test_delete_application_and_resume_before_and_after_ranking(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Site Reliability Engineer",
        description="Operate production systems",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()

    _, app_unranked = await _seed_candidate_with_app(
        db_session, company.id, job.id, "Unranked App", "unranked.app@example.test"
    )
    _, app_ranked = await _seed_candidate_with_app(
        db_session, company.id, job.id, "Ranked App", "ranked.app@example.test"
    )
    _, app_by_resume = await _seed_candidate_with_app(
        db_session, company.id, job.id, "Resume App", "resume.app@example.test"
    )
    resume_for_delete = (
        await db_session.execute(
            select(Resume).where(Resume.application_id == app_by_resume.id)
        )
    ).scalar_one()

    # 1. Delete unranked application directly -> hard-deleted
    r_del1 = await client.delete(
        f"/api/v1/applications/{app_unranked.id}", headers=admin_headers
    )
    assert r_del1.status_code == 200
    d1 = r_del1.json()["data"]
    assert d1["deleted"] is True
    assert d1["resumes_deleted"] == 1
    assert d1["audit_preserved"] is False
    assert (
               await client.get(f"/api/v1/applications/{app_unranked.id}", headers=admin_headers)
           ).status_code == 404

    # 2. Delete by resume_id -> deletes the resume and its owning application
    r_del_res = await client.delete(
        f"/api/v1/resumes/{resume_for_delete.id}", headers=admin_headers
    )
    assert r_del_res.status_code == 200
    d_res = r_del_res.json()["data"]
    assert d_res["deleted"] is True
    assert d_res["application_id"] == str(app_by_resume.id)
    assert d_res["resumes_deleted"] == 1
    assert (
               await client.get(f"/api/v1/resumes/{resume_for_delete.id}", headers=admin_headers)
           ).status_code == 404
    assert (
               await client.get(f"/api/v1/applications/{app_by_resume.id}", headers=admin_headers)
           ).status_code == 404

    # 3. Rank remaining application so append-only ranking_history references app_ranked
    ranked = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": True}
    )
    assert ranked.status_code == 200
    history_before = await db_session.scalar(
        select(func.count()).select_from(RankingHistory).where(RankingHistory.job_id == job.id)
    )
    assert history_before >= 1

    ranking_before = (
        await client.get(f"/api/v1/jobs/{job.id}/ranking", headers=admin_headers)
    ).json()["data"]
    assert len(ranking_before["items"]) == 1
    assert ranking_before["items"][0]["application_id"] == str(app_ranked.id)

    # 4. Delete ranked application -> audit preserved, hidden immediately from ranking and applicants
    r_del2 = await client.delete(
        f"/api/v1/applications/{app_ranked.id}", headers=admin_headers
    )
    assert r_del2.status_code == 200
    d2 = r_del2.json()["data"]
    assert d2["deleted"] is True
    assert d2["resumes_deleted"] == 1
    assert d2["audit_preserved"] is True

    history_after = await db_session.scalar(
        select(func.count()).select_from(RankingHistory).where(RankingHistory.job_id == job.id)
    )
    assert history_after == history_before

    ranking_after = (
        await client.get(f"/api/v1/jobs/{job.id}/ranking", headers=admin_headers)
    ).json()["data"]
    assert ranking_after["items"] == []
    assert ranking_after["total_count"] == 0

    applicants_after = (
        await client.get(f"/api/v1/jobs/{job.id}/applicants", headers=admin_headers)
    ).json()["data"]
    assert applicants_after == []


@pytest.mark.asyncio
async def test_clean_delete_candidate_purges_all_records_and_files(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    from app.modules.application_status.models import ApplicationStatusHistory
    from app.modules.candidate_intelligence.models import (
        CandidateScore,
        ScoreEvidenceRecord,
        VerificationResult,
    )

    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Data Platform Engineer",
        description="Build data platforms with Python",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()

    cand, app = await _seed_candidate_with_app(
        db_session, company.id, job.id, "Purge Target", "purge.target@example.test"
    )
    resume = (
        await db_session.execute(select(Resume).where(Resume.application_id == app.id))
    ).scalar_one()

    # Rank (creates CandidateScore, ScoreEvidenceRecord, VerificationResult, RankingHistory)
    ranked = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": True}
    )
    assert ranked.status_code == 200

    # Record a status transition (creates ApplicationStatusHistory)
    app.status = "analyzed"
    await db_session.flush()
    st_resp = await client.patch(
        f"/api/v1/applications/{app.id}/status",
        headers=admin_headers,
        json={"status": "shortlisted", "reason": "Strong profile"},
    )
    assert st_resp.status_code == 200

    # Confirm rows exist across all tables before clean delete
    assert await db_session.scalar(
        select(func.count()).select_from(RankingHistory).where(RankingHistory.application_id == app.id)
    ) >= 1
    assert await db_session.scalar(
        select(func.count()).select_from(ApplicationStatusHistory).where(
            ApplicationStatusHistory.application_id == app.id)
    ) >= 1
    assert await db_session.scalar(
        select(func.count()).select_from(CandidateScore).where(CandidateScore.application_id == app.id)
    ) >= 1
    assert await db_session.scalar(
        select(func.count()).select_from(VerificationResult).where(VerificationResult.application_id == app.id)
    ) >= 1

    # Execute Data Explorer clean delete (?purge=true)
    resp = await client.delete(
        f"/api/v1/candidates/{cand.id}?purge=true", headers=admin_headers
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deleted"] is True
    assert data["clean_deleted"] is True
    assert data["applications_cleaned"] == 1
    assert data["resumes_deleted"] == 1
    assert data["scores_deleted"] >= 1
    assert data["verifications_deleted"] >= 1
    assert data["audit_records_deleted"] >= 2

    # Zero rows left across EVERY table (no tombstones!)
    assert await db_session.scalar(
        select(func.count()).select_from(Candidate).where(Candidate.id == cand.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(Application).where(Application.id == app.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(Resume).where(Resume.id == resume.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(ExtractedProfile).where(ExtractedProfile.resume_id == resume.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(CandidateScore).where(CandidateScore.application_id == app.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(ScoreEvidenceRecord).where(ScoreEvidenceRecord.application_id == app.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(VerificationResult).where(VerificationResult.application_id == app.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(RankingHistory).where(RankingHistory.application_id == app.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(ApplicationStatusHistory).where(
            ApplicationStatusHistory.application_id == app.id)
    ) == 0


@pytest.mark.asyncio
async def test_data_explorer_delete_all_jobs_candidates_and_team(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers
):
    from app.models.job import JobStatus
    from app.models.user import User, UserRole
    from app.modules.candidate_intelligence.models import RankingRun

    company, admin_user = company_with_admin

    # Seed 2 jobs (one active, one draft), 2 candidates, and 2 non-admin recruiters
    job_a = Job(
        company_id=company.id,
        title="Backend Lead",
        description="Python services",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
        status=JobStatus.ACTIVE,
    )
    job_b = Job(
        company_id=company.id,
        title="Frontend Engineer",
        description="Svelte UI",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
        status=JobStatus.DRAFT,
    )
    recruiter1 = User(
        name="Recruiter One",
        email=f"rec1-{uuid.uuid4().hex[:8]}@example.test",
        company_id=company.id,
        role=UserRole.RECRUITER,
    )
    recruiter2 = User(
        name="Recruiter Two",
        email=f"rec2-{uuid.uuid4().hex[:8]}@example.test",
        company_id=company.id,
        role=UserRole.RECRUITER,
    )
    db_session.add_all([job_a, job_b, recruiter1, recruiter2])
    await db_session.flush()

    await _seed_candidate_with_app(db_session, company.id, job_a.id, "Cand One", "c1@example.test")
    await _seed_candidate_with_app(db_session, company.id, job_a.id, "Cand Two", "c2@example.test")
    assert (
               await client.post(
                   f"/api/v1/jobs/{job_a.id}/rank", headers=admin_headers, json={"force_rescore": True}
               )
           ).status_code == 200

    # 1. Delete all candidates (Data Explorer)
    r_cands = await client.delete("/api/v1/candidates", headers=admin_headers)
    assert r_cands.status_code == 200
    assert r_cands.json()["data"]["candidates_deleted"] == 2
    assert r_cands.json()["data"]["applications_cleaned"] == 2
    assert await db_session.scalar(
        select(func.count()).select_from(Candidate).where(Candidate.company_id == company.id)
    ) == 0

    # 2. Delete all jobs (Data Explorer) — including active job with RankingRun
    r_jobs = await client.delete("/api/v1/jobs", headers=admin_headers)
    assert r_jobs.status_code == 200
    assert r_jobs.json()["data"]["jobs_deleted"] == 2
    assert await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.company_id == company.id)
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(RankingRun).where(RankingRun.job_id == job_a.id)
    ) == 0

    # 3. Remove all non-admin team members while preserving admin
    r_team = await client.delete("/api/v1/companies/me/members", headers=admin_headers)
    assert r_team.status_code == 200
    assert r_team.json()["data"]["members_removed"] == 2
    assert r_team.json()["data"]["admins_preserved"] >= 1
    remaining = (
        await client.get("/api/v1/companies/me/members", headers=admin_headers)
    ).json()["data"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == str(admin_user.id)
