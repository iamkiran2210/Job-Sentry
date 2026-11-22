import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_google_id_token,
    verify_password,
)
from app.models.token import RefreshToken
from app.models.user import AuthProvider, User, UserRole
from app.schemas.auth import (
    GoogleOAuthRequest,
    TokenRefreshResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserGoogleRegisterRequest,
)
from app.schemas.user import UserResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AuthService:
    """Service handling user registration, authentication, token rotation, and Google OAuth."""

    @staticmethod
    async def register_user(db: AsyncSession, request: UserRegisterRequest):
        email_normalized = request.email.lower().strip()

        # Check for duplicate email
        result = await db.execute(select(User).where(User.email == email_normalized))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise ConflictException(f"User with email '{email_normalized}' already exists")

        # Hash password with Argon2
        password_hashed = hash_password(request.password)

        new_user = User(
            name=request.name.strip(),
            email=email_normalized,
            password_hash=password_hashed,
            role=UserRole.RECRUITER,
            auth_provider=AuthProvider.EMAIL,
            is_active=True,
            is_verified=False,
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def register_user_google(db: AsyncSession, request: UserGoogleRegisterRequest):
        email_normalized = request.email.lower().strip()

        # Check for duplicate email
        result = await db.execute(select(User).where(User.email == email_normalized))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise ConflictException(f"User with email '{email_normalized}' already exists")

        new_user = User(
            name=request.name.strip(),
            email=email_normalized,
            password_hash=None,
            role=UserRole.RECRUITER,
            auth_provider=AuthProvider.GOOGLE,
            is_active=True,
            is_verified=True,
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def register_user_by_admin(
        db: AsyncSession, request: UserRegisterRequest, *, company_id: uuid.UUID
    ) -> User:
        """Register a new user with email and password."""
        email_normalized = request.email.lower().strip()

        # Check for duplicate email
        result = await db.execute(select(User).where(User.email == email_normalized))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise ConflictException(f"User with email '{email_normalized}' already exists")

        # Hash password with Argon2
        password_hashed = hash_password(request.password)

        new_user = User(
            name=request.name.strip(),
            email=email_normalized,
            password_hash=password_hashed,
            role=UserRole.RECRUITER,
            auth_provider=AuthProvider.EMAIL,
            company_id=company_id,
            is_active=True,
            is_verified=False,
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def login_user(db: AsyncSession, request: UserLoginRequest) -> Tuple[TokenResponse, User]:
        """Authenticate user by email and password, issuing access and refresh tokens."""
        email_normalized = request.email.lower().strip()

        result = await db.execute(select(User).where(User.email == email_normalized))
        user = result.scalar_one_or_none()

        if not user:
            verify_password(request.password, DUMMY_PASSWORD_HASH)
            raise UnauthorizedException("Invalid email or password")

        if not user.password_hash:
            verify_password(request.password, DUMMY_PASSWORD_HASH)
            raise UnauthorizedException("Invalid email or password")

        if not verify_password(request.password, user.password_hash):
            raise UnauthorizedException("Invalid email or password")

        if not user.is_active:
            raise UnauthorizedException("Invalid email or password")

        # Issue tokens
        access_token = create_access_token(
            subject=str(user.id),
            role=user.role.value,
            company_id=str(user.company_id) if user.company_id else None,
        )
        raw_refresh_token, expire_at = create_refresh_token(subject=str(user.id))

        # Store hashed refresh token record in DB
        refresh_token_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh_token),
            expires_at=expire_at,
        )
        db.add(refresh_token_record)
        await db.commit()

        token_response = TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )
        return token_response, user

    @staticmethod
    async def sign_in_with_google(
            db: AsyncSession,
            request: GoogleOAuthRequest,
    ) -> Tuple[TokenResponse, User]:
        # 1. Verify Google ID token off the event loop (may fetch Google JWKS certs)
        id_info = await asyncio.to_thread(verify_google_id_token, request.id_token)

        email = id_info.get("email")
        email_verified = id_info.get("email_verified", False)

        if not email:
            raise UnauthorizedException("Google token does not contain an email address")

        if not email_verified:
            raise UnauthorizedException("Google email address is not verified")

        email = email.lower().strip()

        # 2. Check whether user already exists
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        # 3. Register if user does not exist (defensively normalize short/missing Google names)
        if not user:
            fallback_name = email.split("@")[0].strip()
            raw_name = (
                    (id_info.get("name") or "").strip()
                    or (id_info.get("given_name") or "").strip()
                    or fallback_name
            )
            if len(raw_name) < 2:
                raw_name = fallback_name if len(fallback_name) >= 2 else "Google User"
            register_request = UserGoogleRegisterRequest(
                email=email,
                name=raw_name[:255],
            )

            user = await AuthService.register_user_google(
                db,
                register_request,
            )

        # 4. Reject inactive accounts
        if not user.is_active:
            raise UnauthorizedException("Account is inactive")

        if not user.is_verified:
            user.is_verified = True

        # 5. Issue access token
        access_token = create_access_token(
            subject=str(user.id),
            role=user.role.value,
            company_id=(str(user.company_id) if user.company_id else None),
        )

        # 6. Issue refresh token
        raw_refresh_token, expire_at = create_refresh_token(subject=str(user.id))

        refresh_token_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh_token),
            expires_at=expire_at,
        )

        db.add(refresh_token_record)
        await db.commit()
        await db.refresh(user)

        # 7. Return tokens
        token_response = TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )

        return token_response, user

    @staticmethod
    async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenRefreshResponse:
        """Validate refresh token, enforce single-use rotation, and issue new tokens."""
        if not refresh_token:
            raise UnauthorizedException("Refresh token is required")

        payload = decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise UnauthorizedException("Invalid token type. Refresh token expected")

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise UnauthorizedException("Invalid refresh token payload")

        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError:
            raise UnauthorizedException("Invalid user identifier in refresh token")

        # Look up persistent token record using cryptographic hash
        token_hash = hash_token(refresh_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise UnauthorizedException("Refresh token not found or already invalidated")

        # Check if token was already revoked
        if token_record.revoked_at is not None:
            # Token reuse detected: security risk, reject request
            raise UnauthorizedException("Refresh token has been revoked")

        # Check expiry
        now = datetime.now(timezone.utc)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at <= now:
            token_record.revoked_at = now
            await db.commit()
            raise UnauthorizedException("Refresh token has expired")

        # Fetch user
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.is_active:
            raise ForbiddenException("User account is inactive or no longer exists")

        # Rotate tokens: revoke current token
        token_record.revoked_at = now

        # Generate new access and refresh tokens
        new_access_token = create_access_token(
            subject=str(user.id),
            role=user.role.value,
            company_id=str(user.company_id) if user.company_id else None,
        )
        new_raw_refresh, new_expire = create_refresh_token(subject=str(user.id))

        # Store new hashed refresh token
        new_token_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(new_raw_refresh),
            expires_at=new_expire,
        )
        db.add(new_token_record)
        await db.commit()

        return TokenRefreshResponse(
            access_token=new_access_token,
            refresh_token=new_raw_refresh,
            token_type="bearer",
        )

    @staticmethod
    async def logout_user(
        db: AsyncSession, refresh_token: Optional[str] = None, *, user_id: uuid.UUID
    ) -> None:
        """Revoke the given refresh token to invalidate the session."""
        if refresh_token:
            token_hash = hash_token(refresh_token)
            result = await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.user_id == user_id,
                )
            )
            token_record = result.scalar_one_or_none()
            if token_record and token_record.revoked_at is None:
                token_record.revoked_at = datetime.now(timezone.utc)
                await db.commit()

    @staticmethod
    async def authenticate_google(
        db: AsyncSession,
        request: GoogleOAuthRequest,
        *,
        expected_user_id: uuid.UUID,
        expected_email: str,
    ) -> Tuple[TokenResponse, User]:
        """Issue fresh tokens after verifying the authenticated user's Google email."""
        id_info = await asyncio.to_thread(verify_google_id_token, request.id_token)
        email = id_info.get("email")
        if not email:
            raise UnauthorizedException("Google token does not contain an email address")

        email_verified = id_info.get("email_verified", False)
        if not email_verified:
            raise UnauthorizedException("Google email address is not verified")

        email_normalized = email.lower().strip()
        if email_normalized != expected_email.lower().strip():
            raise ForbiddenException("Google account does not match the authenticated account")
        result = await db.execute(select(User).where(User.id == expected_user_id))
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise ForbiddenException("Authenticated account is unavailable")
        # This authenticated operation links a verified Google identity; it cannot create
        # an account or issue a session for a different account.
        if not user.is_verified:
            user.is_verified = True
        # Issue tokens
        access_token = create_access_token(
            subject=str(user.id),
            role=user.role.value,
            company_id=str(user.company_id) if user.company_id else None,
        )
        raw_refresh_token, expire_at = create_refresh_token(subject=str(user.id))

        refresh_token_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh_token),
            expires_at=expire_at,
        )
        db.add(refresh_token_record)
        await db.commit()
        await db.refresh(user)

        token_response = TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )
        return token_response, user
