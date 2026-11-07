import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.security import (
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
)
from app.schemas.user import UserResponse


class AuthService:
    """Service handling user registration, authentication, token rotation, and Google OAuth."""

    @staticmethod
    async def register_user(db: AsyncSession, request: UserRegisterRequest) -> User:
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
            raise UnauthorizedException("Invalid email or password")

        if not user.password_hash:
            raise UnauthorizedException(
                f"This account was registered using {user.auth_provider.value}. Please log in using that provider."
            )

        if not verify_password(request.password, user.password_hash):
            raise UnauthorizedException("Invalid email or password")

        if not user.is_active:
            raise ForbiddenException("User account is deactivated")

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
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
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
    async def logout_user(db: AsyncSession, refresh_token: Optional[str] = None) -> None:
        """Revoke the given refresh token to invalidate the session."""
        if refresh_token:
            token_hash = hash_token(refresh_token)
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash)
            )
            token_record = result.scalar_one_or_none()
            if token_record and token_record.revoked_at is None:
                token_record.revoked_at = datetime.now(timezone.utc)
                await db.commit()

    @staticmethod
    async def authenticate_google(db: AsyncSession, request: GoogleOAuthRequest) -> Tuple[TokenResponse, User]:
        """Authenticate or register user via verified Google ID token."""
        id_info = verify_google_id_token(request.id_token)

        email = id_info.get("email")
        if not email:
            raise UnauthorizedException("Google token does not contain an email address")

        email_verified = id_info.get("email_verified", False)
        if not email_verified:
            raise UnauthorizedException("Google email address is not verified")

        email_normalized = email.lower().strip()
        name = id_info.get("name", email_normalized.split("@")[0]).strip()

        result = await db.execute(select(User).where(User.email == email_normalized))
        user = result.scalar_one_or_none()

        if user:
            if not user.is_active:
                raise ForbiddenException("User account is deactivated")
            # Account linking: mark verified if Google has verified the email
            if not user.is_verified:
                user.is_verified = True
        else:
            # Create new user via Google OAuth
            user = User(
                name=name,
                email=email_normalized,
                password_hash=None,
                role=UserRole.RECRUITER,
                auth_provider=AuthProvider.GOOGLE,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            await db.flush()

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
