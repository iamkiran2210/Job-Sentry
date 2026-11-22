from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.core.exceptions import NotFoundException
from app.models.job import Job
from app.models.job_requirement import JobRequirement
from app.modules.application_status.models import ApplicationStatusHistory
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.evidence.matchers import (
    exact_skill_evidence,
    llm_relevance_evidence,
    resume_context_skill_evidence,
    semantic_evidence,
)
from app.modules.candidate_intelligence.evidence.providers import (
    build_embedding_provider,
    build_llm_analyzer,
    _extract_tokens,
    _tokens_match,
)
from app.modules.candidate_intelligence.models import (
    CandidateScore,
    RankingHistory,
    RankingRun,
    ScoreEvidenceRecord,
    ScoreExplanation,
    VerificationResult,
)
from app.modules.candidate_intelligence.notifications import send_candidate_notification
from app.modules.candidate_intelligence.ranking.decision_agents import (
    deterministic_candidate_decisions,
    evaluate_candidate_decisions,
    list_decision_agents,
    normalize_agent_id,
)
from app.modules.candidate_intelligence.ranking.service import rank_rows
from app.modules.candidate_intelligence.scoring import category_formulas as formulas
from app.modules.candidate_intelligence.types import (
    ScoreEvidence,
    ScoringInputs,
    VerificationResultData,
)
from app.modules.candidate_intelligence.verification.checks import (
    completeness_check,
    compute_fraud_risk_summary,
    content_authenticity_check,
    duplicate_signals,
    email_check,
    email_domain_check,
    github_url_check,
    phone_check,
    portfolio_url_check,
    timeline_check,
    url_reachability_check,
)
from app.modules.candidate_intelligence.verification.checks import overall_status
from app.modules.candidate_intelligence.verification.external_profiles import (
    verify_github_profile,
    verify_linkedin_profile,
    verify_portfolio_ai,
)
from app.modules.candidate_intelligence.verification.project_links import (
    _normalize_project_url,
    verify_project_links,
)
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def _json(value):
    def plain(item):
        if isinstance(item, Mapping):
            return {str(key): plain(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [plain(nested) for nested in item]
        if isinstance(item, (date, Decimal)):
            return str(item)
        return item

    return json.loads(json.dumps(plain(value), sort_keys=True, default=str))


def _profile_detail(profile: dict) -> dict:
    """Expose only job-relevant structured claims; identity and protected fields are excluded."""
    allowed = {
        "skills": ("name", "evidence"),
        "employment": (
            "company",
            "title",
            "start_date",
            "end_date",
            "is_current",
            "description",
            "highlights",
        ),
        "education": ("institution", "degree", "field_of_study", "start_date", "end_date"),
        "projects": ("name", "description", "role", "technologies", "url"),
        "certifications": ("name", "issuer", "issue_date", "expiry_date", "credential_id"),
    }
    result = {}
    for section, fields in allowed.items():
        entries = profile.get(section)
        if isinstance(entries, list):
            result[section] = [
                {field: item[field] for field in fields if field in item}
                for item in entries
                if isinstance(item, dict)
            ]
        else:
            result[section] = []
    return result


def _mask_email(value: str | None) -> str | None:
    if not value:
        return None
    local, separator, domain = value.partition("@")
    return f"{local[:1]}***@{domain}" if separator else "***"


def _mask_phone(value: str | None) -> str | None:
    return f"***{value[-4:]}" if value else None


def _mask_verification_details(details: dict | None) -> dict:
    """Keep verification metadata useful without returning contact values."""
    masked = dict(details or {})
    for key, value in tuple(masked.items()):
        if not isinstance(value, str):
            continue
        lowered = key.casefold()
        if "email" in lowered and "@" in value:
            masked[key] = _mask_email(value)
        elif "phone" in lowered or "e164" in lowered:
            masked[key] = _mask_phone(value)
    return masked


def deterministic_score_summary(
        row: CandidateScore | None, evidence_rows: list[ScoreEvidenceRecord]
) -> list[str]:
    """Summarize persisted score fields only; does not invoke a model or re-score inputs."""
    if row is None:
        return []
    counts: dict[str, int] = {}
    for evidence in evidence_rows:
        requirement = evidence.requirement_term or evidence.canonical_term or "unassigned"
        key = f"{evidence.category}:{requirement}"
        counts[key] = counts.get(key, 0) + 1
    summaries = []
    for category, detail in sorted((row.category_detail or {}).items()):
        match = detail.get("match")
        status = detail.get("status", "unknown")
        count = sum(value for key, value in counts.items() if key.startswith(f"{category}:"))
        summaries.append(
            f"{category}: match {match if match is not None else 'unknown'} ({status}); {count} evidence items."
        )
    mandatory = [
        str(item.get("requirement_name") or item.get("requirement_id") or "requirement")
        for item in row.mandatory_results or []
        if item.get("status") in {"not_met", "unknown"}
    ]
    if mandatory:
        summaries.append("Mandatory requirements not met or unknown: " + ", ".join(mandatory) + ".")
    if row.review_signals:
        summaries.append("Review signals: " + ", ".join(row.review_signals) + ".")
    return summaries


_EDUCATION_LEVEL_MAP: dict[str, int] = {
    "none": 0,
    "high_school": 1,
    "high school": 1,
    "associate": 2,
    "bachelor": 3,
    "b.tech": 3,
    "be": 3,
    "bsc": 3,
    "bs": 3,
    "ba": 3,
    "master": 4,
    "m.tech": 4,
    "ms": 4,
    "msc": 4,
    "mba": 4,
    "doctorate": 5,
    "phd": 5,
}

_YEARS_RE = re.compile(
    r"(?:^|\b)(\d+(?:\.\d+)?)\s*(?:\+|plus|-\s*\d+(?:\.\d+)?)?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)


def _parse_required_years(text: str) -> Decimal | None:
    if not text:
        return None
    m = _YEARS_RE.search(text)
    if m:
        try:
            val = Decimal(m.group(1))
            if val > 0:
                return val
        except Exception:
            pass
    first = text.strip().split()[0] if text.strip() else ""
    first_clean = first.rstrip("+")
    try:
        val = Decimal(first_clean)
        if val > 0:
            return val
    except Exception:
        pass
    return None


def build_scoring_inputs(
        application,
        job,
        as_of: date,
        profile_data: dict | None = None,
        requirements: list | None = None,
) -> ScoringInputs:
    """Build the scorer's allowlist DTO; identity/contact/proxy keys are never copied."""
    profile_data = profile_data or {}
    requirements = requirements or []
    allowed_fields = {
        "skills": {"id", "name", "evidence", "section"},
        "employment": {
            "id",
            "title",
            "start_date",
            "end_date",
            "is_current",
            "description",
            "highlights",
            "claimed_years",
        },
        "projects": {"id", "name", "role", "description", "technologies"},
        "education": {"id", "degree", "field", "field_of_study"},
        "certifications": {"id", "name", "expiry_date"},
    }
    claim_sets = {}
    for key, fields in allowed_fields.items():
        values = []
        raw_items = list(profile_data.get(key) or [])
        if key == "employment":
            has_dated = any(isinstance(it, dict) and it.get("start_date") for it in raw_items)
            if not raw_items or not has_dated:
                for claim in profile_data.get("experience_claims") or []:
                    if not isinstance(claim, dict):
                        continue
                    stmt = claim.get("statement")
                    area = claim.get("area")
                    yrs = claim.get("years")
                    if stmt or yrs is not None:
                        synth = {
                            "title": str(area) if area else "Stated experience",
                            "description": str(stmt) if stmt else "",
                        }
                        if yrs is not None:
                            synth["claimed_years"] = yrs
                        raw_items.append(synth)
        clean_items = []
        for item in raw_items:
            if isinstance(item, dict):
                clean = {field: item[field] for field in fields if field in item}
            elif key == "skills" and isinstance(item, str):
                clean = {"name": item}
            else:
                continue
            clean_items.append(clean)
        clean_items.sort(
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
        )
        for clean in clean_items:
            if not clean.get("id"):
                digest = hashlib.sha256(
                    json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode()
                ).hexdigest()[:16]
                clean["id"] = f"{key}-{digest}"
            values.append(clean)
        claim_sets[key] = tuple(values)
    reqs = tuple(
        {
            "id": str(r.id),
            "category": str(r.category.value if hasattr(r.category, "value") else r.category),
            "name": r.name,
            "requirement_type": str(
                r.requirement_type.value
                if hasattr(r.requirement_type, "value")
                else r.requirement_type
            ),
            "is_mandatory": r.is_mandatory,
            **({"weight": float(r.weight)} if getattr(r, "weight", None) is not None else {}),
        }
        for r in sorted(requirements, key=lambda x: str(x.id))
    )
    return ScoringInputs(
        claim_sets["skills"],
        claim_sets["employment"],
        claim_sets["projects"],
        claim_sets["education"],
        claim_sets["certifications"],
        reqs,
        as_of,
    )


def evidence_to_category_inputs(evidence_rows, inputs: ScoringInputs):
    """Adapt collected evidence into pure-formula arguments without doing score math."""
    reqs = list(inputs.requirements)
    by_name = {}
    for requirement in reqs:
        by_name.setdefault(str(requirement.get("name", "")).casefold(), []).append(requirement)
    skill_credits = {}
    relevance = {"experience": {}, "projects": {}}
    for row in sorted(
            evidence_rows,
            key=lambda e: (str(getattr(e, "category", "")), str(getattr(e, "evidence_id", ""))),
    ):
        category = str(getattr(row, "category", ""))
        matched_requirements = by_name.get(str(getattr(row, "requirement_term", "")).casefold(), [])
        location = str(getattr(row, "source_location", "") or "")
        if (
                category == "skills"
                and matched_requirements
                and getattr(row, "value", None) is not None
        ):
            credit = Decimal(str(row.value))
            for req in matched_requirements:
                old = skill_credits.get(req["id"])
                if old is None or credit > old[0]:
                    skill_credits[req["id"]] = (credit, str(row.evidence_id))
        elif (
                category in relevance
                and getattr(row, "signal_type", None) == "llm_relevance"
                and getattr(row, "value", None) is not None
                and ":" in location
        ):
            item_id = location.split(":", 1)[1]
            current = relevance[category].get(item_id)
            value = Decimal(str(row.value))
            if current is None or value > current[0]:
                relevance[category][item_id] = (value, str(row.evidence_id))
    for req in reqs:
        if (
                req.get("category") == "skills"
                and req["id"] not in skill_credits
                and (inputs.skills or skill_credits)
        ):
            skill_credits[req["id"]] = (Decimal(0), None)
    return {
        "skill_credits": skill_credits,
        "experience_relevance": {k: v[0] for k, v in relevance["experience"].items()},
        "project_relevance": {k: v[0] for k, v in relevance["projects"].items()},
        "evidence_ids": {k: v[1] for group in relevance.values() for k, v in group.items()},
    }


class CandidateIntelligenceService:
    @staticmethod
    async def _bundle(db: AsyncSession, application_id: uuid.UUID):
        app = (
            await db.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundException("Application not found")
        resume = (
            await db.execute(
                select(Resume)
                .where(Resume.application_id == app.id)
                .order_by(Resume.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        profile = (
            (
                await db.execute(
                    select(ExtractedProfile).where(ExtractedProfile.resume_id == resume.id).limit(1)
                )
            ).scalar_one_or_none()
            if resume
            else None
        )
        return (
            app,
            resume,
            profile,
            (profile.profile_data if profile and isinstance(profile.profile_data, dict) else {}),
        )

    @staticmethod
    async def verify(db: AsyncSession, application_id: uuid.UUID):
        app, resume, profile_row, profile = await CandidateIntelligenceService._bundle(
            db, application_id
        )
        candidate = await db.get(Candidate, app.candidate_id) if app.candidate_id else None
        contact = profile.get("contact") or {}
        email = (contact.get("email") or {}).get("value") or (candidate.email if candidate else None)
        phone = (contact.get("phone") or {}).get("value") or (candidate.phone if candidate else None)
        prior = (
            await db.execute(
                select(Application, Resume, Candidate)
                .outerjoin(Resume, Resume.application_id == Application.id)
                .outerjoin(Candidate, Candidate.id == Application.candidate_id)
                .where(Application.company_id == app.company_id, Application.id != app.id)
            )
        ).all()
        existing = []
        for other, other_resume, other_candidate in prior:
            if other_candidate is None and other_resume is None and other.status == "withdrawn":
                continue
            existing.append(
                {
                    "company_id": str(other.company_id),
                    "application_id": str(other.id),
                    "job_id": str(other.job_id),
                    "email": other_candidate.normalized_email or other_candidate.email
                    if other_candidate
                    else None,
                    "phone": other_candidate.normalized_phone or other_candidate.phone
                    if other_candidate
                    else None,
                    "resume_hash": other_resume.sha256 if other_resume else None,
                }
            )
        # Include candidate identity claims without exposing them to any score inputs.
        cfg = get_intelligence_settings()
        result_set = [
            email_check(email, cfg.email_check_enabled),
            phone_check(phone, cfg.phone_region),
            completeness_check(
                profile,
                profile_row.source_text if profile_row else None,
                cfg.completeness_review_threshold,
                cfg.completeness_fail_threshold,
            ),
            timeline_check(
                profile.get("employment") or [],
                date.today(),
                cfg.timeline_overlap_tolerance_months,
                cfg.timeline_gap_threshold_months,
            ),
            duplicate_signals(
                email,
                phone,
                resume.sha256 if resume else None,
                existing,
                str(app.company_id),
                scope=cfg.duplicate_scope,
                job_id=str(app.job_id),
                phone_region=cfg.phone_region,
            ),
            content_authenticity_check(
                profile_row.source_text if profile_row else None,
                profile,
                enabled=cfg.content_authenticity_check_enabled,
            ),
        ]
        github_url_val = _normalize_project_url((contact.get("github_url") or {}).get("value"))
        portfolio_url_val = _normalize_project_url((contact.get("portfolio_url") or {}).get("value"))
        linkedin_url_val = (contact.get("linkedin_url") or {}).get("value")
        candidate_row = await db.get(Candidate, app.candidate_id) if app.candidate_id else None
        candidate_full_name = (
            candidate_row.full_name
            if candidate_row and candidate_row.full_name
            else (
                profile.get("full_name", {}).get("value")
                if isinstance(profile.get("full_name"), dict)
                else None
            )
        )
        bright_data_key = (
            cfg.bright_data_api_key.get_secret_value()
            if cfg.bright_data_api_key is not None
            else None
        )

        async def _check_url(key: str, val: str | None, checker):
            if not val:
                return checker(val)
            return await url_reachability_check(
                val,
                cfg.reachability_timeout_seconds,
                key,
                enabled=cfg.reachability_check_enabled,
            )

        (
            email_domain_res,
            github_url_res,
            portfolio_url_res,
            project_links_res,
            github_profile_res,
            portfolio_ai_res,
            linkedin_profile_res,
        ) = await asyncio.gather(
            email_domain_check(
                email,
                enabled=cfg.email_domain_check_enabled,
                timeout=cfg.email_domain_timeout_seconds,
            ),
            _check_url("github_url", github_url_val, github_url_check),
            _check_url("portfolio_url", portfolio_url_val, portfolio_url_check),
            verify_project_links(
                profile.get("projects") or [],
                enabled=cfg.project_link_check_enabled,
                ai_enabled=cfg.project_link_ai_enabled,
                timeout=cfg.project_link_timeout_seconds,
                max_links=cfg.project_link_max_links,
            ),
            verify_github_profile(
                github_url_val,
                profile,
                enabled=cfg.github_profile_check_enabled,
                ai_enabled=cfg.project_link_ai_enabled,
                timeout=cfg.external_profile_timeout_seconds,
                max_repositories=min(cfg.github_max_repositories, 15),
            ),
            verify_portfolio_ai(
                portfolio_url_val,
                profile,
                enabled=cfg.portfolio_ai_check_enabled,
                ai_enabled=cfg.project_link_ai_enabled,
                timeout=cfg.external_profile_timeout_seconds,
            ),
            verify_linkedin_profile(
                linkedin_url_val,
                profile,
                candidate_name=candidate_full_name,
                enabled=cfg.linkedin_profile_check_enabled,
                ai_enabled=cfg.project_link_ai_enabled,
                api_key=bright_data_key,
                dataset_id=cfg.bright_data_linkedin_dataset_id,
                timeout=cfg.linkedin_profile_timeout_seconds,
            ),
        )
        result_set.extend(
            [
                email_domain_res,
                github_url_res,
                portfolio_url_res,
                project_links_res,
                github_profile_res,
                portfolio_ai_res,
                linkedin_profile_res,
            ]
        )
        for result in result_set:
            db.add(
                VerificationResult(
                    company_id=app.company_id,
                    application_id=app.id,
                    check_type=result.check_type,
                    status=result.status,
                    signal=result.signal,
                    details=result.details,
                )
            )
        await db.flush()
        return result_set

    @staticmethod
    async def analyze(db: AsyncSession, application_id: uuid.UUID, *, pii_access: bool = False):
        app, resume, profile_row, profile = await CandidateIntelligenceService._bundle(
            db, application_id
        )
        candidate = await db.get(Candidate, app.candidate_id) if app.candidate_id else None
        job = await db.get(Job, app.job_id)
        row = (
            await db.execute(
                select(CandidateScore)
                .where(CandidateScore.application_id == app.id, CandidateScore.job_id == app.job_id)
                .order_by(CandidateScore.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        verifications = (
            (
                await db.execute(
                    select(VerificationResult)
                    .where(VerificationResult.application_id == app.id)
                    .order_by(VerificationResult.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest_verifications = {}
        for verification in verifications:
            latest_verifications.setdefault(verification.check_type, verification)
        status_rows = (
            (
                await db.execute(
                    select(ApplicationStatusHistory)
                    .where(ApplicationStatusHistory.application_id == app.id)
                    .order_by(
                        ApplicationStatusHistory.created_at.desc(),
                        ApplicationStatusHistory.id.desc(),
                    )
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        evidence_rows = []
        explanation_row = None
        if row:
            evidence_rows = (
                (
                    await db.execute(
                        select(ScoreEvidenceRecord)
                        .where(ScoreEvidenceRecord.score_id == row.id)
                        .order_by(ScoreEvidenceRecord.created_at)
                    )
                )
                .scalars()
                .all()
            )
            explanation_row = (
                await db.execute(
                    select(ScoreExplanation)
                    .where(ScoreExplanation.candidate_score_id == row.id)
                    .order_by(ScoreExplanation.created_at.desc(), ScoreExplanation.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        ranking = None
        if row:
            ranking = (
                await db.execute(
                    select(RankingHistory)
                    .where(
                        RankingHistory.application_id == app.id, RankingHistory.job_id == app.job_id
                    )
                    .order_by(RankingHistory.created_at.desc(), RankingHistory.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        contact = profile.get("contact") if isinstance(profile.get("contact"), dict) else {}
        raw_email = (
            (contact.get("email") or {}).get("value")
            if isinstance(contact.get("email"), dict)
            else None
        )
        raw_phone = (
            (contact.get("phone") or {}).get("value")
            if isinstance(contact.get("phone"), dict)
            else None
        )
        email = candidate.email if candidate and candidate.email else raw_email
        phone = candidate.phone if candidate and candidate.phone else raw_phone
        full_name = candidate.full_name if candidate and candidate.full_name else None
        if not full_name and isinstance(profile.get("full_name"), dict):
            full_name = profile["full_name"].get("value")
        email_out = email if pii_access else _mask_email(email)
        phone_out = phone if pii_access else _mask_phone(phone)
        links = {}
        for key in ("portfolio_url", "github_url", "linkedin_url"):
            value = contact.get(key)
            links[key] = value.get("value") if isinstance(value, dict) else None
        candidate_detail = {
            "id": candidate.id if candidate else app.candidate_id,
            "display_name": full_name,
            "email": email_out,
            "phone": phone_out,
            "links": links,
            "profile": _profile_detail(profile),
        }
        resume_detail = None
        if resume:
            clean_name = str(resume.original_filename or "resume")
            clean_name = clean_name.replace("\\", "/").split("/")[-1]
            clean_name = (
                    "".join(char for char in clean_name if char.isprintable())[:255] or "resume"
            )
            resume_detail = {
                "file_name": clean_name,
                "content_type": resume.content_type,
                "size_bytes": resume.size_bytes,
                "page_count": profile_row.page_count if profile_row else None,
                "uploaded_at": resume.created_at.isoformat(),
                "parse_status": resume.status,
                "parser_version": profile_row.extraction_method if profile_row else None,
                "extraction_version": profile_row.schema_version if profile_row else None,
                "content_hash_prefix": (resume.sha256 or "")[:12],
                "overall_confidence": profile_row.overall_confidence if profile_row else None,
                "extraction_method": profile_row.extraction_method if profile_row else None,
                "ai_engine": profile_row.ai_engine if profile_row else None,
                "ai_model": profile_row.ai_model if profile_row else None,
                "prompt_version": profile_row.prompt_version if profile_row else None,
                "ocr_used": bool(profile_row.ocr_used) if profile_row else False,
                "ocr_confidence": profile_row.ocr_confidence if profile_row else None,
                "warnings": [
                    *(profile_row.parse_warnings or []),
                    *(profile_row.extraction_warnings or []),
                ]
                if profile_row
                else [],
            }
        checks = [
            {
                "check_type": v.check_type,
                "status": v.status,
                "signal": v.signal,
                "details": _mask_verification_details(v.details),
            }
            for v in latest_verifications.values()
        ]
        verif_data_list = [
            VerificationResultData(
                v.check_type, v.status, v.signal, _mask_verification_details(v.details)
            )
            for v in latest_verifications.values()
        ]
        verification_status = overall_status(verif_data_list)
        fraud_risk = compute_fraud_risk_summary(verif_data_list) if verif_data_list else None
        grouped_evidence: dict[str, dict[str, Any]] = {}
        for evidence in evidence_rows:
            requirement = evidence.requirement_term or evidence.canonical_term or "unassigned"
            key = f"{evidence.category}:{requirement}"
            group = grouped_evidence.setdefault(
                key, {"category": evidence.category, "requirement": requirement, "items": []}
            )
            source = evidence.evidence_data if isinstance(evidence.evidence_data, dict) else {}
            snippet = (
                    (source.get("supporting_quotes") or [None])[0]
                    or source.get("matched_term")
                    or source.get("rationale")
            )
            group["items"].append(
                {
                    "evidence_id": evidence.evidence_id,
                    "signal_type": evidence.signal_type,
                    "snippet": snippet,
                    "source_location": evidence.source_location,
                    "value": float(evidence.value) if evidence.value is not None else None,
                    "is_proof": bool(evidence.is_proof),
                    "versions": {
                        "model_version": evidence.model_version,
                        "embedding_model": evidence.embedding_model,
                        "embedding_model_version": evidence.embedding_model_version,
                        "llm_model": evidence.llm_model,
                        "prompt_version": evidence.prompt_version,
                    },
                }
            )
        score_detail = None
        if row:
            score_detail = {
                "total": float(row.score) if row.score is not None else None,
                "lower_bound": float(row.score_lower_bound)
                if row.score_lower_bound is not None
                else None,
                "upper_bound": float(row.score_upper_bound)
                if row.score_upper_bound is not None
                else None,
                "data_completeness": float(row.data_completeness),
                "eligibility": row.eligibility,
                "mandatory_results": row.mandatory_results,
                "review_signals": row.review_signals,
                "categories": row.category_detail,
                "rank": ranking.rank if ranking else None,
                "ranking_run_id": ranking.run_id if ranking else None,
            }
        history = [
            {
                "id": item.id,
                "from_status": item.from_status,
                "to_status": item.to_status,
                "actor_type": item.actor_type,
                "actor_user_id": item.actor_user_id,
                "reason": item.reason,
                "created_at": item.created_at.isoformat(),
            }
            for item in status_rows
        ]
        ranking_agent_decisions: dict[str, dict] = {}
        ranking_active_decision: dict | None = None
        if ranking and isinstance(ranking.ranked_items, list):
            for snap_item in ranking.ranked_items:
                if isinstance(snap_item, dict) and str(snap_item.get("application_id")) == str(app.id):
                    ad = snap_item.get("agent_decisions")
                    if isinstance(ad, dict) and ad:
                        ranking_agent_decisions = ad
                    if isinstance(snap_item.get("decision"), dict):
                        ranking_active_decision = snap_item["decision"]
                    break
        if row and not ranking_agent_decisions:
            raw_sk = (row.category_detail.get("skills") or {}).get("match")
            ranking_agent_decisions = deterministic_candidate_decisions(
                score=float(row.score) if row.score is not None else None,
                eligibility=row.eligibility,
                skills_score=float(raw_sk) if raw_sk is not None else None,
                data_completeness=float(row.data_completeness),
                verification_map={v.check_type: v.status for v in latest_verifications.values()},
                category_detail=row.category_detail,
                mandatory_results=row.mandatory_results,
                review_signals=row.review_signals,
            )
        if ranking_agent_decisions and ranking_active_decision is None:
            ranking_active_decision = ranking_agent_decisions.get("balanced") or next(
                iter(ranking_agent_decisions.values()), None
            )
        return {
            "application_id": str(app.id),
            "status_note": "scored" if row else "not_scored",
            "score_id": str(row.id) if row else None,
            "score": float(row.score) if row and row.score is not None else None,
            "score_percent": float(row.score) if row and row.score is not None else None,
            "score_lower_bound": float(row.score_lower_bound) if row else None,
            "score_upper_bound": float(row.score_upper_bound) if row else None,
            "data_completeness": float(row.data_completeness) if row else None,
            "mandatory_results": row.mandatory_results if row else [],
            "categories": row.category_detail if row else {},
            "eligibility": row.eligibility if row else None,
            "review_signals": row.review_signals if row else [],
            "evidence": [x.evidence_data for x in evidence_rows],
            "analysis_summary": {
                "text": "Candidate analysis is not scored yet."
                if row is None
                else "Score reflects available job-relevant evidence.",
                "interpretation": "Scores and public profile metadata are decision-support signals; they do not verify skill, employment, or identity.",
            },
            "verification": checks,
            "scoring_version": row.scoring_version if row else None,
            "algorithm_version": row.algorithm_version if row else None,
            "config_snapshot": row.config_snapshot if row else None,
            "candidate": candidate_detail,
            "resume": resume_detail,
            "application": {
                "id": app.id,
                "job_id": app.job_id,
                "job_title": job.title if job else "",
                "status": app.status,
                "status_history": history,
            },
            "verification_detail": {
                "overall_status": verification_status,
                "checks": checks,
                "fraud_risk": fraud_risk,
            },
            "score_detail": score_detail,
            "evidence_groups": list(grouped_evidence.values()),
            "explanation": {
                "deterministic_summary": deterministic_score_summary(row, evidence_rows),
                "ai_summary": explanation_row.content
                if explanation_row and explanation_row.status == "available"
                else None,
                "ai_status": explanation_row.status if explanation_row else "unavailable",
                "disclaimer": "AI-generated from the evidence above. It does not change the score and is not a hiring decision.",
            },
            "decision": ranking_active_decision,
            "agent_decisions": ranking_agent_decisions,
        }

    @staticmethod
    async def rank(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, filters: dict):
        lock_key = job_id.int & ((1 << 63) - 1)
        acquired = (await db.execute(select(func.pg_try_advisory_xact_lock(lock_key)))).scalar_one()
        if not acquired:
            raise HTTPException(
                status_code=409, detail="A ranking run is already in progress for this job"
            )
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        reqs = list(
            (
                await db.execute(
                    select(JobRequirement)
                    .where(JobRequirement.job_id == job.id)
                    .order_by(JobRequirement.id)
                )
            )
            .scalars()
            .all()
        )
        all_job_apps = list(
            (
                await db.execute(
                    select(Application)
                    .where(Application.job_id == job.id)
                    .order_by(Application.created_at, Application.id)
                )
            )
            .scalars()
            .all()
        )
        # Skip deleted-candidate audit tombstones (candidate deleted & resumes purged)
        if all_job_apps:
            tombstone_candidates = [
                a.id for a in all_job_apps if a.candidate_id is None and a.status == "withdrawn"
            ]
            if tombstone_candidates:
                with_resumes = set(
                    (
                        await db.execute(
                            select(Resume.application_id).where(
                                Resume.application_id.in_(tombstone_candidates)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                purged_ids = set(tombstone_candidates) - with_resumes
                if purged_ids:
                    all_job_apps = [a for a in all_job_apps if a.id not in purged_ids]
        requested_ids: set[uuid.UUID] | None = None
        if filters.get("application_ids") is not None:
            requested_ids = {uuid.UUID(str(value)) for value in filters["application_ids"]}
            available_ids = {app.id for app in all_job_apps}
            invalid = sorted(str(value) for value in requested_ids - available_ids)
            if invalid:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "application_ids must belong to this job",
                        "invalid_application_ids": invalid,
                    },
                )
            target_apps = [app for app in all_job_apps if app.id in requested_ids]
        else:
            target_apps = all_job_apps
        rows = []
        scores_by_app = {}
        verification_by_app = {}
        cfg = get_intelligence_settings()
        requested_version = filters.get("scoring_version")
        if requested_version is not None and requested_version != cfg.scoring_version:
            raise HTTPException(
                status_code=422, detail=f"Unknown scoring_version: {requested_version}"
            )
        scored_count = 0
        skipped_count = 0
        verified_count = 0
        force_verify = bool(filters.get("force_verify", False))
        for app in target_apps:
            score = await ScoringService.score_application(
                app.id,
                job.id,
                cfg,
                as_of=date.today(),
                db=db,
                force_rescore=bool(filters.get("force_rescore", False)),
            )
            scored_count += 1
            scores_by_app[str(app.id)] = score
            # Verify automatically once on first ranking; only re-verify if force_verify is requested.
            existing_verif = (
                await db.execute(
                    select(VerificationResult.id)
                    .where(VerificationResult.application_id == app.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_verif is None or force_verify:
                try:
                    await CandidateIntelligenceService.verify(db, app.id)
                    verified_count += 1
                except Exception as exc:
                    logger.warning(
                        "Automatic verification during ranking failed",
                        extra={"error_type": type(exc).__name__},
                    )
            from app.ai_features.ai.settings import get_ai_settings

            ai_cfg = get_ai_settings()
            if cfg.llm_provider == "pydantic_ai" or (ai_cfg.is_production and not ai_cfg.offline):
                try:
                    from app.ai_features.resumes.tasks import generate_score_explanation_task

                    generate_score_explanation_task.apply_async(args=[str(score.id)], countdown=1)
                except Exception as exc:
                    logger.warning(
                        "Could not queue score explanation",
                        extra={"error_type": type(exc).__name__},
                    )
        # When scoring specific individual(s), preserve already-scored peers in the job ranking snapshot
        # without re-scoring them so individual re-scoring updates relative ranks cleanly.
        if requested_ids is not None:
            peer_apps = [app for app in all_job_apps if app.id not in requested_ids]
            for peer in peer_apps:
                existing_score = (
                    await db.execute(
                        select(CandidateScore)
                        .where(
                            CandidateScore.application_id == peer.id,
                            CandidateScore.job_id == job.id,
                            CandidateScore.scoring_version == cfg.scoring_version,
                        )
                        .order_by(CandidateScore.created_at.desc(), CandidateScore.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing_score is not None:
                    scores_by_app[str(peer.id)] = existing_score
                    skipped_count += 1

        apps_for_ranking = [app for app in all_job_apps if str(app.id) in scores_by_app]
        active_decision_agent = normalize_agent_id(
            filters.get("decision_agent"), default=cfg.decision_agent_default
        )

        # Reuse cached agent_decisions from the latest ranking snapshot for unchanged candidates
        # (saves LLM cost & latency when re-ranking subsets or unchanged candidates).
        prev_decisions_by_app: dict[str, tuple[dict, dict]] = {}
        if not bool(filters.get("force_rescore", False)) and not force_verify:
            prev_history = (
                await db.execute(
                    select(RankingHistory)
                    .where(RankingHistory.job_id == job.id)
                    .order_by(RankingHistory.created_at.desc(), RankingHistory.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if prev_history and isinstance(prev_history.ranked_items, list):
                for prev_item in prev_history.ranked_items:
                    if (
                            isinstance(prev_item, dict)
                            and prev_item.get("application_id")
                            and isinstance(prev_item.get("agent_decisions"), dict)
                            and prev_item["agent_decisions"]
                    ):
                        prev_decisions_by_app[str(prev_item["application_id"])] = (
                            prev_item,
                            prev_item["agent_decisions"],
                        )

        decision_inputs: list[tuple[Application, CandidateScore, dict[str, str], list[dict]]] = []
        for app in apps_for_ranking:
            score = scores_by_app[str(app.id)]
            checks = (
                (
                    await db.execute(
                        select(VerificationResult)
                        .where(VerificationResult.application_id == app.id)
                        .order_by(VerificationResult.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            latest: dict[str, str] = {}
            latest_check_dicts: list[dict] = []
            for check in checks:
                if check.check_type not in latest:
                    latest[check.check_type] = check.status
                    latest_check_dicts.append(
                        {
                            "check_type": check.check_type,
                            "status": check.status,
                            "signal": check.signal,
                        }
                    )
            verification_by_app[str(app.id)] = latest
            decision_inputs.append((app, score, latest, latest_check_dicts))

        decision_sem = asyncio.Semaphore(6)
        target_id_strs = {str(a.id) for a in target_apps}

        async def _run_decision_agent(
                app: Application, score: CandidateScore, latest_map: dict[str, str], check_dicts: list[dict]
        ):
            app_id_str = str(app.id)
            cur_score = float(score.score) if score.score is not None else None
            cur_ver_sorted = sorted(latest_map.values())
            prev_pair = prev_decisions_by_app.get(app_id_str)
            if prev_pair is not None and (requested_ids is None or app_id_str not in target_id_strs):
                prev_item, prev_ads = prev_pair
                if (
                        prev_item.get("score") == cur_score
                        and prev_item.get("eligibility") == score.eligibility
                        and prev_item.get("data_completeness") == float(score.data_completeness)
                        and sorted(prev_item.get("verification_statuses") or []) == cur_ver_sorted
                ):
                    return prev_ads
            raw_skills_match = (score.category_detail.get("skills") or {}).get("match")
            async with decision_sem:
                return await evaluate_candidate_decisions(
                    job_title=job.title,
                    score=cur_score,
                    eligibility=score.eligibility,
                    skills_score=float(raw_skills_match) if raw_skills_match is not None else None,
                    data_completeness=float(score.data_completeness),
                    category_detail=score.category_detail,
                    mandatory_results=score.mandatory_results,
                    review_signals=score.review_signals,
                    verification_checks=check_dicts,
                    ai_enabled=cfg.decision_agent_ai_enabled,
                    timeout=cfg.decision_agent_timeout_seconds,
                )

        all_agent_decisions = (
            await asyncio.gather(
                *(
                    _run_decision_agent(app, score, latest_map, check_dicts)
                    for app, score, latest_map, check_dicts in decision_inputs
                )
            )
            if decision_inputs
            else []
        )

        for (app, score, latest, _), agent_decisions in zip(decision_inputs, all_agent_decisions):
            raw_skills_match = (score.category_detail.get("skills") or {}).get("match")
            rows.append(
                {
                    "application_id": str(app.id),
                    "application_created_at": app.created_at.isoformat(),
                    "score": float(score.score) if score.score is not None else None,
                    "eligibility": score.eligibility,
                    "skills_score": float(raw_skills_match)
                    if raw_skills_match is not None
                    else None,
                    "data_completeness": float(score.data_completeness),
                    "status": app.status,
                    "verification_statuses": list(latest.values()),
                    "agent_decisions": agent_decisions,
                    "decision": agent_decisions.get(active_decision_agent),
                }
            )
        min_accept_threshold = filters.get("min_accept_threshold")
        auto_apply_decisions = bool(filters.get("auto_apply_decisions", False))
        all_ranked = rank_rows(
            rows,
            offset=0,
            limit=len(rows) or 1,
            eligibility=filters.get("eligibility"),
            min_score=filters.get("min_score"),
            max_score=filters.get("max_score"),
            status=filters.get("status"),
            verification_status=filters.get("verification_status"),
            decision_agent=active_decision_agent,
            decision=filters.get("decision"),
            min_accept_threshold=min_accept_threshold,
        )
        auto_applied_count = 0
        notifications_sent = 0
        notifications_failed = 0
        notification_results: list[dict] = []
        if auto_apply_decisions and all_ranked:
            eff_threshold = (
                float(min_accept_threshold)
                if min_accept_threshold is not None
                else float(cfg.default_min_accept_threshold)
            )
            apps_by_id = {str(a.id): a for a in apps_for_ranking}
            pending_notifications: list[tuple[str, str | None, str | None, str, float | None, str | None]] = []
            for item in all_ranked:
                # When ranking specific individual(s), only auto-apply & notify the targeted applicant(s).
                if requested_ids is not None and item["application_id"] not in target_id_strs:
                    continue
                app_obj = apps_by_id.get(item["application_id"])
                dec_obj = item.get("decision") or {}
                t_outcome = dec_obj.get("threshold_outcome")
                if app_obj is None or app_obj.status == "withdrawn" or t_outcome not in {"accept", "reject"}:
                    continue
                new_status = "shortlisted" if t_outcome == "accept" else "rejected"
                status_changed = app_obj.status != new_status
                if status_changed:
                    old_status = app_obj.status
                    app_obj.status = new_status
                    item["status"] = new_status
                    score_val = item.get("score")
                    score_str = f"{round(float(score_val))}%" if score_val is not None else "N/A"
                    reason_text = (
                        f"Auto-decision by {dec_obj.get('agent_name', active_decision_agent)} "
                        f"(score {score_str} vs threshold {eff_threshold:.0f}% -> {t_outcome}): "
                        f"{dec_obj.get('summary', '')}"
                    )[:500]
                    db.add(
                        ApplicationStatusHistory(
                            application_id=app_obj.id,
                            job_id=job.id,
                            company_id=job.company_id,
                            from_status=old_status,
                            to_status=new_status,
                            actor_type="user",
                            actor_user_id=user_id,
                            reason=reason_text,
                        )
                    )
                    auto_applied_count += 1

                # Always notify when auto-apply is explicitly requested and either status changed,
                # force_rescore was requested, or specific individual(s) were targeted.
                should_notify = status_changed or bool(filters.get("force_rescore", False)) or requested_ids is not None
                if not should_notify:
                    continue

                # Resolve email & name from Candidate record OR fallback to ExtractedProfile contact
                cand = await db.get(Candidate, app_obj.candidate_id) if app_obj.candidate_id else None
                recip_email = cand.email if cand and cand.email else None
                cand_name = cand.full_name if cand and cand.full_name else None
                if not recip_email or not cand_name:
                    res_row = (
                        await db.execute(
                            select(Resume)
                            .where(Resume.application_id == app_obj.id)
                            .order_by(Resume.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    prof_row = (
                        (
                            await db.execute(
                                select(ExtractedProfile)
                                .where(ExtractedProfile.resume_id == res_row.id)
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if res_row
                        else None
                    )
                    pdata = prof_row.profile_data if prof_row and isinstance(prof_row.profile_data, dict) else {}
                    contact_map = pdata.get("contact") if isinstance(pdata.get("contact"), dict) else {}
                    if not recip_email and isinstance(contact_map.get("email"), dict):
                        recip_email = contact_map["email"].get("value")
                    if not cand_name and isinstance(pdata.get("full_name"), dict):
                        cand_name = pdata["full_name"].get("value")

                pending_notifications.append(
                    (
                        str(app_obj.id),
                        recip_email,
                        cand_name,
                        new_status,
                        item.get("score"),
                        dec_obj.get("summary"),
                    )
                )

            if pending_notifications:
                notif_outputs = await asyncio.gather(
                    *(
                        send_candidate_notification(
                            recipient_email=recip_email,
                            candidate_name=cand_name,
                            job_title=job.title,
                            outcome=new_status,
                            score=score_val,
                            feedback=summary_txt,
                        )
                        for _, recip_email, cand_name, new_status, score_val, summary_txt in pending_notifications
                    )
                )
                for (app_id_str, _, _, new_status, _, _), nres in zip(pending_notifications, notif_outputs):
                    if nres.get("delivered"):
                        notifications_sent += 1
                    elif nres.get("channel") == "smtp_failed":
                        notifications_failed += 1
                    notification_results.append(
                        {
                            "application_id": app_id_str,
                            "outcome": new_status,
                            "delivered": bool(nres.get("delivered")),
                            "channel": nres.get("channel"),
                            "reason": nres.get("reason"),
                        }
                    )
        offset, limit = filters.get("offset", 0), filters.get("limit", 50)
        page = all_ranked[offset: offset + limit]
        requirements_snapshot = [
            {
                "id": str(r.id),
                "category": str(r.category.value if hasattr(r.category, "value") else r.category),
                "name": r.name,
                "type": str(
                    r.requirement_type.value
                    if hasattr(r.requirement_type, "value")
                    else r.requirement_type
                ),
                "is_mandatory": r.is_mandatory,
                "weight": r.weight,
            }
            for r in reqs
        ]
        requirement_hash = hashlib.sha256(
            json.dumps(requirements_snapshot, sort_keys=True).encode()
        ).hexdigest()
        config_snapshot = {
            "scoring_version": cfg.scoring_version,
            "algorithm_version": cfg.algorithm_version,
            "weights": {c: getattr(cfg, f"weight_{c}") for c in formulas.CATEGORIES},
            "semantic_min": cfg.semantic_min,
            "semantic_full": cfg.semantic_full,
            "semantic_credit_cap": cfg.semantic_credit_cap,
            "low_completeness_threshold": cfg.low_completeness_threshold,
            "skill_aliases": cfg.skill_aliases,
            "relevance_scores": cfg.relevance_scores,
        }
        provider_snapshot = {
            "embedding_provider": cfg.embedding_provider,
            "embedding_model": cfg.semantic_model_name,
            "embedding_version": cfg.semantic_model_version,
            "llm_provider": cfg.llm_provider,
            "llm_model": cfg.llm_model,
            "llm_prompt_version": cfg.llm_prompt_version,
        }
        config_hash = hashlib.sha256(
            json.dumps(
                {"config": config_snapshot, "providers": provider_snapshot},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        run_id = uuid.uuid4()
        db.add(
            RankingRun(
                run_id=run_id,
                job_id=job.id,
                status="completed",
                counts={"scored": scored_count, "skipped": skipped_count, "failed": 0},
                filters_applied=_json(filters),
                scoring_version=cfg.scoring_version,
                algorithm_version=cfg.algorithm_version,
                embedding_model=cfg.semantic_model_name,
                embedding_model_version=cfg.semantic_model_version,
                llm_model=cfg.llm_model,
                prompt_version=cfg.llm_prompt_version,
                job_requirements_hash=requirement_hash,
                scoring_config_hash=config_hash,
                triggered_by=user_id,
            )
        )
        for item in all_ranked:
            score_row = scores_by_app[item["application_id"]]
            tie_key = {
                "score": item.get("score"),
                "eligibility": item.get("eligibility"),
                "skills_score": item.get("skills_score"),
                "data_completeness": item.get("data_completeness"),
                "application_created_at": item.get("application_created_at"),
                "application_id": item.get("application_id"),
            }
            verifications = item.get("verification_statuses") or []
            verification_status = next(
                (
                    status
                    for status in ("failed", "needs_review", "not_verified", "passed")
                    if status in verifications
                ),
                "not_verified",
            )
            db.add(
                RankingHistory(
                    company_id=job.company_id,
                    job_id=job.id,
                    run_id=run_id,
                    application_id=uuid.UUID(item["application_id"]),
                    candidate_score_id=score_row.id,
                    rank=item["rank"],
                    total_score=item.get("score"),
                    tie_break_key=tie_key,
                    requirements_snapshot=requirements_snapshot,
                    requirements_hash=requirement_hash,
                    ranked_items=all_ranked,
                    filters_used=_json(filters),
                    scoring_version=cfg.scoring_version,
                    algorithm_version=cfg.algorithm_version,
                    config_snapshot=config_snapshot,
                    config_hash=config_hash,
                    provider_snapshot=provider_snapshot,
                    embedding_model=cfg.semantic_model_name,
                    embedding_model_version=cfg.semantic_model_version,
                    llm_model=cfg.llm_model,
                    prompt_version=cfg.llm_prompt_version,
                    job_requirements_hash=requirement_hash,
                    scoring_config_hash=config_hash,
                    eligibility=item.get("eligibility") or "needs_review",
                    verification_status=verification_status,
                    triggered_by=user_id,
                )
            )
        if not all_ranked:
            db.add(
                RankingHistory(
                    company_id=job.company_id,
                    job_id=job.id,
                    run_id=run_id,
                    application_id=None,
                    candidate_score_id=None,
                    rank=None,
                    total_score=None,
                    tie_break_key={},
                    requirements_snapshot=requirements_snapshot,
                    requirements_hash=requirement_hash,
                    ranked_items=[],
                    filters_used=_json(filters),
                    scoring_version=cfg.scoring_version,
                    algorithm_version=cfg.algorithm_version,
                    config_snapshot=config_snapshot,
                    config_hash=config_hash,
                    provider_snapshot=provider_snapshot,
                    embedding_model=cfg.semantic_model_name,
                    embedding_model_version=cfg.semantic_model_version,
                    llm_model=cfg.llm_model,
                    prompt_version=cfg.llm_prompt_version,
                    job_requirements_hash=requirement_hash,
                    scoring_config_hash=config_hash,
                    eligibility="needs_review",
                    verification_status="not_verified",
                    triggered_by=user_id,
                )
            )
        await db.flush()
        return {
            "run_id": str(run_id),
            "count": len(page),
            "total_count": len(all_ranked),
            "offset": offset,
            "limit": limit,
            "scoring_version": cfg.scoring_version,
            "algorithm_version": cfg.algorithm_version,
            "config_hash": config_hash,
            "provider_snapshot": provider_snapshot,
            "verified_count": verified_count,
            "decision_agent": active_decision_agent,
            "min_accept_threshold": min_accept_threshold,
            "auto_applied_count": auto_applied_count,
            "notifications_sent": notifications_sent,
            "notifications_failed": notifications_failed,
            "notification_results": notification_results,
            "available_decision_agents": list_decision_agents(),
            "items": page,
        }


class ScoringService:
    """Explicit score-write entry point. Read endpoints must not call this."""

    @staticmethod
    async def score_application(
            application_id: uuid.UUID,
            job_id: uuid.UUID,
            scoring_config=None,
            as_of: date | None = None,
            db: AsyncSession | None = None,
            force_rescore: bool = False,
    ):
        if db is None:
            raise ValueError("AsyncSession is required")
        application = (
            await db.execute(
                select(Application).where(
                    Application.id == application_id, Application.job_id == job_id
                )
            )
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundException("Application not found")
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        resume = (
            await db.execute(
                select(Resume)
                .where(Resume.application_id == application_id)
                .order_by(Resume.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        profile_row = (
            (
                await db.execute(
                    select(ExtractedProfile).where(ExtractedProfile.resume_id == resume.id).limit(1)
                )
            ).scalar_one_or_none()
            if resume
            else None
        )
        profile = (
            profile_row.profile_data
            if profile_row and isinstance(profile_row.profile_data, dict)
            else {}
        )
        requirements = list(
            (
                await db.execute(
                    select(JobRequirement)
                    .where(JobRequirement.job_id == job_id)
                    .order_by(JobRequirement.id)
                )
            )
            .scalars()
            .all()
        )
        scoring_config = scoring_config or get_intelligence_settings()
        as_of = as_of or date.today()
        inputs = build_scoring_inputs(application, job, as_of, profile, requirements)
        if not force_rescore:
            existing_rows = (
                (
                    await db.execute(
                        select(CandidateScore)
                        .where(
                            CandidateScore.application_id == application_id,
                            CandidateScore.job_id == job_id,
                            CandidateScore.scoring_version == scoring_config.scoring_version,
                            CandidateScore.algorithm_version == scoring_config.algorithm_version,
                        )
                        .order_by(CandidateScore.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            serialized_inputs = _json(inputs.__dict__)
            for existing in existing_rows:
                snapshot = existing.config_snapshot or {}
                current_weights = {
                    name: str(getattr(scoring_config, f"weight_{name}"))
                    for name in formulas.CATEGORIES
                }
                config_matches = (
                    snapshot.get("scoring_version") == scoring_config.scoring_version
                    and snapshot.get("algorithm_version") == scoring_config.algorithm_version
                    and snapshot.get("weights") == current_weights
                    and snapshot.get("semantic_min") == scoring_config.semantic_min
                    and snapshot.get("semantic_full") == scoring_config.semantic_full
                    and snapshot.get("semantic_credit_cap") == scoring_config.semantic_credit_cap
                    and snapshot.get("low_completeness_threshold")
                    == str(scoring_config.low_completeness_threshold)
                    and snapshot.get("skill_aliases") == scoring_config.skill_aliases
                    and snapshot.get("relevance_scores") == scoring_config.relevance_scores
                    and snapshot.get("embedding_provider") == scoring_config.embedding_provider
                    and snapshot.get("semantic_model_name") == scoring_config.semantic_model_name
                    and snapshot.get("semantic_model_version")
                    == scoring_config.semantic_model_version
                    and snapshot.get("llm_provider") == scoring_config.llm_provider
                    and snapshot.get("llm_model") == scoring_config.llm_model
                    and snapshot.get("llm_prompt_version") == scoring_config.llm_prompt_version
                )
                if config_matches and snapshot.get("reproducibility_inputs") == serialized_inputs:
                    return existing
        evidence = await ScoringService._collect_evidence(inputs, scoring_config)
        adapted = evidence_to_category_inputs(evidence, inputs)
        reqs = list(inputs.requirements)
        cat = lambda req: {
            "certification": "certifications",
            "project": "projects",
            "responsibility": "projects",
        }.get(req["category"], req["category"])
        skills_reqs = [r for r in reqs if cat(r) == "skills"]
        cert_reqs = [r for r in reqs if cat(r) == "certifications"]
        education_reqs = [r for r in reqs if cat(r) == "education"]
        experience_reqs = [r for r in reqs if cat(r) == "experience"]
        project_weight = Decimal(str(scoring_config.weight_projects))
        weights = formulas.validate_weights(
            {
                name: getattr(scoring_config, f"weight_{name}")
                for name in ("skills", "experience", "projects", "education", "certifications")
            }
        )
        skills = formulas.score_skills(skills_reqs, adapted["skill_credits"], weights["skills"])
        required_years = None
        ordered_exp_reqs = sorted(
            experience_reqs,
            key=lambda r: (
                0 if (r.get("is_mandatory") or r.get("requirement_type") == "mandatory") else 1,
                str(r.get("id", "")),
            ),
        )
        for req in ordered_exp_reqs:
            parsed_years = _parse_required_years(str(req.get("name", "")))
            if parsed_years is not None:
                required_years = parsed_years
                break
        experience = formulas.score_experience(
            list(inputs.experience),
            adapted["experience_relevance"],
            required_years,
            as_of,
            weights["experience"],
        )
        projects = formulas.score_projects(
            list(inputs.projects), adapted["project_relevance"], project_weight
        )
        education = formulas.score_education(
            [str(x.get("degree", "")) for x in inputs.education if x.get("degree")],
            education_reqs[0]["name"] if education_reqs else None,
            _EDUCATION_LEVEL_MAP,
            weights["education"],
        )
        certifications = formulas.score_certifications(
            cert_reqs,
            list(inputs.certifications),
            scoring_config.skill_aliases,
            weights["certifications"],
            as_of,
        )
        mandatory = formulas.evaluate_mandatory(reqs, evidence)
        config_snapshot = {
            "scoring_version": scoring_config.scoring_version,
            "algorithm_version": scoring_config.algorithm_version,
            "weights": {k: str(v) for k, v in weights.items()},
            "semantic_min": scoring_config.semantic_min,
            "semantic_full": scoring_config.semantic_full,
            "semantic_credit_cap": scoring_config.semantic_credit_cap,
            "low_completeness_threshold": str(scoring_config.low_completeness_threshold),
            "skill_aliases": scoring_config.skill_aliases,
            "relevance_scores": scoring_config.relevance_scores,
            "embedding_provider": scoring_config.embedding_provider,
            "semantic_model_name": scoring_config.semantic_model_name,
            "semantic_model_version": scoring_config.semantic_model_version,
            "embedding_dimension": scoring_config.embedding_dimension,
            "llm_provider": scoring_config.llm_provider,
            "llm_model": scoring_config.llm_model,
            "llm_prompt_version": scoring_config.llm_prompt_version,
            "reproducibility_inputs": _json(inputs.__dict__),
        }
        aggregate = formulas.aggregate(
            [skills, experience, projects, education, certifications],
            list(mandatory.results),
            Decimal(str(scoring_config.low_completeness_threshold)),
        )
        input_payload = {
            "inputs": _json(inputs.__dict__),
            "config": config_snapshot,
            "evidence": sorted((e.evidence_id, e.value, e.signal_type) for e in evidence),
        }
        inputs_hash = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        category_scores = {
            r.category: {
                "status": r.status,
                "match": str(r.match) if r.match is not None else None,
                "weight": str(r.weight),
                "weighted_contribution": str(r.weighted_contribution)
                if r.weighted_contribution is not None
                else None,
                "components": _json(r.components),
                "evidence_ids": list(r.evidence_ids),
                "notes": list(r.notes),
            }
            for r in (skills, experience, projects, education, certifications)
        }
        snapshot = {
            **config_snapshot,
            "category_scores": category_scores,
            "as_of_date": as_of.isoformat(),
            "inputs_hash": inputs_hash,
        }
        if force_rescore:
            source_inputs_hash = inputs_hash
            inputs_hash = hashlib.sha256(
                f"{source_inputs_hash}:{uuid.uuid4()}".encode()
            ).hexdigest()
            snapshot["source_inputs_hash"] = source_inputs_hash
        score_row = (
            None
            if force_rescore
            else (
                await db.execute(
                    select(CandidateScore).where(
                        CandidateScore.application_id == application_id,
                        CandidateScore.job_id == job_id,
                        CandidateScore.scoring_version == scoring_config.scoring_version,
                        CandidateScore.inputs_hash == inputs_hash,
                    )
                )
            ).scalar_one_or_none()
        )
        if score_row is None:
            score_row = CandidateScore(
                company_id=application.company_id,
                application_id=application_id,
                job_id=job_id,
                scoring_version=scoring_config.scoring_version,
                algorithm_version=scoring_config.algorithm_version,
                score=aggregate.total_score,
                score_lower_bound=aggregate.score_lower_bound,
                score_upper_bound=aggregate.score_upper_bound,
                data_completeness=aggregate.data_completeness,
                mandatory_results=list(mandatory.results),
                inputs_hash=inputs_hash,
                as_of_date=as_of,
                category_detail=category_scores,
                eligibility=aggregate.eligibility,
                review_signals=list(aggregate.review_signals),
                config_snapshot=snapshot,
            )
            db.add(score_row)
            await db.flush()
        for ev in evidence:
            exists = (
                await db.execute(
                    select(ScoreEvidenceRecord).where(
                        ScoreEvidenceRecord.score_id == score_row.id,
                        ScoreEvidenceRecord.evidence_id == ev.evidence_id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    ScoreEvidenceRecord(
                        company_id=application.company_id,
                        score_id=score_row.id,
                        application_id=application_id,
                        evidence_id=ev.evidence_id,
                        category=ev.category,
                        signal_type=ev.signal_type,
                        value=ev.value,
                        evidence_data=_json(ev.__dict__),
                        source_location=ev.source_location,
                        matched_term=ev.matched_term,
                        requirement_term=ev.requirement_term,
                        canonical_term=ev.canonical_term,
                        alias_used=ev.alias_used,
                        match_type=ev.match_type,
                        compared_texts=list(ev.compared_texts) if ev.compared_texts else None,
                        model_version=ev.model_version,
                        similarity=ev.similarity,
                        rationale=ev.rationale,
                        supporting_quotes=list(ev.supporting_quotes),
                        error=ev.error,
                        model_name=ev.model_name,
                        input_hash=ev.input_hash,
                        embedding=list(ev.embedding) if ev.embedding else None,
                        embedding_model_name=ev.embedding_model,
                        embedding_model_version=ev.embedding_model_version,
                        embedding_dimension=ev.embedding_dim,
                        embedding_model=ev.embedding_model,
                        embedding_dim=ev.embedding_dim,
                        llm_model=ev.llm_model,
                        prompt_version=ev.prompt_version,
                        source_start=ev.source_start,
                        source_end=ev.source_end,
                        grounded=ev.grounded if ev.grounded is not None else False,
                        is_proof=ev.signal_type in {"exact_skill_match", "alias_skill_match"},
                    )
                )
        await db.flush()
        return score_row

    @staticmethod
    async def _collect_evidence(inputs: ScoringInputs, cfg):
        from dataclasses import replace

        evidence = []
        skill_aliases = getattr(cfg, "skill_aliases", {}) or {}
        relevance_scores = getattr(
            cfg,
            "relevance_scores",
            {"high": 1.0, "medium": 0.6, "low": 0.25, "none": 0.0},
        )
        category_name = lambda r: {
            "certification": "certifications",
            "project": "projects",
            "responsibility": "projects",
        }.get(r["category"], r["category"])

        safe_lines: list[str] = []
        for group, fields in (
                (inputs.skills, ("name", "evidence")),
                (inputs.experience, ("title", "description", "highlights")),
                (inputs.projects, ("name", "role", "description", "technologies")),
                (inputs.education, ("degree", "field", "field_of_study")),
                (inputs.certifications, ("name",)),
        ):
            for item in group:
                for field in fields:
                    value = item.get(field)
                    if not value:
                        continue
                    if isinstance(value, (list, tuple)):
                        for sub in value:
                            if sub:
                                safe_lines.append(str(sub))
                    else:
                        safe_lines.append(str(value))
        safe_resume_text = "\n".join(safe_lines)

        skill_reqs = [r["name"] for r in inputs.requirements if category_name(r) == "skills"]
        exact_hits = exact_skill_evidence(
            skill_reqs, [dict(item) for item in inputs.skills], skill_aliases
        )
        evidence.extend(exact_hits)

        matched_skill_names = {
            str(e.requirement_term).casefold() for e in exact_hits if e.requirement_term
        }
        unmatched_skill_reqs = [
            req for req in skill_reqs if req.casefold() not in matched_skill_names
        ]
        if unmatched_skill_reqs and (inputs.projects or inputs.experience):
            evidence.extend(
                resume_context_skill_evidence(
                    unmatched_skill_reqs,
                    [dict(p) for p in inputs.projects],
                    [dict(e) for e in inputs.experience],
                    skill_aliases,
                )
            )

        embedder, analyzer = build_embedding_provider(cfg), build_llm_analyzer(cfg)
        for item in inputs.skills:
            claim = str(item.get("name", ""))
            if not claim:
                continue
            for requirement in skill_reqs:
                try:
                    sem = await run_in_threadpool(
                        semantic_evidence,
                        requirement,
                        claim,
                        embedder,
                        cfg.semantic_min,
                        cfg.semantic_model_version,
                        "skills",
                        cfg.semantic_full,
                        cfg.semantic_credit_cap,
                    )
                    evidence.append(replace(sem, source_location=f"skills:{item['id']}"))
                except Exception:
                    pass

        fallback_context_reqs = [
            ", ".join(r["name"] for r in inputs.requirements if r.get("name"))
        ]
        fallback_context_reqs = [x for x in fallback_context_reqs if x.strip()]

        # Track per-requirement item relevance for grounded mandatory rule checks
        req_item_relevance: dict[tuple[str, str], dict[str, Decimal]] = {}
        llm_jobs: list[tuple[str, str, str, str]] = []

        for category, items in (("experience", inputs.experience), ("projects", inputs.projects)):
            cat_reqs = [r["name"] for r in inputs.requirements if category_name(r) == category]
            reqs = cat_reqs or fallback_context_reqs
            for item in items:
                item_id = str(item.get("id", ""))
                claim = " ".join(
                    str(v)
                    for v in (
                        item.get("title"),
                        item.get("name"),
                        item.get("role"),
                        item.get("description"),
                        " ".join(str(h) for h in (item.get("highlights") or []) if h),
                        " ".join(str(t) for t in (item.get("technologies") or []) if t),
                    )
                    if v
                )
                if not claim.strip():
                    continue
                for requirement in reqs:
                    try:
                        sem = await run_in_threadpool(
                            semantic_evidence,
                            requirement,
                            claim,
                            embedder,
                            cfg.semantic_min,
                            cfg.semantic_model_version,
                            category,
                            cfg.semantic_full,
                            cfg.semantic_credit_cap,
                        )
                        sem_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL, f"{sem.evidence_id}:{category}:{item_id}"
                            )
                        )
                        evidence.append(
                            replace(
                                sem, evidence_id=sem_id, source_location=f"{category}:{item_id}"
                            )
                        )
                    except Exception:
                        pass
                    if safe_resume_text:
                        llm_jobs.append((category, item_id, requirement, claim))

        if llm_jobs:
            sem_gate = asyncio.Semaphore(6)
            # Deduplicate identical (requirement, claim) LLM evaluations within one scoring run
            unique_pairs: dict[tuple[str, str], asyncio.Future] = {}
            loop = asyncio.get_running_loop()

            async def _eval_unique(requirement: str, claim: str, category: str):
                async with sem_gate:
                    return await llm_relevance_evidence(
                        requirement,
                        claim,
                        safe_resume_text,
                        analyzer,
                        relevance_scores,
                        category,
                    )

            async def _eval_llm(category: str, item_id: str, requirement: str, claim: str):
                key = (requirement, claim)
                fut = unique_pairs.get(key)
                if fut is None:
                    fut = loop.create_task(_eval_unique(requirement, claim, category))
                    unique_pairs[key] = fut
                base_llm = await fut
                llm_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{base_llm.evidence_id}:{category}:{item_id}")
                )
                return category, item_id, requirement, replace(
                    base_llm,
                    category=category,
                    evidence_id=llm_id,
                    source_location=f"{category}:{item_id}",
                )

            llm_results = await asyncio.gather(*(_eval_llm(*job) for job in llm_jobs))
            for category, item_id, requirement, llm_ev in llm_results:
                evidence.append(llm_ev)
                if llm_ev.value is not None:
                    bucket = req_item_relevance.setdefault((category, requirement.casefold()), {})
                    val = Decimal(str(llm_ev.value))
                    prev = bucket.get(item_id)
                    if prev is None or val > prev:
                        bucket[item_id] = val

        # Grounded rule-based evidence for non-skill requirements (used for mandatory checks & explainability)
        # 1. Experience requirements
        exp_reqs = [r for r in inputs.requirements if category_name(r) == "experience"]
        if exp_reqs and inputs.experience:
            for req in exp_reqs:
                req_name = str(req["name"])
                req_years = _parse_required_years(req_name)
                rel_map = req_item_relevance.get(("experience", req_name.casefold()), {})
                if req_years is not None and req_years > 0:
                    has_duration = any(
                        e.get("start_date") or e.get("claimed_years") is not None
                        for e in inputs.experience
                    )
                    if has_duration and rel_map:
                        rel_years = formulas.merged_relevant_years(
                            list(inputs.experience), rel_map, inputs.as_of
                        )
                        met = rel_years >= req_years
                        evidence.append(
                            ScoreEvidence(
                                evidence_id=str(
                                    uuid.uuid5(uuid.NAMESPACE_URL, f"rule:experience:{req['id']}")
                                ),
                                category="experience",
                                signal_type="rule_based_match",
                                value=1.0 if met else 0.0,
                                source_location="profile_data.employment",
                                matched_term=f"{float(rel_years):.1f} years",
                                requirement_term=req_name,
                                match_type="rule",
                                grounded=True,
                                rationale=(
                                    f"Candidate has {float(rel_years):.1f} relevant years "
                                    f"({'meets' if met else 'below'} {float(req_years):.1f} required)"
                                ),
                            )
                        )
                elif rel_map:
                    max_rel = max(rel_map.values())
                    met = max_rel >= Decimal("0.6")
                    evidence.append(
                        ScoreEvidence(
                            evidence_id=str(
                                uuid.uuid5(uuid.NAMESPACE_URL, f"rule:experience:{req['id']}")
                            ),
                            category="experience",
                            signal_type="rule_based_match",
                            value=1.0 if met else 0.0,
                            source_location="profile_data.employment",
                            matched_term=req_name if met else None,
                            requirement_term=req_name,
                            match_type="rule",
                            grounded=True,
                            rationale=(
                                "Candidate experience aligns with requirement"
                                if met
                                else "Candidate experience has low relevance to requirement"
                            ),
                        )
                    )

        # 2. Education requirements
        edu_reqs = [r for r in inputs.requirements if category_name(r) == "education"]
        if edu_reqs and inputs.education:
            cand_degrees = [
                str(x.get("degree", "")) for x in inputs.education if x.get("degree")
            ]
            resolved_cand = [
                (deg, lvl)
                for deg in cand_degrees
                if (lvl := formulas.resolve_education_level(deg, _EDUCATION_LEVEL_MAP)) is not None
            ]
            if resolved_cand:
                best_deg, best_lvl = max(resolved_cand, key=lambda pair: pair[1])
                for req in edu_reqs:
                    req_name = str(req["name"])
                    req_lvl = formulas.resolve_education_level(req_name, _EDUCATION_LEVEL_MAP)
                    if req_lvl is None:
                        continue
                    met = best_lvl >= req_lvl
                    evidence.append(
                        ScoreEvidence(
                            evidence_id=str(
                                uuid.uuid5(uuid.NAMESPACE_URL, f"rule:education:{req['id']}")
                            ),
                            category="education",
                            signal_type="rule_based_match",
                            value=1.0 if met else 0.0,
                            source_location="profile_data.education",
                            matched_term=best_deg,
                            requirement_term=req_name,
                            match_type="rule",
                            supporting_quotes=(best_deg,),
                            grounded=True,
                            rationale=(
                                f"Degree '{best_deg}' meets or exceeds '{req_name}'"
                                if met
                                else f"Degree '{best_deg}' is below '{req_name}'"
                            ),
                        )
                    )

        # 3. Certification requirements
        cert_reqs = [r for r in inputs.requirements if category_name(r) == "certifications"]
        if cert_reqs and inputs.certifications:
            valid_certs = []
            for cert in inputs.certifications:
                expiry = formulas._month(cert.get("expiry_date"))
                if expiry and expiry < (inputs.as_of.year, inputs.as_of.month):
                    continue
                if cert.get("name"):
                    valid_certs.append(str(cert["name"]))
            for req in cert_reqs:
                req_name = str(req["name"])
                hit = next(
                    (
                        c
                        for c in valid_certs
                        if formulas.certification_matches(req_name, c, skill_aliases)
                    ),
                    None,
                )
                evidence.append(
                    ScoreEvidence(
                        evidence_id=str(
                            uuid.uuid5(uuid.NAMESPACE_URL, f"rule:certifications:{req['id']}")
                        ),
                        category="certifications",
                        signal_type="rule_based_match",
                        value=1.0 if hit else 0.0,
                        source_location="profile_data.certifications",
                        matched_term=hit,
                        requirement_term=req_name,
                        match_type="rule",
                        supporting_quotes=(hit,) if hit else (),
                        grounded=bool(hit),
                        rationale=(
                            f"Active certification '{hit}' matches '{req_name}'"
                            if hit
                            else f"No active certification matches '{req_name}'"
                        ),
                    )
                )

        # 4. Responsibility / Project requirements
        proj_reqs = [r for r in inputs.requirements if category_name(r) == "projects"]
        if proj_reqs and (inputs.projects or inputs.experience):
            for req in proj_reqs:
                req_name = str(req["name"])
                p_rel = req_item_relevance.get(("projects", req_name.casefold()), {})
                max_p = max(p_rel.values()) if p_rel else Decimal("0")
                # Also allow checking token match in employment descriptions for responsibility reqs
                req_toks = list(dict.fromkeys(_extract_tokens(req_name, drop_stopwords=True)))
                resume_toks = set(_extract_tokens(safe_resume_text, drop_stopwords=True))
                tok_cov = (
                    sum(1 for t in req_toks if _tokens_match(t, resume_toks)) / len(req_toks)
                    if req_toks
                    else 0.0
                )
                met = max_p >= Decimal("0.6") or tok_cov >= 0.6
                evidence.append(
                    ScoreEvidence(
                        evidence_id=str(
                            uuid.uuid5(uuid.NAMESPACE_URL, f"rule:projects:{req['id']}")
                        ),
                        category="projects",
                        signal_type="rule_based_match",
                        value=1.0 if met else 0.0,
                        source_location="profile_data.projects",
                        matched_term=req_name if met else None,
                        requirement_term=req_name,
                        match_type="rule",
                        grounded=True,
                        rationale=(
                            "Project or experience claims match responsibility requirement"
                            if met
                            else "Project and experience claims do not strongly match requirement"
                        ),
                    )
                )

        # 5. Language / Other requirements
        other_reqs = [
            r for r in inputs.requirements if category_name(r) in {"language", "other"}
        ]
        if other_reqs and safe_resume_text:
            resume_toks = set(_extract_tokens(safe_resume_text, drop_stopwords=True))
            for req in other_reqs:
                req_name = str(req["name"])
                req_toks = list(dict.fromkeys(_extract_tokens(req_name, drop_stopwords=True)))
                tok_cov = (
                    sum(1 for t in req_toks if _tokens_match(t, resume_toks)) / len(req_toks)
                    if req_toks
                    else 0.0
                )
                met = tok_cov >= 0.6
                evidence.append(
                    ScoreEvidence(
                        evidence_id=str(
                            uuid.uuid5(uuid.NAMESPACE_URL, f"rule:other:{req['id']}")
                        ),
                        category="skills",
                        signal_type="rule_based_match",
                        value=1.0 if met else 0.0,
                        source_location="profile_data",
                        matched_term=req_name if met else None,
                        requirement_term=req_name,
                        match_type="rule",
                        grounded=True,
                        rationale=(
                            f"Requirement '{req_name}' matched in candidate profile"
                            if met
                            else f"Requirement '{req_name}' not found in candidate profile"
                        ),
                    )
                )

        return sorted(evidence, key=lambda e: (e.category, e.signal_type, e.evidence_id))
