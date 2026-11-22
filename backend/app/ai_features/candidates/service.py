from __future__ import annotations

import asyncio
import logging
import uuid
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.identity_suggestion import IdentitySuggestion
from app.ai_features.models.resume import Resume
from app.ai_features._compat import get_accessible_job, is_access_denied
from app.ai_features.resumes.identity import normalize_email, normalize_name, normalize_phone
from app.ai_features.resumes.presenters import profile_out
from app.ai_features.resumes.service import NotFound
from app.ai_features.resumes.storage import get_storage
from app.ai_features.schemas.resume import (
    ApplicantCandidateBrief,
    ApplicantStatus,
    CandidateUpdateIn,
    JobApplicantOut,
)
from app.ai_features.schemas.resume_extraction import ExtractedProfileData

logger = logging.getLogger(__name__)


class CandidatesService:
    @staticmethod
    async def get_candidate_bundle(db: AsyncSession, user, candidate_id):
        """Company members see everything about their company's candidates. A user with only job-level grants
        sees the candidate ONLY through the jobs they can access: other applications, profiles from other jobs'
        resumes and identity-review hints (which point at other candidates) are withheld."""
        cand = await db.get(Candidate, candidate_id)
        if cand is None:
            raise NotFound
        rows = (
            await db.execute(
                sa.select(Application, Resume)
                .join(Resume, Resume.application_id == Application.id)
                .where(Application.candidate_id == cand.id)
                .order_by(Application.created_at)
            )
        ).all()
        is_member = user.company_id is not None and user.company_id == cand.company_id
        if not is_member:
            visible, allowed = [], {}
            for app, resume in rows:
                if app.job_id not in allowed:
                    try:
                        await get_accessible_job(db, user, app.job_id)
                        allowed[app.job_id] = True
                    except Exception as exc:  # noqa: BLE001
                        if not is_access_denied(exc):
                            raise
                        allowed[app.job_id] = False
                if allowed[app.job_id]:
                    visible.append((app, resume))
            if not visible:
                raise NotFound
            rows = visible
        resume_ids = [r.id for _, r in rows]
        profile = (
            (
                await db.execute(
                    sa.select(ExtractedProfile)
                    .where(
                        ExtractedProfile.resume_id.in_(resume_ids),
                        ExtractedProfile.profile_data.is_not(None),
                    )
                    .order_by(ExtractedProfile.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if resume_ids
            else None
        )
        sugg = []
        if is_member:
            sugg = (
                (
                    await db.execute(
                        sa.select(IdentitySuggestion).where(
                            sa.or_(
                                IdentitySuggestion.candidate_id == cand.id,
                                IdentitySuggestion.other_candidate_id == cand.id,
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        return cand, rows, profile, list(sugg)

    @staticmethod
    async def update_candidate(
            db: AsyncSession,
            user,
            candidate_id: uuid.UUID,
            payload: CandidateUpdateIn,
    ):
        """Manually update a candidate's identity and latest extracted profile details."""
        cand = await db.get(Candidate, candidate_id)
        if cand is None or user.company_id is None or user.company_id != cand.company_id:
            raise NotFound

        fields_set = payload.model_fields_set
        clean_str = lambda v: (v.strip() or None) if isinstance(v, str) else None

        if "full_name" in fields_set:
            val = clean_str(payload.full_name)
            cand.full_name = val
            cand.normalized_name = normalize_name(val)
        if "email" in fields_set:
            val = clean_str(payload.email)
            cand.email = val
            cand.normalized_email = normalize_email(val)
        if "phone" in fields_set:
            val = clean_str(payload.phone)
            cand.phone = val
            cand.normalized_phone = normalize_phone(val)

        # Propagate manual updates to the candidate's latest ExtractedProfile so analysis & ranking stay in sync
        resume_ids = list(
            (
                await db.execute(
                    sa.select(Resume.id)
                    .join(Application, Application.id == Resume.application_id)
                    .where(Application.candidate_id == cand.id)
                    .order_by(Resume.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        profile_row = None
        if resume_ids:
            profile_row = (
                await db.execute(
                    sa.select(ExtractedProfile)
                    .where(ExtractedProfile.resume_id.in_(resume_ids))
                    .order_by(ExtractedProfile.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if profile_row is None:
                profile_row = ExtractedProfile(
                    resume_id=resume_ids[0],
                    company_id=cand.company_id,
                    extraction_method="manual_edit",
                    profile_data={},
                )
                db.add(profile_row)
                await db.flush()

        if profile_row is not None:
            data = dict(profile_row.profile_data or {})
            contact = dict(data.get("contact") or {}) if isinstance(data.get("contact"), dict) else {}

            def _manual_sourced(val: str | None) -> dict:
                return {"value": val, "confidence": 1.0 if val else None, "evidence": "manual_edit" if val else None}

            if "full_name" in fields_set:
                data["full_name"] = _manual_sourced(cand.full_name)
            if "email" in fields_set:
                contact["email"] = _manual_sourced(cand.email)
            if "phone" in fields_set:
                contact["phone"] = _manual_sourced(cand.phone)
            for contact_field in ("location", "linkedin_url", "github_url", "portfolio_url"):
                if contact_field in fields_set:
                    contact[contact_field] = _manual_sourced(clean_str(getattr(payload, contact_field)))
            data["contact"] = contact

            if "summary" in fields_set:
                data["summary"] = clean_str(payload.summary)
            if "skills" in fields_set and payload.skills is not None:
                seen: set[str] = set()
                clean_skills = []
                for s in payload.skills:
                    trimmed = str(s).strip()
                    if trimmed and trimmed.casefold() not in seen:
                        seen.add(trimmed.casefold())
                        clean_skills.append({"name": trimmed, "confidence": 1.0, "evidence": "manual_edit"})
                data["skills"] = clean_skills
            for section in ("employment", "education", "projects", "certifications"):
                if section in fields_set and getattr(payload, section) is not None:
                    data[section] = getattr(payload, section)

            validated = ExtractedProfileData.model_validate(data)
            profile_row.profile_data = validated.model_dump(mode="json")

        await db.commit()
        return await CandidatesService.get_candidate_bundle(db, user, candidate_id)

    @staticmethod
    async def delete_candidate(db: AsyncSession, user, candidate_id: uuid.UUID) -> int:
        """Delete a candidate while preserving append-only ranking/status audit tables."""
        from app.modules.application_status.models import ApplicationStatusHistory
        from app.modules.candidate_intelligence.models import RankingHistory

        cand = await db.get(Candidate, candidate_id)
        if cand is None or user.company_id is None or user.company_id != cand.company_id:
            raise NotFound

        apps = list(
            (
                await db.execute(
                    sa.select(Application).where(
                        Application.candidate_id == cand.id,
                        Application.company_id == cand.company_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        app_ids = [a.id for a in apps]
        storage_keys: list[str] = []
        if app_ids:
            resumes = list(
                (
                    await db.execute(sa.select(Resume).where(Resume.application_id.in_(app_ids)))
                )
                .scalars()
                .all()
            )
            storage_keys = [r.storage_key for r in resumes if r.storage_key]

            # Applications referenced by append-only audit tables cannot be hard-deleted (DB trigger);
            # unlink candidate, remove resumes/extracted profiles, and mark withdrawn.
            audited_ids = set(
                (
                    await db.execute(
                        sa.select(RankingHistory.application_id).where(
                            RankingHistory.application_id.in_(app_ids)
                        )
                    )
                )
                .scalars()
                .all()
            ) | set(
                (
                    await db.execute(
                        sa.select(ApplicationStatusHistory.application_id).where(
                            ApplicationStatusHistory.application_id.in_(app_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )

            for app in apps:
                if app.id in audited_ids:
                    app.candidate_id = None
                    app.status = "withdrawn"
                    await db.execute(sa.delete(Resume).where(Resume.application_id == app.id))
                else:
                    await db.delete(app)

        await db.execute(
            sa.delete(IdentitySuggestion).where(
                sa.or_(
                    IdentitySuggestion.candidate_id == cand.id,
                    IdentitySuggestion.other_candidate_id == cand.id,
                )
            )
        )
        await db.delete(cand)
        await db.commit()

        if storage_keys:
            storage = get_storage()
            for key in storage_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:
                    logger.debug("Could not delete resume storage object %s", key)

        return len(apps)

    @staticmethod
    async def purge_candidate(
            db: AsyncSession, user, candidate_id: uuid.UUID
    ) -> dict[str, int]:
        """Clean-delete a candidate along with ALL resumes, applications, scores, verifications, and history.

        Intended exclusively for Data Explorer administrative clean-delete actions.
        Uses a transaction-local PostgreSQL GUC (`job_sentry.allow_candidate_purge = 'on'`) so
        append-only triggers remain active for every other transaction and all UPDATE operations.
        """
        from app.modules.application_status.models import ApplicationStatusHistory
        from app.modules.candidate_intelligence.models import (
            CandidateScore,
            RankingHistory,
            ScoreEvidenceRecord,
            ScoreExplanation,
            VerificationResult,
        )

        cand = await db.get(Candidate, candidate_id)
        if cand is None or user.company_id is None or user.company_id != cand.company_id:
            raise NotFound

        apps = list(
            (
                await db.execute(
                    sa.select(Application).where(
                        Application.candidate_id == cand.id,
                        Application.company_id == cand.company_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        app_ids = [a.id for a in apps]
        storage_keys: list[str] = []
        counts = {
            "applications_cleaned": len(app_ids),
            "resumes_deleted": 0,
            "scores_deleted": 0,
            "verifications_deleted": 0,
            "audit_records_deleted": 0,
        }

        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
        if is_pg:
            await db.execute(
                sa.text("SELECT set_config('job_sentry.allow_candidate_purge', 'on', true)")
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
            counts["resumes_deleted"] = len(resumes)

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
            counts["scores_deleted"] = len(score_ids)

            rh_res = await db.execute(
                sa.delete(RankingHistory).where(RankingHistory.application_id.in_(app_ids))
            )
            sh_res = await db.execute(
                sa.delete(ApplicationStatusHistory).where(
                    ApplicationStatusHistory.application_id.in_(app_ids)
                )
            )
            counts["audit_records_deleted"] = (rh_res.rowcount or 0) + (sh_res.rowcount or 0)

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
            ver_res = await db.execute(
                sa.delete(VerificationResult).where(
                    VerificationResult.application_id.in_(app_ids)
                )
            )
            counts["verifications_deleted"] = ver_res.rowcount or 0

            if resume_ids:
                await db.execute(
                    sa.delete(ExtractedProfile).where(
                        ExtractedProfile.resume_id.in_(resume_ids)
                    )
                )
            for r in resumes:
                await db.delete(r)
            await db.flush()
            for app in apps:
                await db.delete(app)
            await db.flush()

        await db.execute(
            sa.delete(IdentitySuggestion).where(
                sa.or_(
                    IdentitySuggestion.candidate_id == cand.id,
                    IdentitySuggestion.other_candidate_id == cand.id,
                )
            )
        )
        await db.delete(cand)
        await db.commit()

        if storage_keys:
            storage = get_storage()
            for key in storage_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:
                    logger.debug("Could not delete resume storage object %s", key)

        return counts

    @staticmethod
    async def purge_all_candidates(db: AsyncSession, user) -> dict[str, int]:
        """Data Explorer clean delete: permanently purge ALL candidates, applications, resumes, and details for the company."""
        from app.modules.application_status.models import ApplicationStatusHistory
        from app.modules.candidate_intelligence.models import (
            CandidateScore,
            RankingHistory,
            ScoreEvidenceRecord,
            ScoreExplanation,
            VerificationResult,
        )

        if user.company_id is None:
            raise NotFound

        company_id = user.company_id
        cands = list(
            (
                await db.execute(sa.select(Candidate).where(Candidate.company_id == company_id))
            )
            .scalars()
            .all()
        )
        apps = list(
            (
                await db.execute(sa.select(Application).where(Application.company_id == company_id))
            )
            .scalars()
            .all()
        )
        app_ids = [a.id for a in apps]
        storage_keys: list[str] = []
        counts = {
            "candidates_deleted": len(cands),
            "applications_cleaned": len(app_ids),
            "resumes_deleted": 0,
            "scores_deleted": 0,
            "verifications_deleted": 0,
            "audit_records_deleted": 0,
        }

        if not cands and not apps:
            return counts

        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
        if is_pg:
            await db.execute(
                sa.text("SELECT set_config('job_sentry.allow_candidate_purge', 'on', true)")
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
            counts["resumes_deleted"] = len(resumes)

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
            counts["scores_deleted"] = len(score_ids)

            rh_res = await db.execute(
                sa.delete(RankingHistory).where(RankingHistory.application_id.in_(app_ids))
            )
            sh_res = await db.execute(
                sa.delete(ApplicationStatusHistory).where(
                    ApplicationStatusHistory.application_id.in_(app_ids)
                )
            )
            counts["audit_records_deleted"] = (rh_res.rowcount or 0) + (sh_res.rowcount or 0)

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
            ver_res = await db.execute(
                sa.delete(VerificationResult).where(
                    VerificationResult.application_id.in_(app_ids)
                )
            )
            counts["verifications_deleted"] = ver_res.rowcount or 0

            if resume_ids:
                await db.execute(
                    sa.delete(ExtractedProfile).where(
                        ExtractedProfile.resume_id.in_(resume_ids)
                    )
                )
            for r in resumes:
                await db.delete(r)
            await db.flush()
            for app in apps:
                await db.delete(app)
            await db.flush()

        await db.execute(
            sa.delete(IdentitySuggestion).where(IdentitySuggestion.company_id == company_id)
        )
        for cand in cands:
            await db.delete(cand)
        await db.commit()

        if storage_keys:
            storage = get_storage()
            for key in storage_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:
                    logger.debug("Could not delete resume storage object %s", key)

        return counts

    @staticmethod
    async def list_job_applicants(
            db: AsyncSession,
            user,
            job_id: uuid.UUID,
            status: ApplicantStatus | str | None = None,
    ) -> list[JobApplicantOut]:
        """List applicants for a specific job.

        RBAC: User must have read access to the job (company member or explicit job viewer/editor grant).
        If user has no access, raises standard not found error (preventing job existence probing).
        """
        # 1. RBAC check via get_accessible_job
        job = await get_accessible_job(db, user, job_id, require_edit=False)

        # 2. Fetch applications for the job
        query = (
            sa.select(Application, Candidate)
            .outerjoin(Candidate, Candidate.id == Application.candidate_id)
            .where(Application.job_id == job.id)
            .order_by(Application.created_at.desc())
        )
        if status:
            query = query.where(Application.status == status)

        app_rows = (await db.execute(query)).all()
        if not app_rows:
            return []

        # 3. Fetch resumes for these applications
        app_ids = [app.id for app, _ in app_rows]
        resumes = (
            (
                await db.execute(
                    sa.select(Resume)
                    .where(Resume.application_id.in_(app_ids))
                    .order_by(Resume.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        resumes_by_app_id: dict[uuid.UUID, list[Resume]] = {}
        for r in resumes:
            resumes_by_app_id.setdefault(r.application_id, []).append(r)

        # 4. Fetch extracted profiles for latest resumes
        latest_resume_ids = [r_list[0].id for r_list in resumes_by_app_id.values() if r_list]
        profiles_by_resume_id: dict[uuid.UUID, ExtractedProfile] = {}
        if latest_resume_ids:
            profs = (
                (
                    await db.execute(
                        sa.select(ExtractedProfile).where(
                            ExtractedProfile.resume_id.in_(latest_resume_ids),
                            ExtractedProfile.profile_data.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            profiles_by_resume_id = {p.resume_id: p for p in profs}

        # 5. Format results
        applicants: list[JobApplicantOut] = []
        for app, cand in app_rows:
            r_list = resumes_by_app_id.get(app.id, [])
            latest_resume = r_list[0] if r_list else None
            # Hide deleted-candidate audit tombstones (candidate deleted & resumes purged)
            if cand is None and latest_resume is None and app.status == "withdrawn":
                continue
            profile = profiles_by_resume_id.get(latest_resume.id) if latest_resume else None

            full_name = cand.full_name if cand else None
            email = cand.email if cand else None
            phone = cand.phone if cand else None

            if profile and profile.profile_data:
                data = profile.profile_data
                if not full_name and isinstance(data.get("full_name"), dict):
                    full_name = data["full_name"].get("value")
                if not email and isinstance(data.get("contact"), dict):
                    email = data["contact"].get("email", {}).get("value")
                if not phone and isinstance(data.get("contact"), dict):
                    phone = data["contact"].get("phone", {}).get("value")

            cand_brief = (
                ApplicantCandidateBrief(
                    id=cand.id,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                )
                if cand
                else None
            )

            latest_profile_out = (
                profile_out(profile) if (profile and profile.profile_data) else None
            )

            applicants.append(
                JobApplicantOut(
                    id=app.id,
                    application_id=app.id,
                    job_id=app.job_id,
                    status=app.status,
                    created_at=app.created_at,
                    candidate_id=cand.id if cand else None,
                    candidate=cand_brief,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    resume_id=latest_resume.id if latest_resume else None,
                    resume_status=latest_resume.status if latest_resume else None,
                    original_filename=latest_resume.original_filename if latest_resume else None,
                    overall_confidence=profile.overall_confidence if profile else None,
                    latest_profile=latest_profile_out,
                )
            )

        return applicants
