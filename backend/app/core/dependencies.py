import uuid
from typing import Callable, Optional
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import decode_token
from app.models.user import User, UserRole

# HTTP Bearer scheme for Swagger UI and header parsing
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and validate the JWT Bearer access token from the Authorization header.
    Returns the authenticated User model.
    """
    if not credentials or not credentials.credentials:
        raise UnauthorizedException("Authentication credentials were not provided")

    token = credentials.credentials
    payload = decode_token(token)

    # Validate token type
    token_type = payload.get("type")
    if token_type != "access":
        raise UnauthorizedException("Invalid token type. Access token expected")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException("Token payload missing subject identifier")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedException("Invalid user identifier in token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise UnauthorizedException("User not found or account has been removed")

    request.state.user_id = str(user.id)
    request.state.company_id = str(user.company_id) if user.company_id else None

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure the authenticated user account is active.
    """
    if not current_user.is_active:
        raise ForbiddenException("User account is deactivated")
    return current_user


def require_role(*allowed_roles: UserRole) -> Callable:
    """
    Role-based access control dependency factory.
    Enforces that current active user holds one of the specified roles.
    """

    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenException("Insufficient permissions for this operation")
        return current_user

    return role_checker


async def require_company_membership(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Ensure the authenticated user belongs to a company.
    """
    if not current_user.company_id:
        raise NotFoundException("User does not belong to any company")
    return current_user


async def require_company_admin(
    current_user: User = Depends(require_company_membership),
) -> User:
    """
    Ensure the authenticated user is an administrator of their company.
    """
    if current_user.role != UserRole.ADMIN:
        raise ForbiddenException("Only company administrators can perform this action")
    return current_user
