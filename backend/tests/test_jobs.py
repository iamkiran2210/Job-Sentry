import pytest
from app.core.security import create_access_token
from app.models.company import Company
from app.models.user import AuthProvider, User, UserRole
from app.modules.jobs.provider import get_requirement_extraction_provider
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

JOB_PAYLOAD = {
    "title": "Senior Backend Engineer",
    "description": "Build reliable distributed services and APIs.",
    "department": "Engineering",
    "employment_type": "full_time",
    "work_mode": "hybrid",
    "location": "Bengaluru",
    "openings": 2,
}


def headers_for(user: User) -> dict[str, str]:
    token = create_access_token(
        subject=str(user.id),
        role=user.role.value,
        company_id=str(user.company_id) if user.company_id else None,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_job_crud_and_draft_deletion(client: AsyncClient, company_with_admin, admin_headers):
    created = await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)
    assert created.status_code == 201
    job_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "draft"

    listed = await client.get("/api/v1/jobs", headers=admin_headers)
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1

    updated = await client.put(
        f"/api/v1/jobs/{job_id}",
        json={"title": "Staff Engineer"},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "Staff Engineer"

    deleted = await client.delete(f"/api/v1/jobs/{job_id}", headers=admin_headers)
    assert deleted.status_code == 200
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers)).status_code == 404


@pytest.mark.asyncio
async def test_recruiter_can_manage_jobs_within_company(
        client: AsyncClient, company_with_admin, db_session: AsyncSession
):
    company, _ = company_with_admin
    recruiter = User(
        name="Recruiter",
        email="jobs-recruiter@example.com",
        role=UserRole.RECRUITER,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(recruiter)
    await db_session.commit()
    response = await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=headers_for(recruiter))
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]
    access_response = await client.post(
        f"/api/v1/jobs/{job_id}/access",
        json={"email": "someone@example.com", "access_level": "viewer"},
        headers=headers_for(recruiter),
    )
    assert access_response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_grant_and_revoke_company_access(
        client, company_with_admin, admin_headers, registered_user, auth_headers
):
    created_job = await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)
    assert created_job.status_code == 201

    granted = await client.post(
        "/api/v1/companies/me/members",
        json={"email": registered_user.email},
        headers=admin_headers,
    )
    assert granted.status_code == 201
    assert granted.json()["data"]["role"] == "recruiter"
    assert (await client.get("/api/v1/jobs", headers=auth_headers)).json()["data"]
    overview = (await client.get("/api/v1/users/me/access", headers=auth_headers)).json()["data"]
    assert overview["company_access"]["company_name"] == "Acme Corp"
    assert overview["job_accesses"][0]["access_source"] == "company"

    revoked = await client.delete(
        f"/api/v1/companies/me/members/{registered_user.id}", headers=admin_headers
    )
    assert revoked.status_code == 200
    assert (await client.get("/api/v1/jobs", headers=auth_headers)).json()["data"] == []


@pytest.mark.asyncio
async def test_admin_can_grant_viewer_or_editor_access_to_one_job(
        client, company_with_admin, admin_headers, registered_user, auth_headers
):
    created_job = await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)
    job_id = created_job.json()["data"]["id"]
    access_url = f"/api/v1/jobs/{job_id}/access"

    granted = await client.post(
        access_url,
        json={"email": registered_user.email, "access_level": "viewer"},
        headers=admin_headers,
    )
    assert granted.status_code == 201
    assert granted.json()["data"]["access_level"] == "viewer"
    assert len((await client.get("/api/v1/jobs", headers=auth_headers)).json()["data"]) == 1
    overview = (await client.get("/api/v1/users/me/access", headers=auth_headers)).json()["data"]
    assert overview["company_access"] is None
    assert overview["job_accesses"][0]["access_source"] == "job_grant"
    assert overview["job_accesses"][0]["access_level"] == "viewer"
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)).status_code == 200
    denied = await client.put(
        f"/api/v1/jobs/{job_id}", json={"title": "No edit access"}, headers=auth_headers
    )
    assert denied.status_code == 403

    upgraded = await client.post(
        access_url,
        json={"email": registered_user.email, "access_level": "editor"},
        headers=admin_headers,
    )
    assert upgraded.status_code == 201
    edited = await client.put(
        f"/api/v1/jobs/{job_id}", json={"title": "Shared edit"}, headers=auth_headers
    )
    assert edited.status_code == 200
    assert (await client.get(access_url, headers=admin_headers)).json()["data"][0][
               "access_level"
           ] == "editor"

    revoked = await client.delete(f"{access_url}/{registered_user.id}", headers=admin_headers)
    assert revoked.status_code == 200
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_company_isolation_and_missing_membership(
        client: AsyncClient, admin_headers, db_session
):
    company = Company(name="Other Org")
    db_session.add(company)
    await db_session.flush()
    other_user = User(
        name="Other Admin",
        email="other-admin@example.com",
        role=UserRole.ADMIN,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(other_user)
    await db_session.commit()
    created = await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=headers_for(other_user))
    job_id = created.json()["data"]["id"]
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers)).status_code == 404
    assert (await client.get("/api/v1/jobs", headers=admin_headers)).json()["data"] == []


