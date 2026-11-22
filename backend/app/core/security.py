import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from app.core.config import settings
from app.core.exceptions import UnauthorizedException
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Argon2 password hasher instance
pwd_hasher = PasswordHasher()
logger = logging.getLogger(__name__)
DUMMY_PASSWORD_HASH = pwd_hasher.hash("job-sentry-invalid-login-timing-padding")


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2."""
    return pwd_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    if not hashed_password:
        return False
    try:
        return pwd_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    """Hash a token using SHA-256 for secure persistent storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    subject: str,
    role: str,
    company_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Generate a signed JWT access token.
    Contains subject, role, company_id, token type, and expiration.
    """
    now = datetime.now(timezone.utc)
    requested_expiry = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + min(requested_expiry, timedelta(minutes=15))

    payload = {
        "sub": str(subject),
        "role": role,
        "company_id": str(company_id) if company_id else None,
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> tuple[str, datetime]:
    """
    Generate a signed JWT refresh token.
    Returns (token_str, expiry_datetime_utc).
    """
    now = datetime.now(timezone.utc)
    requested_expiry = expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    expire = now + min(requested_expiry, timedelta(days=7))

    payload = {
        "sub": str(subject),
        "type": "refresh",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, expire


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token's signature and expiration.
    Raises UnauthorizedException on failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type", "iss", "aud"]},
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Token has expired")
    except jwt.InvalidTokenError as e:
        raise UnauthorizedException(f"Invalid token: {str(e)}")


def verify_google_id_token(token: str) -> Dict[str, Any]:
    """
    Verify Google ID token using Google's official library.
    Validates audience, issuer, and expiration with clock-skew tolerance.
    """
    if not token or not token.strip():
        raise UnauthorizedException("Google ID token is required")
    try:
        request = google_requests.Request()
        audience = settings.GOOGLE_CLIENT_ID.strip() if settings.GOOGLE_CLIENT_ID else None
        id_info = id_token.verify_oauth2_token(
            token.strip(),
            request,
            audience=audience,
            clock_skew_in_seconds=60,
        )
        issuer = id_info.get("iss")
        if issuer not in ["accounts.google.com", "https://accounts.google.com"]:
            raise UnauthorizedException("Invalid Google token issuer")

        return id_info
    except UnauthorizedException:
        raise
    except (ValueError, GoogleAuthError) as exc:
        logger.warning(
            "Google ID token rejected: %s (%s)",
            type(exc).__name__,
            str(exc)[:200],
        )
        raise UnauthorizedException("Could not validate Google credentials") from exc
    except Exception as exc:
        logger.warning(
            "Google ID token verification failed: %s (%s)",
            type(exc).__name__,
            str(exc)[:200],
        )
        raise UnauthorizedException("Could not validate Google credentials") from exc
