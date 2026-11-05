import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.company import Company
from app.models.user import AuthProvider, User, UserRole


@pytest.mark.asyncio
async def test_create_company_success(
    client: AsyncClient,
    registered_user: User,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Test successful company creation promotes creator to admin and associates company."""
    payload = {
        "name": "Tech Corp International",
        "industry": "Software",
        "website": "https://techcorp.example.com",
        "description": "Enterprise SaaS Solutions",
        "location": "Bengaluru, India",
    }
    response = await client.post("/api/v1/companies", json=payload, headers=auth_headers)
    assert response.status_code == 201

    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Tech Corp International"
    assert data["data"]["industry"] == "Software"
    assert data["data"]["location"] == "Bengaluru, India"

    # Verify user state in DB: must be promoted to ADMIN and associated with new company
    await db_session.refresh(registered_user)
    assert registered_user.role == UserRole.ADMIN
    assert registered_user.company_id is not None
    assert str(registered_user.company_id) == data["data"]["id"]


@pytest.mark.asyncio
async def test_duplicate_company_creation(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    admin_headers: dict,
):
    """Test user who already belongs to a company cannot create another company."""
    payload = {
        "name": "Second Company Ltd",
    }
    response = await client.post("/api/v1/companies", json=payload, headers=admin_headers)
    assert response.status_code == 409
    data = response.json()
    assert data["success"] is False
    assert "already associated" in data["message"].lower()


@pytest.mark.asyncio
async def test_get_company_without_membership(client: AsyncClient, auth_headers: dict):
    """Test get company fails with 404 if user has not created or joined a company."""
    response = await client.get("/api/v1/companies/me", headers=auth_headers)
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "does not belong" in data["message"].lower()


@pytest.mark.asyncio
async def test_get_company_success(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    admin_headers: dict,
):
    """Test retrieving authenticated user's company information."""
    company, _ = company_with_admin
    response = await client.get("/api/v1/companies/me", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == str(company.id)
    assert data["data"]["name"] == company.name
    assert data["data"]["industry"] == company.industry


@pytest.mark.asyncio
async def test_recruiter_can_view_company(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    db_session: AsyncSession,
):
    """Test recruiter belonging to a company can view company details."""
    company, _ = company_with_admin

    # Add recruiter to this company
    recruiter = User(
        name="Charlie Recruiter",
        email="charlie@acme.example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.RECRUITER,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(recruiter)
    await db_session.commit()
    await db_session.refresh(recruiter)

    token = create_access_token(
        subject=str(recruiter.id),
        role=recruiter.role.value,
        company_id=str(company.id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/companies/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(company.id)


@pytest.mark.asyncio
async def test_update_company_by_admin(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    admin_headers: dict,
):
    """Test company administrator can successfully update company details."""
    company, _ = company_with_admin
    payload = {
        "name": "Acme Global Technologies",
        "description": "Updated enterprise recruitment platform",
        "location": "New York, NY",
    }
    response = await client.put("/api/v1/companies/me", json=payload, headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Acme Global Technologies"
    assert data["data"]["description"] == "Updated enterprise recruitment platform"
    assert data["data"]["location"] == "New York, NY"
    # Industry was not changed
    assert data["data"]["industry"] == company.industry


@pytest.mark.asyncio
async def test_update_company_by_recruiter_forbidden(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    db_session: AsyncSession,
):
    """Test recruiter cannot update company details (403 Forbidden)."""
    company, _ = company_with_admin
    recruiter = User(
        name="Dave Recruiter",
        email="dave@acme.example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.RECRUITER,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(recruiter)
    await db_session.commit()

    token = create_access_token(
        subject=str(recruiter.id),
        role=recruiter.role.value,
        company_id=str(company.id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.put(
        "/api/v1/companies/me",
        json={"name": "Hacked Name"},
        headers=headers,
    )
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "only company administrators" in data["message"].lower()


@pytest.mark.asyncio
async def test_list_members_by_admin(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    admin_headers: dict,
    db_session: AsyncSession,
):
    """Test administrator can view full list of company members."""
    company, admin = company_with_admin

    # Add members to company
    member = User(
        name="Team Member 1",
        email="team1@acme.example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.RECRUITER,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(member)
    await db_session.commit()

    response = await client.get("/api/v1/companies/me/members", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    members = data["data"]
    assert len(members) == 2  # Admin + member
    emails = [m["email"] for m in members]
    assert admin.email in emails
    assert member.email in emails

    # Verify no sensitive password hashes are exposed in member listing
    for m in members:
        assert "password" not in m
        assert "password_hash" not in m


@pytest.mark.asyncio
async def test_list_members_by_recruiter_forbidden(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    db_session: AsyncSession,
):
    """Test recruiters are forbidden from viewing company member listings."""
    company, _ = company_with_admin
    recruiter = User(
        name="Elena Recruiter",
        email="elena@acme.example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.RECRUITER,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(recruiter)
    await db_session.commit()

    token = create_access_token(
        subject=str(recruiter.id),
        role=recruiter.role.value,
        company_id=str(company.id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/companies/me/members", headers=headers)
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "only company administrators" in data["message"].lower()


@pytest.mark.asyncio
async def test_cross_company_access_prevention(
    client: AsyncClient,
    company_with_admin: tuple[Company, User],
    db_session: AsyncSession,
):
    """Test strict company data isolation: users cannot see or modify other companies."""
    company_a, admin_a = company_with_admin

    # Create Company B with Admin B and Member B
    company_b = Company(
        name="Beta Industries",
        industry="Finance",
        website="https://beta.example.com",
        description="Banking & Finance",
        location="London, UK",
    )
    db_session.add(company_b)
    await db_session.flush()

    admin_b = User(
        name="Admin Beta",
        email="admin@beta.example.com",
        password_hash=hash_password("BetaPass123!"),
        role=UserRole.ADMIN,
        company_id=company_b.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    member_b = User(
        name="Member Beta",
        email="member@beta.example.com",
        password_hash=hash_password("BetaPass123!"),
        role=UserRole.RECRUITER,
        company_id=company_b.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([admin_b, member_b])
    await db_session.commit()

    # Generate token for Admin A
    token_a = create_access_token(
        subject=str(admin_a.id),
        role=admin_a.role.value,
        company_id=str(company_a.id),
    )
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Generate token for Admin B
    token_b = create_access_token(
        subject=str(admin_b.id),
        role=admin_b.role.value,
        company_id=str(company_b.id),
    )
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Admin A accesses their company: must see Acme Corp, NEVER Beta Industries
    res_a = await client.get("/api/v1/companies/me", headers=headers_a)
    assert res_a.status_code == 200
    assert res_a.json()["data"]["name"] == "Acme Corp"
    assert res_a.json()["data"]["name"] != "Beta Industries"

    # 2. Admin B accesses their company: must see Beta Industries, NEVER Acme Corp
    res_b = await client.get("/api/v1/companies/me", headers=headers_b)
    assert res_b.status_code == 200
    assert res_b.json()["data"]["name"] == "Beta Industries"
    assert res_b.json()["data"]["name"] != "Acme Corp"

    # 3. Admin A views members: must ONLY see members of Company A, never Beta members
    members_res_a = await client.get("/api/v1/companies/me/members", headers=headers_a)
    assert members_res_a.status_code == 200
    emails_a = [m["email"] for m in members_res_a.json()["data"]]
    assert admin_a.email in emails_a
    assert admin_b.email not in emails_a
    assert member_b.email not in emails_a

    # 4. Admin B views members: must ONLY see members of Company B, never Acme members
    members_res_b = await client.get("/api/v1/companies/me/members", headers=headers_b)
    assert members_res_b.status_code == 200
    emails_b = [m["email"] for m in members_res_b.json()["data"]]
    assert admin_b.email in emails_b
    assert member_b.email in emails_b
    assert admin_a.email not in emails_b
