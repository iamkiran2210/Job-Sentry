from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume

from app.ai_features._compat import get_accessible_job
from .config import ResumeSettings
from .dispatch import Dispatcher
from .enums import ApplicationStatus, ResumeStatus
from .errors import DispatchError, RejectCode, StorageError, UploadRejected
from .storage import ObjectStorage, build_key
from .timeutil import as_utc, utcnow
from .validation import sanitize_filename, validate_upload

log = logging.getLogger("resumes.service")


@dataclass
class IngestResult:
    filename: str
    status: Literal["accepted", "duplicate", "rejected"]
    resume_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    processing_status: str | None = None
    reason_code: str | None = None
    detail: str | None = None


class NotFound(Exception):
    """Missing record. Routers turn it into the same 404 a no-access caller gets (no existence leak)."""


class RetryConflict(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _cas_status(db: AsyncSession, resume_id, frm: ResumeStatus, to: ResumeStatus) -> bool:
    res = await db.execute(
        sa.update(Resume)
        .where(Resume.id == resume_id, Resume.status == frm.value)
        .values(status=to.value, status_updated_at=utcnow())
    )
    return res.rowcount == 1


async def _by_hash(db: AsyncSession, company_id, job_id, sha: str) -> Resume | None:
    return (
        await db.execute(
            sa.select(Resume).where(
                Resume.company_id == company_id,
                Resume.job_id == job_id,
                Resume.sha256 == sha,
            )
        )
    ).scalar_one_or_none()


class ResumesService:
    """Business rules for resume ingestion. Access always goes through Phase 2's JobsService.get_job."""

    @staticmethod
    async def job_for_upload(db: AsyncSession, user, job_id):
        """Company member or job EDITOR. Raises your standard 404/403 otherwise."""
        return await get_accessible_job(db, user, job_id, require_edit=True)

    @staticmethod
    async def ingest_file(
            db: AsyncSession,
            *,
            job,
            user,
            filename: str | None,
            data: bytes,
            cfg: ResumeSettings,
            storage: ObjectStorage,
            dispatcher: Dispatcher,
    ) -> IngestResult:
        company_id, job_id = (
            job.company_id,
            job.id,
        )  # tenant is the JOB's company, never the caller's claim
        company_id, job_id, user_id = company_id, job_id, user.id
        safe_name = sanitize_filename(filename)
        try:
            v = validate_upload(filename, data, cfg)
        except UploadRejected as exc:
            return IngestResult(
                safe_name, "rejected", reason_code=exc.code.value, detail=exc.detail
            )

        def duplicate(r: Resume) -> IngestResult:
            return IngestResult(v.filename, "duplicate", r.id, r.application_id, r.status)

        if existing := await _by_hash(db, company_id, job_id, v.sha256):
            return duplicate(existing)

        prior = (
            await db.execute(
                sa.select(Resume.id)
                .where(Resume.company_id == company_id, Resume.sha256 == v.sha256)
                .order_by(Resume.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        resume_id, app_id = uuid.uuid4(), uuid.uuid4()
        key = build_key(company_id, job_id, resume_id, v.extension)
        stored = False
        try:
            db.add(
                Application(
                    id=app_id,
                    company_id=company_id,
                    job_id=job_id,
                    candidate_id=None,
                    status=ApplicationStatus.APPLIED.value,
                )
            )
            await db.flush()
            db.add(
                Resume(
                    id=resume_id,
                    company_id=company_id,
                    job_id=job_id,
                    application_id=app_id,
                    uploaded_by=user_id,
                    original_filename=v.filename,
                    extension=v.extension,
                    content_type=v.content_type,
                    size_bytes=v.size_bytes,
                    sha256=v.sha256,
                    storage_backend=storage.backend_name,
                    storage_key=key,
                    status=ResumeStatus.UPLOADED.value,
                    duplicate_of_resume_id=prior,
                )
            )
            await db.flush()  # unique constraint catches concurrent identical uploads
            await asyncio.to_thread(storage.put, key, data, content_type=v.content_type)
            stored = True
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if existing := await _by_hash(db, company_id, job_id, v.sha256):
                return duplicate(existing)
            return IngestResult(
                v.filename,
                "rejected",
                reason_code="CONFLICT",
                detail="Could not record the upload.",
            )
        except StorageError:
            await db.rollback()
            return IngestResult(
                v.filename,
                "rejected",
                reason_code=RejectCode.STORAGE_UNAVAILABLE.value,
                detail="File storage is temporarily unavailable.",
            )
        except Exception:
            await db.rollback()
            if stored:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except StorageError:
                    pass
            raise

        # Hand off to the worker. CAS (uploaded->queued) first so a fast worker can't be overwritten.
        await _cas_status(db, resume_id, ResumeStatus.UPLOADED, ResumeStatus.QUEUED)
        await db.commit()
        status = ResumeStatus.QUEUED
        try:
            await asyncio.to_thread(dispatcher.enqueue, resume_id)
        except DispatchError:
            await _cas_status(db, resume_id, ResumeStatus.QUEUED, ResumeStatus.UPLOADED)
            await db.commit()
            status = ResumeStatus.UPLOADED  # the sweeper / retry endpoint will pick it up
            log.warning("enqueue failed resume=%s", resume_id)
        return IngestResult(v.filename, "accepted", resume_id, app_id, status.value)

    # ---------------------------------------------------------------- reads (access via the resume's job)
    @staticmethod
    async def get_resume(
            db: AsyncSession, user, resume_id, *, require_edit: bool = False
    ) -> Resume:
        r = await db.get(Resume, resume_id)
        if r is None:
            raise NotFound
        await get_accessible_job(db, user, r.job_id, require_edit=require_edit)
        return r

    @staticmethod
    async def get_profile(db: AsyncSession, resume_id) -> ExtractedProfile | None:
        return (
            await db.execute(
                sa.select(ExtractedProfile).where(
                    ExtractedProfile.resume_id == resume_id,
                    ExtractedProfile.profile_data.is_not(None),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_application(
            db: AsyncSession, user, application_id
    ) -> tuple[Application, list[Resume]]:
        app = await db.get(Application, application_id)
        if app is None:
            raise NotFound
        await get_accessible_job(db, user, app.job_id)
        resumes = (
            (
                await db.execute(
                    sa.select(Resume)
                    .where(Resume.application_id == app.id)
                    .order_by(Resume.created_at)
                )
            )
            .scalars()
            .all()
        )
        if (
                app.candidate_id is None
                and app.status == "withdrawn"
                and not resumes
        ):
            raise NotFound
        return app, list(resumes)

    # ---------------------------------------------------------------- retry (editor/member only)
    @staticmethod
    async def request_retry(
            db: AsyncSession, user, resume_id, cfg: ResumeSettings, dispatcher: Dispatcher
    ) -> Resume:
        r0 = await ResumesService.get_resume(db, user, resume_id, require_edit=True)
        r = (
            await db.execute(sa.select(Resume).where(Resume.id == r0.id).with_for_update())
        ).scalar_one()
        if r.status == ResumeStatus.FAILED:
            if r.retry_count >= cfg.manual_retry_limit:
                await db.rollback()
                raise RetryConflict("retry_limit_reached")
            r.retry_count += 1
        elif r.status != ResumeStatus.UPLOADED:
            await db.rollback()
            raise RetryConflict("not_retryable")
        r.status, r.status_updated_at = ResumeStatus.QUEUED.value, utcnow()
        r.attempt_count, r.lease_expires_at = 0, None
        r.failure_code = r.failure_message = r.last_error_code = None
        await db.commit()
        try:
            await asyncio.to_thread(dispatcher.enqueue, resume_id)
        except DispatchError:
            await _cas_status(db, resume_id, ResumeStatus.QUEUED, ResumeStatus.UPLOADED)
            await db.commit()
        await db.refresh(r)
        return r

    # ---------------------------------------------------------------- delete (editor/member only)
    @staticmethod
    async def delete_application(
            db: AsyncSession,
            user,
            application_id: uuid.UUID,
            storage: ObjectStorage | None = None,
    ) -> tuple[uuid.UUID, int, bool]:
        """Delete a job application and its resumes while preserving append-only audit tables."""
        from app.modules.application_status.models import ApplicationStatusHistory
        from app.modules.candidate_intelligence.models import RankingHistory

        app = await db.get(Application, application_id)
        if app is None:
            raise NotFound
        await get_accessible_job(db, user, app.job_id, require_edit=True)

        resumes = list(
            (
                await db.execute(
                    sa.select(Resume).where(Resume.application_id == app.id)
                )
            )
            .scalars()
            .all()
        )
        storage_keys = [r.storage_key for r in resumes if r.storage_key]

        has_ranking_audit = (
                                await db.execute(
                                    sa.select(RankingHistory.id)
                                    .where(RankingHistory.application_id == app.id)
                                    .limit(1)
                                )
                            ).scalar_one_or_none() is not None
        has_status_audit = (
                               await db.execute(
                                   sa.select(ApplicationStatusHistory.id)
                                   .where(ApplicationStatusHistory.application_id == app.id)
                                   .limit(1)
                               )
                           ).scalar_one_or_none() is not None
        audit_preserved = has_ranking_audit or has_status_audit

        if audit_preserved:
            app.candidate_id = None
            app.status = "withdrawn"
            for r in resumes:
                await db.delete(r)
        else:
            for r in resumes:
                await db.delete(r)
            await db.flush()
            await db.delete(app)

        await db.commit()

        if storage_keys and storage is not None:
            for key in storage_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:
                    log.debug("Could not delete resume storage object %s", key)

        return app.id, len(resumes), audit_preserved

    @staticmethod
    async def delete_resume(
            db: AsyncSession,
            user,
            resume_id: uuid.UUID,
            storage: ObjectStorage | None = None,
    ) -> tuple[uuid.UUID, int, bool]:
        """Delete a resume and its owning application (if it is the application's only resume)."""
        r = await ResumesService.get_resume(db, user, resume_id, require_edit=True)
        other_count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(Resume)
                .where(Resume.application_id == r.application_id, Resume.id != r.id)
            )
        ).scalar_one()
        if other_count == 0:
            return await ResumesService.delete_application(
                db, user, r.application_id, storage=storage
            )
        key = r.storage_key
        app_id = r.application_id
        await db.delete(r)
        await db.commit()
        if key and storage is not None:
            try:
                await asyncio.to_thread(storage.delete, key)
            except Exception:
                log.debug("Could not delete resume storage object %s", key)
        return app_id, 1, False


async def find_stuck_resume_ids(
        factory: async_sessionmaker, cfg: ResumeSettings, limit: int = 100
) -> list[uuid.UUID]:
    now = utcnow()
    cutoff = now - timedelta(seconds=cfg.stuck_after_seconds)
    async with factory() as s:
        rows = (
            await s.execute(
                sa.select(Resume.id, Resume.lease_expires_at)
                .where(
                    Resume.status.in_(["uploaded", "queued", "extracting", "analyzing"]),
                    Resume.status_updated_at < cutoff,
                )
                .limit(limit)
            )
        ).all()
    return [rid for rid, lease in rows if lease is None or as_utc(lease) <= now]
