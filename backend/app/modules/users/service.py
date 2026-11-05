import uuid

from app.core.exceptions import NotFoundException
from app.models.company import Company
from app.models.job import Job
from app.models.job_access import JobAccess, JobAccessLevel
from app.models.user import User
from app.schemas.user import CompanyAccessSummary, UserAccessOverview, UserJobAccessSummary
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class UsersService:
    """Service handling user profile lookups and validations."""

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
        """Fetch a user by UUID or raise NotFoundException."""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found")
        return user

    @staticmethod
    async def get_access_overview(db: AsyncSession, current_user: User) -> UserAccessOverview:
        company_access = None
        access_conditions = [JobAccess.user_id == current_user.id]
        if current_user.company_id:
            company_result = await db.execute(
                select(Company).where(Company.id == current_user.company_id)
            )
            company = company_result.scalar_one_or_none()
            if company:
                company_access = CompanyAccessSummary(
                    company_id=company.id,
                    company_name=company.name,
                    role=current_user.role,
                )
            access_conditions.append(Job.company_id == current_user.company_id)

        result = await db.execute(
            select(Job, Company.name, JobAccess.access_level, JobAccess.granted_by_id)
            .join(Company, Company.id == Job.company_id)
            .outerjoin(
                JobAccess,
                and_(JobAccess.job_id == Job.id, JobAccess.user_id == current_user.id),
            )
            .where(or_(*access_conditions))
            .order_by(Job.created_at.desc())
        )
        job_accesses = []
        for job, company_name, grant_level, granted_by_id in result.all():
            is_company_access = current_user.company_id == job.company_id
            job_accesses.append(
                UserJobAccessSummary(
                    job_id=job.id,
                    job_title=job.title,
                    company_id=job.company_id,
                    company_name=company_name,
                    status=job.status,
                    access_level=JobAccessLevel.EDITOR if is_company_access else grant_level,
                    access_source="company" if is_company_access else "job_grant",
                    granted_by_id=None if is_company_access else granted_by_id,
                )
            )
        return UserAccessOverview(company_access=company_access, job_accesses=job_accesses)
