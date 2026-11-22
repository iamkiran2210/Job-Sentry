import pytest
from app.core.security import create_access_token
from app.models.user import User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_current_user_profile(
        client: AsyncClient, registered_user: User, auth_headers: dict
):
    """Test retrieving current user profile with valid authentication."""
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == str(registered_user.id)
    assert data["data"]["email"] == registered_user.email
    assert data["data"]["role"] == registered_user.role.value
    assert data["data"]["is_active"] is True


@pytest.mark.asyncio
async def test_access_inactive_user(
    client: AsyncClient,
    registered_user: User,
    db_session: AsyncSession,
):
    """Test inactive user accounts are rejected with 403 Forbidden."""
    # Deactivate user in database
    registered_user.is_active = False
    await db_session.commit()

    # Create token for this now-inactive user
    token = create_access_token(
        subject=str(registered_user.id),
        role=registered_user.role.value,
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "deactivated" in data["message"].lower()


@pytest.mark.asyncio
async def test_role_validation_admin_success(client: AsyncClient, admin_headers: dict):
    """Test user holding ADMIN role is granted access to admin-only endpoint."""
    response = await client.get("/api/v1/users/admin/check", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["role"] == "admin"


@pytest.mark.asyncio
async def test_role_validation_recruiter_forbidden(client: AsyncClient, auth_headers: dict):
    """Test user holding RECRUITER role is forbidden from admin-only endpoint."""
    response = await client.get("/api/v1/users/admin/check", headers=auth_headers)
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "insufficient permissions" in data["message"].lower()


@pytest.mark.asyncio
async def test_delete_account_sole_owner_purges_company_and_all_data(
        client: AsyncClient, db_session: AsyncSession, company_with_admin, admin_headers: dict
):
    """Sole-owner account deletion removes user, tokens, company, jobs, candidates, applications, and resumes."""
    import uuid
    from sqlalchemy import func, select
    from app.ai_features.models.application import Application
    from app.ai_features.models.candidate import Candidate
    from app.ai_features.models.extracted_profile import ExtractedProfile
    from app.ai_features.models.resume import Resume
    from app.models.company import Company
    from app.models.job import EmploymentType, Job, JobStatus, WorkMode
    from app.models.token import RefreshToken

    company, admin_user = company_with_admin

    # Seed a job, candidate, application, resume, extracted profile, and ranking run
    job = Job(
        company_id=company.id,
        title="Account Delete Test Role",
        description="Python FastAPI",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
        status=JobStatus.ACTIVE,
    )
    db_session.add(job)
    await db_session.flush()
    cand = Candidate(company_id=company.id, full_name="Jane Sample", email="jane.sample@example.test")
    db_session.add(cand)
    await db_session.flush()
    app_row = Application(company_id=company.id, job_id=job.id, candidate_id=cand.id, status="applied")
    db_session.add(app_row)
    await db_session.flush()
    res = Resume(
        company_id=company.id,
        job_id=job.id,
        application_id=app_row.id,
        uploaded_by=admin_user.id,
        original_filename="jane.pdf",
        extension="pdf",
        content_type="application/pdf",
        size_bytes=128,
        sha256=uuid.uuid4().hex * 2,
        storage_backend="local",
        storage_key=f"acct-del/{app_row.id}.pdf",
        status="completed",
    )
    db_session.add(res)
    await db_session.flush()
    db_session.add(
        ExtractedProfile(
            company_id=company.id,
            resume_id=res.id,
            source_text="Jane Sample Python",
            extraction_method="pdf_text",
            overall_confidence=0.9,
            profile_data={"skills": [{"name": "Python"}]},
        )
    )
    await db_session.commit()

    # Rank to populate candidate_scores, ranking_run, ranking_history
    rank_resp = await client.post(
        f"/api/v1/jobs/{job.id}/rank", headers=admin_headers, json={"force_rescore": True}
    )
    assert rank_resp.status_code == 200

    # Delete account
    del_resp = await client.delete("/api/v1/users/me", headers=admin_headers)
    assert del_resp.status_code == 200
    payload = del_resp.json()["data"]
    assert payload["deleted"] is True
    assert payload["company_deleted"] is True
    assert payload["jobs_deleted"] == 1
    assert payload["candidates_deleted"] == 1
    assert payload["applications_deleted"] == 1
    assert payload["resumes_deleted"] == 1

    # Zero breadcrumbs remain in DB
    assert await db_session.scalar(select(func.count()).select_from(User).where(User.id == admin_user.id)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Company).where(Company.id == company.id)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Job).where(Job.company_id == company.id)) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(Candidate).where(Candidate.company_id == company.id)) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(Application).where(Application.company_id == company.id)) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == admin_user.id)) == 0

    # Existing JWT is immediately rejected
    me_after = await client.get("/api/v1/users/me", headers=admin_headers)
    assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_shared_company_preserves_workspace_and_promotes_member(
        client: AsyncClient, db_session: AsyncSession, company_with_admin, admin_headers: dict
):
    """When other company members exist, deleting the last admin preserves the company and promotes a member."""
    from sqlalchemy import select
    from app.core.security import hash_password
    from app.models.company import Company
    from app.models.user import AuthProvider, UserRole

    company, admin_user = company_with_admin
    teammate = User(
        name="Teammate Recruiter",
        email="teammate.keep@example.com",
        password_hash=hash_password("ValidPass123!"),
        role=UserRole.RECRUITER,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(teammate)
    await db_session.commit()

    del_resp = await client.delete("/api/v1/users/me", headers=admin_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["data"]["deleted"] is True
    assert del_resp.json()["data"]["company_deleted"] is False

    # Company still exists and teammate was promoted to ADMIN
    kept_company = await db_session.get(Company, company.id)
    assert kept_company is not None
    await db_session.refresh(teammate)
    assert teammate.role == UserRole.ADMIN
    assert (await db_session.execute(select(User).where(User.id == admin_user.id))).scalar_one_or_none() is None
