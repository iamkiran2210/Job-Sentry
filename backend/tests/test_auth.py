from datetime import timedelta
from unittest.mock import patch
import pytest
from httpx import AsyncClient

from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Test successful user registration with valid data."""
    payload = {
        "name": "Rahul Sharma",
        "email": "rahul@example.com",
        "password": "StrongPassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["success"] is True
    assert data["message"] == "User registered successfully"
    assert data["data"]["email"] == "rahul@example.com"
    assert data["data"]["name"] == "Rahul Sharma"
    assert data["data"]["role"] == "recruiter"
    assert data["data"]["auth_provider"] == "email"
    # Ensure sensitive credentials are never returned
    assert "password" not in data["data"]
    assert "password_hash" not in data["data"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, registered_user):
    """Test registration failure when email already exists."""
    payload = {
        "name": "Another Person",
        "email": registered_user.email,
        "password": "ValidPassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["success"] is False
    assert "already exists" in data["message"].lower()


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    """Test registration failure on malformed email address."""
    payload = {
        "name": "Invalid Email",
        "email": "not-an-email",
        "password": "StrongPassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "weak_password,reason",
    [
        ("short1!", "too short"),
        ("lowercaseonly123!", "missing uppercase"),
        ("UPPERCASEONLY123!", "missing lowercase"),
        ("NoNumberHere!", "missing digit"),
        ("NoSpecialChar123", "missing special char"),
    ],
)
async def test_register_weak_password(client: AsyncClient, weak_password: str, reason: str):
    """Test registration failure on passwords not meeting strength requirements."""
    payload = {
        "name": "Weak Pass User",
        "email": f"user_{reason.replace(' ', '_')}@example.com",
        "password": weak_password,
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, registered_user):
    """Test successful login returns access and refresh tokens."""
    payload = {
        "email": registered_user.email,
        "password": "ValidPass123!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    assert "refresh_token" in data["data"]
    assert data["data"]["token_type"] == "bearer"
    assert data["data"]["user"]["email"] == registered_user.email
    assert "password_hash" not in data["data"]["user"]


@pytest.mark.asyncio
async def test_login_incorrect_password(client: AsyncClient, registered_user):
    """Test login failure with wrong password."""
    payload = {
        "email": registered_user.email,
        "password": "WrongPassword999!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert "invalid email or password" in data["message"].lower()


@pytest.mark.asyncio
async def test_expired_access_token(client: AsyncClient, registered_user):
    """Test rejection when access token has expired."""
    expired_token = create_access_token(
        subject=str(registered_user.id),
        role=registered_user.role.value,
        expires_delta=timedelta(seconds=-10),
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert "expired" in data["message"].lower()


@pytest.mark.asyncio
async def test_invalid_refresh_token(client: AsyncClient):
    """Test refresh endpoint with completely invalid token."""
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid.jwt.token"})
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_refresh_token_rotation(client: AsyncClient, registered_user):
    """Test refresh token rotation: old token is revoked, new token works."""
    # 1. Login to obtain tokens
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "ValidPass123!"},
    )
    assert login_res.status_code == 200
    initial_refresh = login_res.json()["data"]["refresh_token"]

    # 2. Use refresh token to obtain rotated pair
    refresh_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert refresh_res.status_code == 200
    rotated_data = refresh_res.json()["data"]
    new_refresh = rotated_data["refresh_token"]
    assert new_refresh != initial_refresh

    # 3. Old refresh token must now be rejected (revoked / reuse detection)
    reuse_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert reuse_res.status_code == 401
    assert "revoked" in reuse_res.json()["message"].lower()

    # 4. New refresh token can be used again
    second_refresh_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_refresh},
    )
    assert second_refresh_res.status_code == 200


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, registered_user):
    """Test logout revokes the persistent refresh token."""
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "ValidPass123!"},
    )
    refresh_token = login_res.json()["data"]["refresh_token"]

    # Logout
    logout_res = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True

    # Attempting to refresh with the revoked token must fail
    refresh_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res.status_code == 401


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    """Test protected endpoints reject requests lacking authentication."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_google_oauth_flow(client: AsyncClient):
    """Test Google OAuth login and user creation with mocked Google verification."""
    mock_google_payload = {
        "email": "googleuser@example.com",
        "name": "Google User",
        "email_verified": True,
        "iss": "accounts.google.com",
        "sub": "google-user-12345",
    }

    with patch("app.modules.auth.service.verify_google_id_token", return_value=mock_google_payload):
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "valid-mock-google-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["user"]["email"] == "googleuser@example.com"
        assert data["data"]["user"]["auth_provider"] == "google"
        assert "access_token" in data["data"]
        assert "refresh_token" in data["data"]


@pytest.mark.asyncio
async def test_google_oauth_unverified_email(client: AsyncClient):
    """Test Google OAuth rejects unverified email addresses."""
    mock_google_payload = {
        "email": "unverified@example.com",
        "name": "Unverified User",
        "email_verified": False,
        "iss": "accounts.google.com",
    }

    with patch("app.modules.auth.service.verify_google_id_token", return_value=mock_google_payload):
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "unverified-google-token"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert "not verified" in data["message"].lower()
