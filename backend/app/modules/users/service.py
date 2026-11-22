import asyncio
import uuid

import sqlalchemy as sa
from app.core.exceptions import NotFoundException
from app.models.company import Company
from app.models.job import Job
from app.models.job_access import JobAccess, JobAccessLevel
from app.models.token import RefreshToken
from app.models.user import User, UserRole
from app.schemas.user import (
    CompanyAccessSummary,
    UserAccessOverview,
    UserJobAccessSummary,
)
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

    @staticmethod
    async def delete_my_account(db: AsyncSession, current_user: User) -> dict[str, int | bool]:
        """Permanently delete the authenticated user's account and clear all personal/sole-company data.

        - Always deletes the user's refresh tokens, job access grants, and user record.
        - If the user is the sole remaining member of their company, permanently purges the entire
          company workspace (jobs, requirements, candidates, applications, resumes & stored files,
          extracted profiles, identity suggestions, scores, evidence, explanations, verifications,
          ranking runs/history, status history, and the company itself) leaving zero breadcrumbs.
        - If other users remain in the same company, preserves the shared company workspace,
          unlinks this user's ID from shared records, and promotes the earliest remaining active
          member to ADMIN if the deleting user was the last administrator.
        """
        from app.ai_features.models.application import Application
        from app.ai_features.models.candidate import Candidate
        from app.ai_features.models.extracted_profile import ExtractedProfile
        from app.ai_features.models.identity_suggestion import IdentitySuggestion
        from app.ai_features.models.resume import Resume
        from app.ai_features.resumes.storage import get_storage
        from app.models.job_requirement import JobRequirement
        from app.modules.application_status.models import ApplicationStatusHistory
        from app.modules.candidate_intelligence.models import (
            CandidateScore,
            RankingHistory,
            RankingRun,
            ScoreEvidenceRecord,
            ScoreExplanation,
            VerificationResult,
        )

        user_id = current_user.id
        company_id = current_user.company_id
        storage_keys: list[str] = []
        counts: dict[str, int | bool] = {
            "deleted": True,
            "company_deleted": False,
            "jobs_deleted": 0,
            "candidates_deleted": 0,
            "applications_deleted": 0,
            "resumes_deleted": 0,
        }

        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
        if is_pg:
            await db.execute(
                sa.text("SELECT set_config('job_sentry.allow_candidate_purge', 'on', true)")
            )

        # Always revoke/delete all refresh tokens and explicit job access grants involving this user
        await db.execute(sa.delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await db.execute(
            sa.delete(JobAccess).where(
                or_(JobAccess.user_id == user_id, JobAccess.granted_by_id == user_id)
            )
        )

        other_members: list[User] = []
        if company_id is not None:
            other_members = list(
                (
                    await db.execute(
                        select(User)
                        .where(User.company_id == company_id, User.id != user_id)
                        .order_by(User.created_at.asc(), User.id.asc())
                    )
                )
                .scalars()
                .all()
            )

        if company_id is not None and len(other_members) == 0:
            # Sole member of the company -> purge entire company workspace cleanly
            job_ids = list(
                (await db.execute(select(Job.id).where(Job.company_id == company_id)))
                .scalars()
                .all()
            )
            app_ids = list(
                (
                    await db.execute(
                        select(Application.id).where(Application.company_id == company_id)
                    )
                )
                .scalars()
                .all()
            )
            resumes = list(
                (await db.execute(select(Resume).where(Resume.company_id == company_id)))
                .scalars()
                .all()
            )
            resume_ids = [r.id for r in resumes]
            storage_keys = [r.storage_key for r in resumes if r.storage_key]

            score_ids = list(
                (
                    await db.execute(
                        select(CandidateScore.id).where(CandidateScore.company_id == company_id)
                    )
                )
                .scalars()
                .all()
            )
            cand_count = (
                await db.execute(
                    sa.select(sa.func.count())
                    .select_from(Candidate)
                    .where(Candidate.company_id == company_id)
                )
            ).scalar_one()

            # Delete dependent tables in strict FK order
            await db.execute(
                sa.delete(RankingHistory).where(RankingHistory.company_id == company_id)
            )
            if job_ids:
                await db.execute(
                    sa.delete(RankingHistory).where(RankingHistory.job_id.in_(job_ids))
                )
                await db.execute(sa.delete(RankingRun).where(RankingRun.job_id.in_(job_ids)))
            await db.execute(
                sa.delete(ApplicationStatusHistory).where(
                    ApplicationStatusHistory.company_id == company_id
                )
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
                    ScoreEvidenceRecord.company_id == company_id
                )
            )
            await db.execute(
                sa.delete(CandidateScore).where(CandidateScore.company_id == company_id)
            )
            await db.execute(
                sa.delete(VerificationResult).where(VerificationResult.company_id == company_id)
            )
            if resume_ids:
                await db.execute(
                    sa.delete(ExtractedProfile).where(
                        ExtractedProfile.resume_id.in_(resume_ids)
                    )
                )
            await db.execute(
                sa.delete(ExtractedProfile).where(ExtractedProfile.company_id == company_id)
            )
            await db.execute(sa.delete(Resume).where(Resume.company_id == company_id))
            await db.execute(sa.delete(Application).where(Application.company_id == company_id))
            await db.execute(
                sa.delete(IdentitySuggestion).where(IdentitySuggestion.company_id == company_id)
            )
            await db.execute(sa.delete(Candidate).where(Candidate.company_id == company_id))
            if job_ids:
                await db.execute(
                    sa.delete(JobRequirement).where(JobRequirement.job_id.in_(job_ids))
                )
                await db.execute(sa.delete(JobAccess).where(JobAccess.job_id.in_(job_ids)))
            await db.execute(sa.delete(Job).where(Job.company_id == company_id))

            # Delete user and company
            await db.execute(sa.delete(User).where(User.id == user_id))
            await db.execute(sa.delete(Company).where(Company.id == company_id))

            counts["company_deleted"] = True
            counts["jobs_deleted"] = len(job_ids)
            counts["candidates_deleted"] = int(cand_count or 0)
            counts["applications_deleted"] = len(app_ids)
            counts["resumes_deleted"] = len(resumes)
        else:
            # Shared company or standalone user: unlink personal FKs and promote another admin if needed
            if company_id is not None and current_user.role == UserRole.ADMIN:
                has_other_admin = any(m.role == UserRole.ADMIN and m.is_active for m in other_members)
                if not has_other_admin:
                    replacement = next((m for m in other_members if m.is_active), other_members[0])
                    replacement.role = UserRole.ADMIN

            await db.execute(
                sa.update(Resume)
                .where(Resume.uploaded_by == user_id)
                .values(uploaded_by=None)
            )
            await db.execute(
                sa.update(RankingRun)
                .where(RankingRun.triggered_by == user_id)
                .values(triggered_by=None)
            )
            await db.execute(
                sa.update(RankingHistory)
                .where(RankingHistory.triggered_by == user_id)
                .values(triggered_by=None)
            )
            await db.execute(sa.delete(User).where(User.id == user_id))

        await db.commit()

        # Remove resume binary files from storage after DB commit succeeds
        if storage_keys:
            storage = get_storage()
            for key in storage_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:
                    pass

        return counts
