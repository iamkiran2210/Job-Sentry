from app.core.database import get_db
from app.core.dependencies import get_current_active_user, require_role
from app.models.user import User, UserRole
from app.modules.users.service import UsersService
from app.schemas.user import UserAccessOverview, UserResponse
from app.utils.responses import success_response
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description="Returns profile of the currently authenticated user.",
)
async def get_current_user_profile(
    current_user: User = Depends(get_current_active_user),
):
    return success_response(
        data=UserResponse.model_validate(current_user).model_dump(mode="json"),
        message="Current user fetched successfully",
        status_code=status.HTTP_200_OK,
    )


@router.get(
    "/me/access",
    status_code=status.HTTP_200_OK,
    summary="List my access",
    description="Returns the current user's company membership and all accessible jobs with their access source and level.",
)
async def get_my_access(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    overview = await UsersService.get_access_overview(db, current_user)
    return success_response(
        data=UserAccessOverview.model_validate(overview).model_dump(mode="json"),
        message="Access overview retrieved successfully",
        status_code=status.HTTP_200_OK,
    )


@router.delete(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Delete current user account",
    description=(
            "Permanently deletes the authenticated user's account, tokens, and access grants. "
            "If the user is the sole remaining member of their company, also deletes the entire "
            "company workspace (jobs, candidates, resumes, scores, and history)."
    ),
)
async def delete_current_user_account(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    result = await UsersService.delete_my_account(db, current_user)
    return success_response(
        data=result,
        message="Account deleted permanently",
        status_code=status.HTTP_200_OK,
    )


@router.get(
    "/admin/check",
    status_code=status.HTTP_200_OK,
    summary="Admin role validation check",
    description="Endpoint accessible only to administrators, used to verify role authorization.",
)
async def check_admin_access(
    admin_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return success_response(
        data={
            "user_id": str(admin_user.id),
            "role": admin_user.role.value,
            "is_admin": True,
        },
        message="Admin access granted",
        status_code=status.HTTP_200_OK,
    )
