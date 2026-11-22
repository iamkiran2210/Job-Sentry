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
