from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.modules.auth.service import AuthService
from app.schemas.auth import (
    GoogleOAuthRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenRefreshResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.user import UserResponse
from app.utils.responses import success_response

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Registers a new user with name, email, and strong password.",
)
async def register(
    request: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await AuthService.register_user(db, request)
    return success_response(
        data=UserResponse.model_validate(user).model_dump(mode="json"),
        message="User registered successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    summary="User login",
    description="Authenticates user credentials and returns JWT access and refresh tokens.",
)
async def login(
    request: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    token_response, _ = await AuthService.login_user(db, request)
    return success_response(
        data=token_response.model_dump(mode="json"),
        message="Login successful",
        status_code=status.HTTP_200_OK,
    )


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Rotates refresh token and issues a new access token.",
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    token_data = await AuthService.refresh_tokens(db, request.refresh_token)
    return success_response(
        data=token_data.model_dump(mode="json"),
        message="Tokens refreshed successfully",
        status_code=status.HTTP_200_OK,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout user",
    description="Revokes the persistent refresh token, terminating the active session.",
)
async def logout(
    request: LogoutRequest,
    db: AsyncSession = Depends(get_db),
):
    await AuthService.logout_user(db, request.refresh_token)
    return success_response(
        data=None,
        message="Logged out successfully",
        status_code=status.HTTP_200_OK,
    )


@router.post(
    "/google",
    status_code=status.HTTP_200_OK,
    summary="Google OAuth login / registration",
    description="Authenticates with a verified Google ID token from frontend.",
)
async def google_auth(
    request: GoogleOAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    token_response, _ = await AuthService.authenticate_google(db, request)
    return success_response(
        data=token_response.model_dump(mode="json"),
        message="Google authentication successful",
        status_code=status.HTTP_200_OK,
    )


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user",
    description="Returns profile information for the authenticated user.",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
):
    return success_response(
        data=UserResponse.model_validate(current_user).model_dump(mode="json"),
        message="User profile retrieved successfully",
        status_code=status.HTTP_200_OK,
    )
