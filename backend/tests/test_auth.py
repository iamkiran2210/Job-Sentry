from datetime import timedelta
from unittest.mock import patch

import pytest
from app.core.security import create_access_token, hash_password
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient, admin_headers):
    """Test successful user registration with valid data."""
    payload = {
        "name": "Rahul Sharma",
        "email": "rahul@example.com",
        "password": "StrongPassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload, headers=admin_headers)
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
async def test_registration_requires_company_admin(client: AsyncClient, auth_headers):
    payload = {
        "name": "Recruiter Created",
        "email": "new-recruiter@example.com",
        "password": "StrongPassword123!",
    }
    anonymous = await client.post("/api/v1/auth/register", json=payload)
    recruiter = await client.post("/api/v1/auth/register", json=payload, headers=auth_headers)
    assert anonymous.status_code == 401
    assert recruiter.status_code in {403, 404}


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, registered_user, admin_headers):
    """Test registration failure when email already exists."""
    payload = {
        "name": "Another Person",
        "email": registered_user.email,
        "password": "ValidPassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload, headers=admin_headers)
    assert response.status_code == 409
    data = response.json()
    assert data["success"] is False
    assert "already exists" in data["message"].lower()


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient, admin_headers):
    """Test registration failure on malformed email address."""
    payload = {
        "name": "Invalid Email",
        "email": "not-an-email",
        "password": "StrongPassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload, headers=admin_headers)
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
async def test_register_weak_password(
    client: AsyncClient, weak_password: str, reason: str, admin_headers
):
    """Test registration failure on passwords not meeting strength requirements."""
    payload = {
        "name": "Weak Pass User",
        "email": f"user_{reason.replace(' ', '_')}@example.com",
        "password": weak_password,
    }
    response = await client.post("/api/v1/auth/register", json=payload, headers=admin_headers)
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
async def test_login_failure_is_generic_for_unknown_and_provider_accounts(
    client: AsyncClient, db_session, caplog
):
    from app.models.user import AuthProvider, User, UserRole

    db_session.add(
        User(
            name="OAuth Account",
            email="oauth-only@example.com",
            password_hash=None,
            role=UserRole.RECRUITER,
            auth_provider=AuthProvider.GOOGLE,
            is_active=True,
            is_verified=True,
        )
    )
    await db_session.commit()
    caplog.set_level("INFO")
    first = await client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "MustNotBeLogged123!"},
    )
    second = await client.post(
        "/api/v1/auth/login",
        json={"email": "oauth-only@example.com", "password": "MustNotBeLogged123!"},
    )
    assert first.status_code == second.status_code == 401
    assert first.json()["message"] == second.json()["message"]
    assert "MustNotBeLogged123!" not in caplog.text


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
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "invalid.jwt.token"}
    )
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
        headers={"Authorization": f"Bearer {login_res.json()['data']['access_token']}"},
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
async def test_logout_requires_authentication(client: AsyncClient):
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": "x"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_cannot_revoke_another_users_refresh_token(
    client: AsyncClient, db_session, auth_headers
):
    from app.models.user import AuthProvider, User, UserRole

    other = User(
        name="Other Recruiter",
        email="other-recruiter@example.com",
        password_hash=hash_password("ValidPass123!"),
        role=UserRole.RECRUITER,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(other)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": other.email, "password": "ValidPass123!"},
    )
    other_refresh = login.json()["data"]["refresh_token"]
    await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": other_refresh},
        headers=auth_headers,
    )
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": other_refresh})
    assert refresh.status_code == 200


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    """Test protected endpoints reject requests lacking authentication."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_google_oauth_flow(client: AsyncClient, registered_user, auth_headers):
    """Test authenticated Google identity linking with mocked verification."""
    mock_google_payload = {
        "email": registered_user.email,
        "name": "Google User",
        "email_verified": True,
        "iss": "accounts.google.com",
        "sub": "google-user-12345",
    }

    with patch(
        "app.modules.auth.service.verify_google_id_token",
        return_value=mock_google_payload,
    ):
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "valid-mock-google-token"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["user"]["email"] == registered_user.email
        assert "access_token" in data["data"]
        assert "refresh_token" in data["data"]


@pytest.mark.asyncio
async def test_google_oauth_unverified_email(client: AsyncClient, registered_user, auth_headers):
    """Test Google OAuth rejects unverified email addresses."""
    mock_google_payload = {
        "email": registered_user.email,
        "name": "Unverified User",
        "email_verified": False,
        "iss": "accounts.google.com",
    }

    with patch(
        "app.modules.auth.service.verify_google_id_token",
        return_value=mock_google_payload,
    ):
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "unverified-google-token"},
            headers=auth_headers,
        )
        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert "not verified" in data["message"].lower()


@pytest.mark.asyncio
async def test_google_link_cannot_issue_tokens_for_another_account(
    client: AsyncClient, registered_user, auth_headers
):
    with patch(
        "app.modules.auth.service.verify_google_id_token",
        return_value={
            "email": "someone-else@example.com",
            "name": "Other Account",
            "email_verified": True,
        },
    ):
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "valid-mock-google-token"},
            headers=auth_headers,
        )
    assert response.status_code == 403
    assert "someone-else@example.com" not in response.text


@pytest.mark.asyncio
async def test_google_sign_in_registers_new_user_and_handles_short_name(client: AsyncClient):
    """POST /auth/sign/google creates a verified Google user even when display name is missing/1-char."""
    mock_google_payload = {
        "email": "fresh.google@example.com",
        "name": "K",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "sub": "google-sub-999",
    }
    with patch(
            "app.modules.auth.service.verify_google_id_token",
            return_value=mock_google_payload,
    ):
        response = await client.post(
            "/api/v1/auth/sign/google",
            json={"id_token": "valid-google-id-token"},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["email"] == "fresh.google@example.com"
    assert data["user"]["name"] == "fresh.google"
    assert data["user"]["auth_provider"] == "google"
    assert data["user"]["is_verified"] is True
    assert data["access_token"]
    assert data["refresh_token"]

    # Signing in a second time returns fresh tokens for the existing account
    with patch(
            "app.modules.auth.service.verify_google_id_token",
            return_value=mock_google_payload,
    ):
        second = await client.post(
            "/api/v1/auth/sign/google",
            json={"id_token": "valid-google-id-token"},
        )
    assert second.status_code == 200
    assert second.json()["data"]["user"]["id"] == data["user"]["id"]


def test_verify_google_id_token_passes_clock_skew():
    """verify_google_id_token passes clock_skew_in_seconds to tolerate host/Docker clock drift."""
    from app.core.security import verify_google_id_token

    with patch("app.core.security.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.return_value = {
            "email": "skew@example.com",
            "email_verified": True,
            "iss": "https://accounts.google.com",
        }
        info = verify_google_id_token("fake-jwt-token")
    assert info["email"] == "skew@example.com"
    _, kwargs = mock_verify.call_args
    assert kwargs["clock_skew_in_seconds"] == 60