@pytest.mark.asyncio
async def test_status_transitions_and_preference_weight_validation(
        client, company_with_admin, admin_headers
):
    job_id = (await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)).json()[
        "data"
    ]["id"]
    paused = await client.post(f"/api/v1/jobs/{job_id}/pause", headers=admin_headers)
    assert paused.status_code == 409
    published = await client.post(f"/api/v1/jobs/{job_id}/publish", headers=admin_headers)
    assert published.status_code == 200
    paused = await client.post(f"/api/v1/jobs/{job_id}/pause", headers=admin_headers)
    assert paused.status_code == 200
    resumed = await client.post(f"/api/v1/jobs/{job_id}/publish", headers=admin_headers)
    assert resumed.status_code == 200
    closed = await client.post(f"/api/v1/jobs/{job_id}/close", headers=admin_headers)
    assert closed.status_code == 200
    archived = await client.post(f"/api/v1/jobs/{job_id}/archive", headers=admin_headers)
    assert archived.status_code == 200
    republish = await client.post(f"/api/v1/jobs/{job_id}/publish", headers=admin_headers)
    assert republish.status_code == 409


@pytest.mark.asyncio
async def test_requirement_crud_and_publish_weight_total(client, company_with_admin, admin_headers):
    job_id = (await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)).json()[
        "data"
    ]["id"]
    requirements_url = f"/api/v1/jobs/{job_id}/requirements"
    mandatory = {
        "category": "experience",
        "name": "5 years experience",
        "requirement_type": "mandatory",
        "importance": "high",
        "weight": 0,
        "is_mandatory": True,
    }
    preferred_a = {
        "category": "skills",
        "name": "Python",
        "requirement_type": "preferred",
        "importance": "high",
        "weight": 0.7,
        "is_mandatory": False,
    }
    preferred_b = {**preferred_a, "name": "PostgreSQL", "weight": 0.2}
    must = await client.post(requirements_url, json=mandatory, headers=admin_headers)
    assert must.status_code == 201
    first = await client.post(requirements_url, json=preferred_a, headers=admin_headers)
    second = await client.post(requirements_url, json=preferred_b, headers=admin_headers)
    assert first.status_code == second.status_code == 201
    assert (
               await client.post(f"/api/v1/jobs/{job_id}/publish", headers=admin_headers)
           ).status_code == 400

    second_id = second.json()["data"]["id"]
    fixed = await client.put(
        f"{requirements_url}/{second_id}", json={"weight": 0.3}, headers=admin_headers
    )
    assert fixed.status_code == 200
    assert (
               await client.post(f"/api/v1/jobs/{job_id}/publish", headers=admin_headers)
           ).status_code == 200
    items = (await client.get(requirements_url, headers=admin_headers)).json()["data"]
    assert len(items) == 3

    delete = await client.delete(
        f"{requirements_url}/{first.json()['data']['id']}", headers=admin_headers
    )
    assert delete.status_code == 400


