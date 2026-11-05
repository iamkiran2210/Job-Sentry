from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.company import Company
from app.models.user import User, UserRole
from app.schemas.company import CompanyCreateRequest, CompanyUpdateRequest


class CompaniesService:
    """Service handling company lifecycle, administration, and member listings."""

    @staticmethod
    async def create_company(
        db: AsyncSession,
        current_user: User,
        request: CompanyCreateRequest,
    ) -> Company:
        """
        Create a new company and assign the current user as company administrator.
        Enforces one company per user rule within a single transaction.
        """
        if current_user.company_id is not None:
            raise ConflictException("User is already associated with an existing company")

        # Create company entity
        company = Company(
            name=request.name.strip(),
            industry=request.industry.strip() if request.industry else None,
            website=request.website.strip() if request.website else None,
            description=request.description.strip() if request.description else None,
            location=request.location.strip() if request.location else None,
        )
        db.add(company)
        await db.flush()

        # Associate creator with company as ADMIN in the same transaction
        current_user.company_id = company.id
        current_user.role = UserRole.ADMIN

        await db.commit()
        await db.refresh(company)
        return company

    @staticmethod
    async def get_user_company(
        db: AsyncSession,
        current_user: User,
    ) -> Company:
        """
        Retrieve company information for the current user.
        Accessible by both recruiters and administrators belonging to the company.
        """
        if not current_user.company_id:
            raise NotFoundException("User does not belong to any company")

        result = await db.execute(
            select(Company).where(Company.id == current_user.company_id)
        )
        company = result.scalar_one_or_none()

        if not company:
            raise NotFoundException("Associated company could not be found")

        return company

    @staticmethod
    async def update_company(
        db: AsyncSession,
        current_user: User,
        request: CompanyUpdateRequest,
    ) -> Company:
        """
        Update company details.
        Permitted only for company administrators.
        """
        if not current_user.company_id:
            raise NotFoundException("User does not belong to any company")

        if current_user.role != UserRole.ADMIN:
            raise ForbiddenException("Only company administrators can update company information")

        result = await db.execute(
            select(Company).where(Company.id == current_user.company_id)
        )
        company = result.scalar_one_or_none()

        if not company:
            raise NotFoundException("Associated company could not be found")

        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None and isinstance(value, str):
                setattr(company, field, value.strip())
            else:
                setattr(company, field, value)

        await db.commit()
        await db.refresh(company)
        return company

    @staticmethod
    async def get_company_members(
        db: AsyncSession,
        current_user: User,
    ) -> List[User]:
        """
        Retrieve all member accounts belonging to the user's company.
        Restricted exclusively to company administrators.
        """
        if not current_user.company_id:
            raise NotFoundException("User does not belong to any company")

        if current_user.role != UserRole.ADMIN:
            raise ForbiddenException("Only company administrators can view company members")

        result = await db.execute(
            select(User)
            .where(User.company_id == current_user.company_id)
            .order_by(User.created_at.asc())
        )
        members = result.scalars().all()
        return list(members)
