import uuid

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.modules.companies.service import CompaniesService
from app.schemas.company import (
    CompanyCreateRequest,
    CompanyMemberGrantRequest,
    CompanyResponse,
    CompanyUpdateRequest,
)
from app.schemas.user import UserPublicResponse
from app.utils.responses import success_response
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new company",
    description="Creates a company organization and assigns the creator as administrator.",
)
async def create_company(
    request: CompanyCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    company = await CompaniesService.create_company(db, current_user, request)
    return success_response(
        data=CompanyResponse.model_validate(company).model_dump(mode="json"),
        message="Company created successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get current user company",
    description="Returns company information for the authenticated user (recruiters and admins).",
)
async def get_my_company(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    company = await CompaniesService.get_user_company(db, current_user)
    return success_response(
        data=CompanyResponse.model_validate(company).model_dump(mode="json"),
        message="Company details retrieved successfully",
        status_code=status.HTTP_200_OK,
    )


@router.put(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Update current company",
    description="Updates company information. Restricted to company administrators.",
)
async def update_my_company(
    request: CompanyUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    company = await CompaniesService.update_company(db, current_user, request)
    return success_response(
        data=CompanyResponse.model_validate(company).model_dump(mode="json"),
        message="Company updated successfully",
        status_code=status.HTTP_200_OK,
    )


@router.get(
    "/me/members",
    status_code=status.HTTP_200_OK,
    summary="List company members",
    description="Returns all users belonging to the company. Restricted to company administrators.",
)
async def get_company_members(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    members = await CompaniesService.get_company_members(db, current_user)
    serialized_members = [
        UserPublicResponse.model_validate(m).model_dump(mode="json")
        for m in members
    ]
    return success_response(
        data=serialized_members,
        message="Company members retrieved successfully",
        status_code=status.HTTP_200_OK,
    )


@router.post(
    "/me/members",
    status_code=status.HTTP_201_CREATED,
    summary="Grant company access",
    description="Adds an existing registered user as a recruiter in the current company.",
)
async def add_company_member(
        request: CompanyMemberGrantRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    member = await CompaniesService.add_company_member(db, current_user, request)
    return success_response(
        data=UserPublicResponse.model_validate(member).model_dump(mode="json"),
        message="Company access granted successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.delete(
    "/me/members/{member_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke company access",
    description="Removes a recruiter from the current company.",
)
async def remove_company_member(
        member_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    await CompaniesService.remove_company_member(db, current_user, member_id)
    return success_response(None, "Company access revoked successfully")