@pytest.mark.asyncio
async def test_requirement_weights_accept_decimals_and_mandatory_can_be_toggled(
        client, company_with_admin, admin_headers
):
    job_id = (await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)).json()[
        "data"
    ]["id"]
    requirements_url = f"/api/v1/jobs/{job_id}/requirements"
    create = await client.post(
        requirements_url,
        json={
            "category": "skills",
            "name": "Python",
            "requirement_type": "preferred",
            "importance": "high",
            "weight": 0.333,
            "is_mandatory": False,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201
    requirement_id = create.json()["data"]["id"]
    assert create.json()["data"]["weight"] == pytest.approx(0.333)

    mandatory = await client.put(
        f"{requirements_url}/{requirement_id}",
        json={"is_mandatory": True},
        headers=admin_headers,
    )
    assert mandatory.status_code == 200
    assert mandatory.json()["data"]["requirement_type"] == "mandatory"
    assert mandatory.json()["data"]["is_mandatory"] is True
    assert mandatory.json()["data"]["weight"] == 0

    preferred = await client.put(
        f"{requirements_url}/{requirement_id}",
        json={"is_mandatory": False, "weight": 0.333},
        headers=admin_headers,
    )
    assert preferred.status_code == 200
    assert preferred.json()["data"]["requirement_type"] == "preferred"
    assert preferred.json()["data"]["is_mandatory"] is False
    assert preferred.json()["data"]["weight"] == pytest.approx(0.333)

    second = await client.post(
        requirements_url,
        json={
            "category": "skills",
            "name": "PostgreSQL",
            "requirement_type": "preferred",
            "importance": "medium",
            "weight": 0.667,
            "is_mandatory": False,
        },
        headers=admin_headers,
    )
    assert second.status_code == 201
    published = await client.post(f"/api/v1/jobs/{job_id}/publish", headers=admin_headers)
    assert published.status_code == 200


@pytest.mark.asyncio
async def test_requirement_validation_separates_mandatory_from_scoring(
        client, company_with_admin, admin_headers
):
    job_id = (await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)).json()[
        "data"
    ]["id"]
    invalid = {
        "category": "skills",
        "name": "Python",
        "requirement_type": "mandatory",
        "importance": "high",
        "weight": 50,
        "is_mandatory": True,
    }
    response = await client.post(
        f"/api/v1/jobs/{job_id}/requirements", json=invalid, headers=admin_headers
    )
    assert response.status_code == 422
    invalid_weight = {
        "category": "skills",
        "name": "Python",
        "requirement_type": "preferred",
        "importance": "high",
        "weight": 1.01,
        "is_mandatory": False,
    }
    response = await client.post(
        f"/api/v1/jobs/{job_id}/requirements",
        json=invalid_weight,
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extraction_returns_valid_suggestions_without_overwriting_job(
        client: AsyncClient, company_with_admin, admin_headers
):
    class MockProvider:
        async def extract_requirements(self, description):
            assert description == JOB_PAYLOAD["description"]
            return {
                "suggestions": [
                    {
                        "category": "skills",
                        "name": "Python",
                        "requirement_type": "preferred",
                        "importance": "high",
                        "weight": 1.0,
                        "is_mandatory": False,
                    },
                ]
            }

    app = client._transport.app
    app.dependency_overrides[get_requirement_extraction_provider] = lambda: MockProvider()
    job = await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)
    job_id = job.json()["data"]["id"]
    response = await client.post(
        f"/api/v1/jobs/{job_id}/extract-requirements", json={}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["data"]["suggestions"][0]["name"] == "Python"
    stored = (
        await client.get(f"/api/v1/jobs/{job_id}/requirements", headers=admin_headers)
    ).json()["data"]
    assert stored == []
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers)).json()["data"][
               "status"
           ] == "draft"


@pytest.mark.asyncio
async def test_extraction_rejects_invalid_provider_output(
        client, company_with_admin, admin_headers
):
    class MockProvider:
        async def extract_requirements(self, description):
            return {"suggestions": [{"category": "bogus", "name": "Invalid"}]}

    app = client._transport.app
    app.dependency_overrides[get_requirement_extraction_provider] = lambda: MockProvider()
    job_id = (await client.post("/api/v1/jobs", json=JOB_PAYLOAD, headers=admin_headers)).json()[
        "data"
    ]["id"]
    response = await client.post(
        f"/api/v1/jobs/{job_id}/extract-requirements", json={}, headers=admin_headers
    )
    assert response.status_code == 502
