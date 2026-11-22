import math
import uuid

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
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
    async def update_job(
            db: AsyncSession,
            current_user: User,
            job_id: uuid.UUID,
            request: JobUpdateRequest,
    ) -> Job:
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
        await JobsService._purge_jobs_internal(db, [job])

    @staticmethod
    async def purge_job(
            db: AsyncSession, current_user: User, job_id: uuid.UUID
    ) -> dict[str, int]:
        """Clean-delete a single job (any status) along with all dependent records and resume files."""
        job = await JobsService.get_job(db, current_user, job_id, require_edit=True)
        return await JobsService._purge_jobs_internal(db, [job])

    @staticmethod
    async def _purge_jobs_internal(db: AsyncSession, jobs: list[Job]) -> dict[str, int]:
        """Permanently remove the given jobs and all dependent applications, resumes, scores, and audit rows."""
        import asyncio
        import sqlalchemy as sa

        from app.ai_features.models.application import Application
        from app.ai_features.models.extracted_profile import ExtractedProfile
        from app.ai_features.models.resume import Resume
        from app.ai_features.resumes.storage import get_storage
        from app.modules.application_status.models import ApplicationStatusHistory
        from app.modules.candidate_intelligence.models import (
            CandidateScore,
            RankingHistory,
            RankingRun,
            ScoreEvidenceRecord,
            ScoreExplanation,
            VerificationResult,
        )

        job_ids = [j.id for j in jobs]
        if not job_ids:
            return {"jobs_deleted": 0, "applications_deleted": 0, "resumes_deleted": 0}

        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
        if is_pg:
            await db.execute(
                sa.text("SELECT set_config('job_sentry.allow_candidate_purge', 'on', true)")
            )

        app_ids = list(
            (
                await db.execute(
                    sa.select(Application.id).where(Application.job_id.in_(job_ids))
                )
            )
            .scalars()
            .all()
        )
        storage_keys: list[str] = []
        resumes_deleted = 0

        await db.execute(sa.delete(RankingHistory).where(RankingHistory.job_id.in_(job_ids)))
        await db.execute(sa.delete(RankingRun).where(RankingRun.job_id.in_(job_ids)))
        await db.execute(
            sa.delete(ApplicationStatusHistory).where(
                ApplicationStatusHistory.job_id.in_(job_ids)
            )
        )

        if app_ids:
            resumes = list(
                (
                    await db.execute(sa.select(Resume).where(Resume.application_id.in_(app_ids)))
                )
                .scalars()
                .all()
            )
            resume_ids = [r.id for r in resumes]
            storage_keys = [r.storage_key for r in resumes if r.storage_key]
            resumes_deleted = len(resumes)

            score_ids = list(
                (
                    await db.execute(
                        sa.select(CandidateScore.id).where(
                            CandidateScore.application_id.in_(app_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if score_ids:
                await db.execute(
                    sa.delete(ScoreExplanation).where(
                        ScoreExplanation.candidate_score_id.in_(score_ids)
                    )
                )
                await db.execute(
                    sa.delete(ScoreEvidenceRecord).where(
                        ScoreEvidenceRecord.score_id.in_(score_ids)
                    )
                )
            await db.execute(
                sa.delete(ScoreEvidenceRecord).where(
                    ScoreEvidenceRecord.application_id.in_(app_ids)
                )
            )
            await db.execute(
                sa.delete(CandidateScore).where(CandidateScore.application_id.in_(app_ids))
            )
            await db.execute(
                sa.delete(VerificationResult).where(
                    VerificationResult.application_id.in_(app_ids)
                )
            )
            if resume_ids:
                await db.execute(
                    sa.delete(ExtractedProfile).where(
                        ExtractedProfile.resume_id.in_(resume_ids)
                    )
                )
            await db.execute(sa.delete(Resume).where(Resume.application_id.in_(app_ids)))
            await db.execute(sa.delete(Application).where(Application.id.in_(app_ids)))

        await db.execute(sa.delete(JobRequirement).where(JobRequirement.job_id.in_(job_ids)))
        await db.execute(sa.delete(JobAccess).where(JobAccess.job_id.in_(job_ids)))
        await db.execute(sa.delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()

        if storage_keys:
            storage = get_storage()
            for key in storage_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:
                    pass

        return {
            "jobs_deleted": len(job_ids),
            "applications_deleted": len(app_ids),
            "resumes_deleted": resumes_deleted,
        }

    @staticmethod
    async def purge_all_jobs(db: AsyncSession, current_user: User) -> dict[str, int]:
        """Data Explorer clean delete: permanently remove all jobs (and dependent records/files) for the company."""
        if not current_user.company_id:
            raise NotFoundException("User does not belong to any company")

        jobs = list(
            (
                await db.execute(select(Job).where(Job.company_id == current_user.company_id))
            )
            .scalars()
            .all()
        )
        return await JobsService._purge_jobs_internal(db, jobs)

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
            raise BadRequestException(
                "Preferred requirement weights must total 1.0 before publishing"
            )

    @staticmethod
    async def transition(
            db: AsyncSession, current_user: User, job_id: uuid.UUID, action: str
    ) -> Job:
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
            select(JobRequirement)
            .where(JobRequirement.job_id == job.id)
            .order_by(JobRequirement.created_at)
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
    async def create_requirement(
            db: AsyncSession, job: Job, request: JobRequirementCreateRequest
    ) -> JobRequirement:
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
            db: AsyncSession,
            job: Job,
            requirement_id: uuid.UUID,
            request: JobRequirementUpdateRequest,
    ) -> JobRequirement:
        JobsService._ensure_requirements_editable(job)
        result = await db.execute(
            select(JobRequirement).where(
                JobRequirement.id == requirement_id, JobRequirement.job_id == job.id
            )
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
            **{
                key: getattr(requirement, key)
                for key in (
                    "category",
                    "name",
                    "requirement_type",
                    "importance",
                    "weight",
                    "is_mandatory",
                )
            },
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
            select(JobRequirement).where(
                JobRequirement.id == requirement_id, JobRequirement.job_id == job.id
            )
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
