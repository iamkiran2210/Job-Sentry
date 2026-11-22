"""
Background pipeline: claim -> extracting -> analyzing -> completed.

Idempotency/retry design:
  * A row-locked LEASE ensures only one worker runs a resume at a time (duplicate deliveries skip).
  * Each stage persists its result (source_text, then profile_data) so a retry resumes where it
    stopped instead of repeating OCR / LLM calls.
  * Finalize (candidate + application link + COMPLETED) is one transaction guarded by
    "already completed" / "application already linked" checks and a per-identity advisory lock.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import ResumeSettings
from .enums import ResumeStatus, assert_transition
from .errors import (
    SAFE_MESSAGES,
    FailureCode,
    PipelineError,
    StorageError,
    StorageObjectMissing,
)
from app.ai_features.schemas.resume_extraction import (
    SCHEMA_VERSION,
    ExtractedProfileData,
)
from .grounding import ground_profile
from .identity import (
    CandidateSnapshot,
    Signals,
    decide,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.identity_suggestion import IdentitySuggestion
from app.ai_features.models.resume import Resume
from app.modules.application_status.service import (
    ApplicationStatus,
    ApplicationStatusService,
)

from .llm import LLMProvider
from .timeutil import as_utc, utcnow
from .parsers import OcrFn, parse_document
from .storage import ObjectStorage

log = logging.getLogger("resumes.pipeline")


@dataclass
class Outcome:
    kind: Literal["completed", "failed", "retry", "skipped"]
    retry_in: int | None = None
    code: FailureCode | None = None


@dataclass
class Claim:
    resume_id: object
    company_id: object
    job_id: object
    application_id: object
    storage_key: str
    sha256: str
    content_type: str
    attempt: int


def _set_status(r: Resume, new: ResumeStatus) -> None:
    assert_transition(r.status, new.value)
    if r.status != new.value:
        r.status = new.value
        r.status_updated_at = utcnow()


async def _claim(session: AsyncSession, resume_id, cfg: ResumeSettings) -> Claim | None:
    now = utcnow()
    async with session.begin():
        r = (
            await session.execute(sa.select(Resume).where(Resume.id == resume_id).with_for_update())
        ).scalar_one_or_none()
        if r is None or r.status in (ResumeStatus.COMPLETED, ResumeStatus.FAILED):
            return None
        app = (
            await session.execute(
                sa.select(Application).where(Application.id == r.application_id).with_for_update()
            )
        ).scalar_one_or_none()
        if app is None or app.status in {
            ApplicationStatus.ANALYZED.value,
            ApplicationStatus.SHORTLISTED.value,
            ApplicationStatus.REJECTED.value,
            ApplicationStatus.WITHDRAWN.value,
        }:
            return None
        if app.status == ApplicationStatus.APPLIED.value:
            await ApplicationStatusService.transition(
                session,
                app.id,
                ApplicationStatus.PROCESSING,
                actor_type="system",
            )
        lease = as_utc(r.lease_expires_at)
        if lease and lease > now:
            return None  # another worker owns it
        r.lease_expires_at = now + timedelta(seconds=cfg.lease_seconds)
        r.attempt_count += 1
        r.started_at = r.started_at or now
        if r.status in (ResumeStatus.UPLOADED, ResumeStatus.QUEUED):
            _set_status(r, ResumeStatus.EXTRACTING)
        return Claim(
            r.id,
            r.company_id,
            r.job_id,
            r.application_id,
            r.storage_key,
            r.sha256,
            r.content_type,
            r.attempt_count,
        )


def _fetch_verified(storage: ObjectStorage, claim: Claim) -> bytes:
    try:
        data = storage.get(claim.storage_key)
    except StorageObjectMissing:
        raise PipelineError(FailureCode.STORAGE_ERROR) from None
    except StorageError:
        raise PipelineError(FailureCode.STORAGE_ERROR, retryable=True) from None
    if hashlib.sha256(data).hexdigest() != claim.sha256:
        raise PipelineError(FailureCode.INTEGRITY_ERROR)
    return data


async def _identity_lock(session: AsyncSession, company_id, key: str) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(f"{company_id}:{key}", 0))
            )
        )


async def _finalize(session: AsyncSession, claim: Claim, data: ExtractedProfileData) -> None:
    async with session.begin():
        resume = (
            await session.execute(
                sa.select(Resume).where(Resume.id == claim.resume_id).with_for_update()
            )
        ).scalar_one()
        if resume.status == ResumeStatus.COMPLETED:
            return
        app = (
            await session.execute(
                sa.select(Application)
                .where(Application.id == claim.application_id)
                .with_for_update()
            )
        ).scalar_one()
        if app.candidate_id is None:
            sig = Signals(
                normalize_name(data.full_name.value),
                normalize_email(data.contact.email.value),
                normalize_phone(data.contact.phone.value),
            )
            await _identity_lock(
                session,
                claim.company_id,
                sig.email or sig.phone or sig.name or str(claim.resume_id),
            )
            conds = [Candidate.normalized_email == sig.email] if sig.email else []
            if sig.phone:
                conds.append(Candidate.normalized_phone == sig.phone)
            if sig.name:
                conds.append(Candidate.normalized_name == sig.name)
            snapshots: list[CandidateSnapshot] = []
            if conds:
                rows = (
                    (
                        await session.execute(
                            sa.select(Candidate)
                            .where(Candidate.company_id == claim.company_id, sa.or_(*conds))
                            .limit(25)
                        )
                    )
                    .scalars()
                    .all()
                )
                applied = (
                    set(
                        (
                            await session.execute(
                                sa.select(Application.candidate_id).where(
                                    Application.job_id == claim.job_id,
                                    Application.candidate_id.in_([c.id for c in rows]),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if rows
                    else set()
                )
                snapshots = [
                    CandidateSnapshot(
                        c.id,
                        c.normalized_name,
                        c.normalized_email,
                        c.normalized_phone,
                        c.id in applied,
                    )
                    for c in rows
                ]
            decision = decide(sig, snapshots)
            if decision.action == "link_existing":
                candidate_id = decision.candidate_id
            else:
                cand = Candidate(
                    company_id=claim.company_id,
                    full_name=data.full_name.value,
                    email=data.contact.email.value,
                    phone=data.contact.phone.value,
                    normalized_name=sig.name,
                    normalized_email=sig.email,
                    normalized_phone=sig.phone,
                )
                session.add(cand)
                await session.flush()
                candidate_id = cand.id
            app.candidate_id = candidate_id
            for s in decision.suggestions:  # never merged automatically: recorded for human review
                a, b = sorted([candidate_id, s.other_candidate_id], key=str)  # canonical pair order
                exists = (
                    await session.execute(
                        sa.select(IdentitySuggestion.id).where(
                            IdentitySuggestion.candidate_id == a,
                            IdentitySuggestion.other_candidate_id == b,
                        )
                    )
                ).first()
                if not exists:
                    session.add(
                        IdentitySuggestion(
                            company_id=claim.company_id,
                            candidate_id=a,
                            other_candidate_id=b,
                            source_resume_id=claim.resume_id,
                            strength=s.strength,
                            reasons=s.reasons,
                        )
                    )
        await ApplicationStatusService.set_system_status_if_needed(
            session, app.id, ApplicationStatus.ANALYZED
        )
        _set_status(resume, ResumeStatus.COMPLETED)
        resume.completed_at = utcnow()
        resume.lease_expires_at = None
        resume.failure_code = resume.failure_message = resume.last_error_code = None


async def _fail(factory: async_sessionmaker, resume_id, code: FailureCode) -> None:
    async with factory() as s, s.begin():
        r = await s.get(Resume, resume_id)
        if r is None or r.status == ResumeStatus.COMPLETED:
            return
        _set_status(r, ResumeStatus.FAILED)
        r.failure_code, r.failure_message = code.value, SAFE_MESSAGES[code]
        r.last_error_code = code.value
        r.lease_expires_at = None
        application = (
            await s.execute(
                sa.select(Application).where(Application.id == r.application_id).with_for_update()
            )
        ).scalar_one_or_none()
        if application and application.status == ApplicationStatus.PROCESSING.value:
            await ApplicationStatusService.transition(
                s,
                application.id,
                ApplicationStatus.APPLIED,
                actor_type="system",
            )


async def _release_for_retry(factory: async_sessionmaker, resume_id, code: FailureCode) -> None:
    async with factory() as s, s.begin():
        r = await s.get(Resume, resume_id)
        if r is not None:
            r.last_error_code, r.lease_expires_at = code.value, None


async def _run_stages(
        factory: async_sessionmaker, claim: Claim, storage, llm, cfg, ocr: OcrFn | None
) -> None:
    async with factory() as s:
        prof = (
            await s.execute(
                sa.select(ExtractedProfile).where(ExtractedProfile.resume_id == claim.resume_id)
            )
        ).scalar_one_or_none()
        text = prof.source_text if prof else None
        have_data = bool(prof and prof.profile_data)

    if not text:  # ---- stage 1: extract text (skipped on retry if already done)
        data = await asyncio.to_thread(_fetch_verified, storage, claim)
        parsed = await asyncio.to_thread(parse_document, data, claim.content_type, cfg, ocr)
        text = parsed.text
        async with factory() as s, s.begin():
            prof = (
                await s.execute(
                    sa.select(ExtractedProfile).where(ExtractedProfile.resume_id == claim.resume_id)
                )
            ).scalar_one_or_none()
            if prof is None:
                prof = ExtractedProfile(resume_id=claim.resume_id, company_id=claim.company_id)
                s.add(prof)
            prof.source_text, prof.extraction_method = text, parsed.method
            prof.page_count, prof.ocr_used, prof.ocr_confidence = (
                parsed.page_count,
                parsed.ocr_used,
                parsed.ocr_confidence,
            )
            prof.parse_warnings = parsed.warnings
            r = await s.get(Resume, claim.resume_id)
            _set_status(r, ResumeStatus.ANALYZING)
    else:
        async with factory() as s, s.begin():
            r = await s.get(Resume, claim.resume_id)
            if r.status == ResumeStatus.EXTRACTING:
                _set_status(r, ResumeStatus.ANALYZING)

    if not have_data:  # ---- stage 2: LLM extraction + validation + grounding
        result = await llm.extract_profile(resume_text=text)
        try:
            validated = ExtractedProfileData.model_validate(result.data)
        except ValidationError:
            raise PipelineError(FailureCode.LLM_INVALID_OUTPUT, retryable=True) from None
        validated, warnings = ground_profile(validated, text)
        confs = validated.all_confidences()
        async with factory() as s, s.begin():
            prof = (
                await s.execute(
                    sa.select(ExtractedProfile).where(ExtractedProfile.resume_id == claim.resume_id)
                )
            ).scalar_one()
            prof.profile_data = validated.model_dump(mode="json")
            prof.extraction_warnings = warnings
            prof.overall_confidence = round(sum(confs) / len(confs), 3) if confs else None
            prof.ai_engine, prof.ai_model = result.provider, result.model
            prof.prompt_version, prof.schema_version = (
                result.prompt_version,
                SCHEMA_VERSION,
            )
    else:
        validated = ExtractedProfileData.model_validate(prof.profile_data)

    async with factory() as s:  # ---- stage 3: identity + completion (atomic)
        await _finalize(s, claim, validated)


def backoff_seconds(attempt: int, cfg: ResumeSettings) -> int:
    return max(
        1,
        int(
            min(900, cfg.task_retry_base_seconds * 2 ** max(attempt - 1, 0))
            * random.uniform(0.8, 1.2)
        ),
    )


async def process_resume(
        resume_id,
        *,
        session_factory: async_sessionmaker,
        storage: ObjectStorage,
        llm: LLMProvider,
        cfg: ResumeSettings,
        ocr: OcrFn | None = None,
) -> Outcome:
    async with session_factory() as s:
        claim = await _claim(s, resume_id, cfg)
    if claim is None:
        return Outcome("skipped")
    try:
        await _run_stages(session_factory, claim, storage, llm, cfg, ocr)
        return Outcome("completed")
    except PipelineError as exc:
        code, retryable = exc.code, exc.retryable
    except Exception as exc:  # unexpected: log the TYPE only (messages can contain resume text)
        log.error(
            "pipeline error resume=%s type=%s",
            claim.resume_id,
            type(exc).__name__,
            exc_info=cfg.log_tracebacks,
        )
        code, retryable = FailureCode.INTERNAL_ERROR, True

    if retryable and claim.attempt < cfg.task_max_attempts:
        await _release_for_retry(session_factory, claim.resume_id, code)
        return Outcome("retry", backoff_seconds(claim.attempt, cfg), code)
    await _fail(session_factory, claim.resume_id, code)
    log.warning(
        "resume failed resume=%s code=%s attempts=%s",
        claim.resume_id,
        code.value,
        claim.attempt,
    )
    return Outcome("failed", code=code)
