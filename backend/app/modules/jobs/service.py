import math
import uuid

from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.models.job import Job, JobStatus
from app.models.job_access import JobAccess, JobAccessLevel
from app.models.job_requirement import JobRequirement, RequirementType
from app.models.user import User, UserRole
from app.schemas.job import (
    JobAccessGrantRequest,
    JobCreateRequest,
    JobRequirementCreateRequest,
    JobRequirementFields,
    JobRequirementUpdateRequest,
    JobUpdateRequest,
    RequirementExtractionSuggestions,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class JobsService:
    @staticmethod
    async def get_job(
            db: AsyncSession,
            current_user: User,
            job_id: uuid.UUID,
            require_edit: bool = False,
    ) -> Job:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundException("Job not found")
        if current_user.company_id != job.company_id:
            access_result = await db.execute(
                select(JobAccess).where(
                    JobAccess.job_id == job.id,
                    JobAccess.user_id == current_user.id,
                )
            )
            access = access_result.scalar_one_or_none()
            if access is None:
                raise NotFoundException("Job not found")
            if require_edit and access.access_level != JobAccessLevel.EDITOR:
                raise ForbiddenException("Viewer access does not permit editing this job")
        return job

    @staticmethod
    async def list_jobs(db: AsyncSession, current_user: User) -> list[Job]:
        conditions = [JobAccess.user_id == current_user.id]
        if current_user.company_id:
            conditions.append(Job.company_id == current_user.company_id)
        result = await db.execute(
            select(Job)
            .outerjoin(
                JobAccess,
                and_(JobAccess.job_id == Job.id, JobAccess.user_id == current_user.id),
            )
            .where(or_(*conditions))
            .distinct()
            .order_by(Job.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_job(db: AsyncSession, current_user: User, request: JobCreateRequest) -> Job:
        if not current_user.company_id:
            raise NotFoundException("User does not belong to any company")
        job = Job(company_id=current_user.company_id, **request.model_dump())
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    @staticmethod
    async def update_job(db: AsyncSession, current_user: User, job_id: uuid.UUID, request: JobUpdateRequest) -> Job:
        job = await JobsService.get_job(db, current_user, job_id, require_edit=True)
        if job.status in (JobStatus.CLOSED, JobStatus.ARCHIVED):
            raise ConflictException("Closed or archived jobs cannot be edited")
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(job, field, value)
        await db.commit()
        await db.refresh(job)
        return job

    @staticmethod
    async def delete_job(db: AsyncSession, current_user: User, job_id: uuid.UUID) -> None:
        job = await JobsService.get_job(db, current_user, job_id, require_edit=True)
        if job.status != JobStatus.DRAFT:
            raise ConflictException("Only draft jobs can be deleted")
        await db.delete(job)
        await db.commit()

    @staticmethod
    async def validate_weights(db: AsyncSession, job_id: uuid.UUID) -> None:
        result = await db.execute(
            select(JobRequirement.weight).where(
                JobRequirement.job_id == job_id,
                JobRequirement.requirement_type == RequirementType.PREFERRED,
            )
        )
        weights = list(result.scalars().all())
        if weights and not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise BadRequestException("Preferred requirement weights must total 1.0 before publishing")

    @staticmethod
    async def transition(db: AsyncSession, current_user: User, job_id: uuid.UUID, action: str) -> Job:
        job = await JobsService.get_job(db, current_user, job_id, require_edit=True)
        transitions = {
            "publish": {JobStatus.DRAFT, JobStatus.PAUSED},
            "pause": {JobStatus.ACTIVE},
            "close": {JobStatus.ACTIVE, JobStatus.PAUSED},
            "archive": {JobStatus.CLOSED},
        }
        targets = {
            "publish": JobStatus.ACTIVE,
            "pause": JobStatus.PAUSED,
            "close": JobStatus.CLOSED,
            "archive": JobStatus.ARCHIVED,
        }
        if job.status not in transitions[action]:
            raise ConflictException(f"Cannot {action} a job with status '{job.status.value}'")
        if action == "publish":
            await JobsService.validate_weights(db, job.id)
        job.status = targets[action]
        await db.commit()
        await db.refresh(job)
        return job

    @staticmethod
    async def list_requirements(db: AsyncSession, job: Job) -> list[JobRequirement]:
        result = await db.execute(
            select(JobRequirement).where(JobRequirement.job_id == job.id).order_by(JobRequirement.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _ensure_active_weights_valid(db: AsyncSession, job: Job) -> None:
        if job.status == JobStatus.ACTIVE:
            await JobsService.validate_weights(db, job.id)

    @staticmethod
    def _ensure_requirements_editable(job: Job) -> None:
        if job.status in (JobStatus.CLOSED, JobStatus.ARCHIVED):
            raise ConflictException("Requirements on closed or archived jobs cannot be edited")

    @staticmethod
    async def create_requirement(db: AsyncSession, job: Job, request: JobRequirementCreateRequest) -> JobRequirement:
        JobsService._ensure_requirements_editable(job)
        requirement = JobRequirement(job_id=job.id, **request.model_dump())
        db.add(requirement)
        await db.flush()
        await JobsService._ensure_active_weights_valid(db, job)
        await db.commit()
        await db.refresh(requirement)
        return requirement

    @staticmethod
    async def update_requirement(
            db: AsyncSession, job: Job, requirement_id: uuid.UUID, request: JobRequirementUpdateRequest
    ) -> JobRequirement:
        JobsService._ensure_requirements_editable(job)
        result = await db.execute(
            select(JobRequirement).where(JobRequirement.id == requirement_id, JobRequirement.job_id == job.id)
        )
        requirement = result.scalar_one_or_none()
        if requirement is None:
            raise NotFoundException("Requirement not found")
        updates = request.model_dump(exclude_unset=True)
        if "is_mandatory" in updates and "requirement_type" not in updates:
            updates["requirement_type"] = (
                RequirementType.MANDATORY if updates["is_mandatory"] else RequirementType.PREFERRED
            )
        elif "requirement_type" in updates and "is_mandatory" not in updates:
            updates["is_mandatory"] = updates["requirement_type"] == RequirementType.MANDATORY
        if updates.get("is_mandatory") is True and "weight" not in updates:
            updates["weight"] = 0.0
        updated = {
            **{key: getattr(requirement, key) for key in (
                "category", "name", "requirement_type", "importance", "weight", "is_mandatory"
            )},
            **updates,
        }
        validated = JobRequirementFields.model_validate(updated)
        for field, value in validated.model_dump().items():
            setattr(requirement, field, value)
        await JobsService._ensure_active_weights_valid(db, job)
        await db.commit()
        await db.refresh(requirement)
        return requirement

    @staticmethod
    async def delete_requirement(db: AsyncSession, job: Job, requirement_id: uuid.UUID) -> None:
        JobsService._ensure_requirements_editable(job)
        result = await db.execute(
            select(JobRequirement).where(JobRequirement.id == requirement_id, JobRequirement.job_id == job.id)
        )
        requirement = result.scalar_one_or_none()
        if requirement is None:
            raise NotFoundException("Requirement not found")
        await db.delete(requirement)
        await db.flush()
        await JobsService._ensure_active_weights_valid(db, job)
        await db.commit()

    @staticmethod
    async def validate_extraction(value: object) -> RequirementExtractionSuggestions:
        return RequirementExtractionSuggestions.model_validate(value)

    @staticmethod
    def _require_job_company_admin(current_user: User, job: Job) -> None:
        if current_user.company_id != job.company_id or current_user.role != UserRole.ADMIN:
            raise ForbiddenException("Only the job's company administrators can manage job access")

    @staticmethod
    async def list_job_access(
            db: AsyncSession, current_user: User, job: Job
    ) -> list[tuple[JobAccess, User]]:
        JobsService._require_job_company_admin(current_user, job)
        result = await db.execute(
            select(JobAccess, User)
            .join(User, User.id == JobAccess.user_id)
            .where(JobAccess.job_id == job.id)
            .order_by(JobAccess.created_at.asc())
        )
        return list(result.all())

    @staticmethod
    async def grant_job_access(
            db: AsyncSession,
            current_user: User,
            job: Job,
            request: JobAccessGrantRequest,
    ) -> tuple[JobAccess, User]:
        JobsService._require_job_company_admin(current_user, job)
        user_result = await db.execute(select(User).where(User.email == request.email))
        target_user = user_result.scalar_one_or_none()
        if target_user is None:
            raise NotFoundException("A registered user with that email was not found")
        if target_user.company_id == job.company_id:
            raise ConflictException("Company members already have access to this job")
        access_result = await db.execute(
            select(JobAccess).where(JobAccess.job_id == job.id, JobAccess.user_id == target_user.id)
        )
        grant = access_result.scalar_one_or_none()
        if grant is None:
            grant = JobAccess(
                job_id=job.id,
                user_id=target_user.id,
                access_level=request.access_level,
                granted_by_id=current_user.id,
            )
            db.add(grant)
        else:
            grant.access_level = request.access_level
            grant.granted_by_id = current_user.id
        await db.commit()
        await db.refresh(grant)
        return grant, target_user

    @staticmethod
    async def revoke_job_access(
            db: AsyncSession,
            current_user: User,
            job: Job,
            user_id: uuid.UUID,
    ) -> None:
        JobsService._require_job_company_admin(current_user, job)
        result = await db.execute(
            select(JobAccess).where(JobAccess.job_id == job.id, JobAccess.user_id == user_id)
        )
        grant = result.scalar_one_or_none()
        if grant is None:
            raise NotFoundException("Job access grant not found")
        await db.delete(grant)
        await db.commit()
