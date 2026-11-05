from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_active_user, require_role
from app.models.user import User, UserRole
from app.schemas.user import UserResponse
from app.utils.responses import success_response

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
    "/admin/check",
    status_code=status.HTTP_200_OK,
    summary="Admin role validation check",
    description="Endpoint accessible only to administrators, used to verify role authorization.",
)
async def check_admin_access(
    admin_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return success_response(
        data={"user_id": str(admin_user.id), "role": admin_user.role.value},
        message="Admin access granted",
        status_code=status.HTTP_200_OK,
    )
