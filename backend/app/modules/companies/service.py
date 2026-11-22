import uuid
from typing import List

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.company import Company
from app.models.user import User, UserRole
from app.schemas.company import (
    CompanyCreateRequest,
    CompanyMemberGrantRequest,
    CompanyUpdateRequest,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class CompaniesService:
    """Service handling company lifecycle, administration, and member listings."""

    @staticmethod
    def _require_company_admin(current_user: User) -> None:
        if not current_user.company_id:
            raise NotFoundException("User does not belong to any company")
        if current_user.role != UserRole.ADMIN:
            raise ForbiddenException("Only company administrators can manage company access")

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

        result = await db.execute(select(Company).where(Company.id == current_user.company_id))
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

        result = await db.execute(select(Company).where(Company.id == current_user.company_id))
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
        CompaniesService._require_company_admin(current_user)

        result = await db.execute(
            select(User)
            .where(User.company_id == current_user.company_id)
            .order_by(User.created_at.asc())
        )
        members = result.scalars().all()
        return list(members)

    @staticmethod
    async def add_company_member(
            db: AsyncSession,
            current_user: User,
            request: CompanyMemberGrantRequest,
    ) -> User:
        CompaniesService._require_company_admin(current_user)
        result = await db.execute(
            select(User).where(User.email == str(request.email).lower()).with_for_update()
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise NotFoundException("A registered user with that email was not found")
        if member.company_id is not None:
            raise ConflictException("User already belongs to a company")
        member.company_id = current_user.company_id
        member.role = UserRole.RECRUITER
        await db.commit()
        await db.refresh(member)
        return member

    @staticmethod
    async def remove_company_member(
            db: AsyncSession,
            current_user: User,
            member_id: uuid.UUID,
    ) -> None:
        CompaniesService._require_company_admin(current_user)
        result = await db.execute(
            select(User).where(User.id == member_id, User.company_id == current_user.company_id)
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise NotFoundException("Company member not found")
        if member.role == UserRole.ADMIN:
            raise ConflictException(
                "Company administrators cannot be removed through member access management"
            )
        member.company_id = None
        await db.commit()

    @staticmethod
    async def remove_all_company_members(
            db: AsyncSession,
            current_user: User,
    ) -> dict[str, int]:
        """Data Explorer bulk action: remove all non-admin team members from the company while preserving admins."""
        from app.models.job import Job
        from app.models.job_access import JobAccess
        from sqlalchemy import delete

        CompaniesService._require_company_admin(current_user)
        members = list(
            (
                await db.execute(
                    select(User).where(User.company_id == current_user.company_id)
                )
            )
            .scalars()
            .all()
        )
        removable = [
            m for m in members if m.role != UserRole.ADMIN and m.id != current_user.id
        ]
        admins_preserved = len(members) - len(removable)

        if removable:
            removable_ids = [m.id for m in removable]
            job_ids = list(
                (
                    await db.execute(
                        select(Job.id).where(Job.company_id == current_user.company_id)
                    )
                )
                .scalars()
                .all()
            )
            if job_ids:
                await db.execute(
                    delete(JobAccess).where(
                        JobAccess.job_id.in_(job_ids),
                        JobAccess.user_id.in_(removable_ids),
                    )
                )
            for m in removable:
                m.company_id = None
            await db.commit()

        return {
            "members_removed": len(removable),
            "admins_preserved": admins_preserved,
        }
