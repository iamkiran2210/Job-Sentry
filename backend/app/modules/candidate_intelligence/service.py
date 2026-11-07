from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.core.exceptions import NotFoundException
from app.models.job import Job
from app.models.job_requirement import JobRequirement
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.evidence.matchers import exact_skill_evidence, llm_relevance_evidence, semantic_evidence
from app.modules.candidate_intelligence.evidence.github import github_language_evidence
from app.modules.candidate_intelligence.evidence.providers import build_embedding_provider, build_llm_analyzer
from app.modules.candidate_intelligence.matching.categories import category_match
from app.modules.candidate_intelligence.models import CandidateScore, RankingHistory, ScoreEvidenceRecord, VerificationResult
from app.modules.candidate_intelligence.ranking.service import rank_rows
from app.modules.candidate_intelligence.scoring.score import CATEGORIES, score_candidate
from app.modules.candidate_intelligence.types import CategoryMatch
from app.modules.candidate_intelligence.types import ScoringInputs
from app.modules.candidate_intelligence.verification.checks import completeness_check, duplicate_signals, email_check, overall_status, phone_check, portfolio_url_check, timeline_check, url_reachability_check


def _json(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def build_scoring_inputs(application, job, profile_data: dict, requirements: list, as_of: date) -> ScoringInputs:
    """Build the scorer's allowlist DTO; identity/contact/proxy keys are never copied."""
    allowed = ("skills", "employment", "projects", "education", "certifications")
    claim_sets = {key: tuple(dict(item) for item in (profile_data.get(key) or []) if isinstance(item, dict)) for key in allowed}
    reqs = tuple({"id": str(r.id), "category": str(r.category.value if hasattr(r.category, "value") else r.category), "name": r.name, "requirement_type": str(r.requirement_type.value if hasattr(r.requirement_type, "value") else r.requirement_type), "is_mandatory": r.is_mandatory} for r in sorted(requirements, key=lambda x: str(x.id)))
    return ScoringInputs(claim_sets["skills"], claim_sets["employment"], claim_sets["projects"], claim_sets["education"], claim_sets["certifications"], reqs, as_of)


def evidence_to_category_inputs(evidence_rows, inputs: ScoringInputs):
    """Reshape rows keyed to job requirements; contains no scoring math."""
    return {str(getattr(row, "requirement_ref", None) or getattr(row, "requirement_term", "")): row for row in evidence_rows}


class CandidateIntelligenceService:
    @staticmethod
    async def _bundle(db: AsyncSession, application_id: uuid.UUID):
        app = (await db.execute(select(Application).where(Application.id == application_id))).scalar_one_or_none()
        if app is None: raise NotFoundException("Application not found")
        resume = (await db.execute(select(Resume).where(Resume.application_id == app.id).order_by(Resume.created_at.desc()).limit(1))).scalar_one_or_none()
        profile = (await db.execute(select(ExtractedProfile).where(ExtractedProfile.resume_id == resume.id).limit(1))).scalar_one_or_none() if resume else None
        return app, resume, profile, (profile.profile_data if profile and isinstance(profile.profile_data, dict) else {})

    @staticmethod
    async def verify(db: AsyncSession, application_id: uuid.UUID):
        app, resume, profile_row, profile = await CandidateIntelligenceService._bundle(db, application_id)
        contact = profile.get("contact") or {}
        email = ((contact.get("email") or {}).get("value"))
        phone = ((contact.get("phone") or {}).get("value"))
        urls = [((contact.get(key) or {}).get("value")) for key in ("github_url", "portfolio_url")]
        prior = (await db.execute(
            select(Application, Resume, Candidate)
            .outerjoin(Resume, Resume.application_id == Application.id)
            .outerjoin(Candidate, Candidate.id == Application.candidate_id)
            .where(Application.company_id == app.company_id, Application.id != app.id)
        )).all()
        existing = []
        for other, other_resume, other_candidate in prior:
            existing.append({
                "company_id": str(other.company_id),
                "application_id": str(other.id),
                "email": other_candidate.normalized_email or other_candidate.email if other_candidate else None,
                "phone": other_candidate.normalized_phone or other_candidate.phone if other_candidate else None,
                "resume_hash": other_resume.sha256 if other_resume else None,
            })
        # Include candidate identity claims without exposing them to any score inputs.
        result_set = [email_check(email), phone_check(phone), completeness_check(profile, profile_row.source_text if profile_row else None), timeline_check(profile.get("employment") or [], date.today()), duplicate_signals(email, phone, resume.sha256 if resume else None, existing, str(app.company_id))]
        cfg = get_intelligence_settings()
        for key in ("github_url", "portfolio_url"):
            value = ((contact.get(key) or {}).get("value"))
            if value:
                url_result = await url_reachability_check(value, cfg.reachability_timeout_seconds) if cfg.reachability_check_enabled else portfolio_url_check(value)
                if key == "github_url":
                    url_result = type(url_result)("github_url", url_result.status, url_result.signal, url_result.details)
                result_set.append(url_result)
        for result in result_set:
            db.add(VerificationResult(company_id=app.company_id, application_id=app.id, check_type=result.check_type, status=result.status, signal=result.signal, details=result.details))
        await db.flush()
        return result_set

    @staticmethod
    async def analyze(db: AsyncSession, application_id: uuid.UUID):
        app, resume, profile_row, profile = await CandidateIntelligenceService._bundle(db, application_id)
        job = (await db.execute(select(Job).where(Job.id == app.job_id))).scalar_one()
        reqs = list((await db.execute(select(JobRequirement).where(JobRequirement.job_id == job.id).order_by(JobRequirement.id))).scalars().all())
        scoring_inputs = build_scoring_inputs(app, job, profile, reqs, date.today())
        cfg = get_intelligence_settings()
        skill_reqs = [r.name for r in reqs if str(r.category.value if hasattr(r.category, "value") else r.category) == "skills"]
        skill_items = profile.get("skills") or []
        evidence = exact_skill_evidence(skill_reqs, skill_items, cfg.skill_aliases)
        # GitHub and semantic signals supplement resume evidence and remain lower-weight.
        github_url = (((profile.get("contact") or {}).get("github_url") or {}).get("value"))
        github_result = {"status": "not_verified", "reason": "github_evidence_disabled"}
        if cfg.github_evidence_enabled and github_url:
            github_evidence, github_result = await github_language_evidence(
                github_url, timeout=cfg.github_timeout_seconds,
                max_repositories=cfg.github_max_repositories,
            )
            from app.modules.candidate_intelligence.evidence.matchers import canonical_skill
            req_canon = {canonical_skill(r, cfg.skill_aliases)[0] for r in skill_reqs}
            evidence.extend(e for e in github_evidence if canonical_skill(e.matched_term or "", cfg.skill_aliases)[0] in req_canon)
        embedding_provider = build_embedding_provider(cfg)
        llm_analyzer = build_llm_analyzer(cfg)
        profile_text = profile_row.source_text or "" if profile_row else ""
        # Collect claim text only from the documented job-relevant allowlist.
        claim_groups = {
            "skills": (skill_reqs, [x.get("name", "") if isinstance(x, dict) else str(x) for x in skill_items]),
            "experience": ([r.name for r in reqs if str(r.category.value if hasattr(r.category, "value") else r.category) == "experience"], [" ".join(str(v) for v in (x.get("title"), x.get("description"), " ".join(x.get("highlights") or [])) if v) for x in (profile.get("employment") or []) if isinstance(x, dict)]),
            "projects": ([r.name for r in reqs if str(r.category.value if hasattr(r.category, "value") else r.category) in {"project", "projects", "responsibility"}], [" ".join(str(v) for v in (x.get("name"), x.get("description"), " ".join(x.get("technologies") or [])) if v) for x in (profile.get("projects") or []) if isinstance(x, dict)]),
        }
        for category, (requirements_for_category, claims) in claim_groups.items():
            for requirement in requirements_for_category:
                for claim in claims:
                    if not claim.strip():
                        continue
                    try:
                        semantic = semantic_evidence(requirement, claim, embedding_provider,
                            cfg.semantic_min, cfg.semantic_model_version, category,
                            cfg.semantic_full, cfg.semantic_credit_cap)
                        if semantic.value is not None:
                            evidence.append(semantic)
                    except Exception:
                        pass
                    if category in {"experience", "projects"} and profile_text:
                        evidence.append(await llm_relevance_evidence(
                            requirement, claim, profile_text, llm_analyzer,
                            cfg.relevance_scores, category,
                        ))
        req_counts = {c: sum(1 for r in reqs if str(r.category.value if hasattr(r.category, "value") else r.category) in ({"certification": "certifications"}.get(c, c))) for c in CATEGORIES}
        matches = {c: category_match(c, req_counts[c], evidence, {"exact_skill_match": cfg.weight_exact_match, "alias_skill_match": cfg.weight_alias_match, "github_language_signal": cfg.weight_github_language, "semantic_similarity": 1.0, "llm_relevance": cfg.weight_llm_relevance}) for c in CATEGORIES}
        required = [{"id": str(r.id), "name": r.name, "category": str(r.category.value if hasattr(r.category, "value") else r.category), "is_mandatory": r.is_mandatory} for r in reqs]
        weights = {"skills": cfg.weight_skills, "experience": cfg.weight_experience, "projects": cfg.weight_projects, "education": cfg.weight_education, "certifications": cfg.weight_certifications}
        scored = score_candidate(matches, evidence, required, weights, {"exact_skill_match": cfg.weight_exact_match, "alias_skill_match": cfg.weight_alias_match, "github_language_signal": cfg.weight_github_language, "semantic_similarity": cfg.weight_semantic_match, "llm_relevance": cfg.weight_llm_relevance}, cfg.low_completeness_threshold)
        input_payload = {"requirements": [{"id": str(r.id), "category": str(r.category.value if hasattr(r.category, "value") else r.category), "name": r.name, "type": str(r.requirement_type.value if hasattr(r.requirement_type, "value") else r.requirement_type), "weight": r.weight, "mandatory": r.is_mandatory} for r in reqs], "profile": {key: profile.get(key) for key in ("skills", "employment", "experience", "projects", "education", "certifications")}, "evidence": sorted((e.evidence_id, e.value, e.signal_type) for e in evidence)}
        inputs_hash = hashlib.sha256(json.dumps(input_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        snapshot = {**scored.config_snapshot, "scoring_version": cfg.scoring_version, "algorithm_version": cfg.algorithm_version, "data_completeness": str(scored.data_completeness), "score_lower_bound": str(scored.score_lower_bound) if scored.score_lower_bound is not None else None, "score_upper_bound": str(scored.score_upper_bound) if scored.score_upper_bound is not None else None}
        row = (await db.execute(select(CandidateScore).where(CandidateScore.application_id == app.id, CandidateScore.job_id == job.id, CandidateScore.scoring_version == cfg.scoring_version, CandidateScore.inputs_hash == inputs_hash))).scalar_one_or_none()
        if row is None:
            row = CandidateScore(company_id=app.company_id, application_id=app.id, job_id=job.id, scoring_version=cfg.scoring_version, algorithm_version=cfg.algorithm_version, score=float(scored.score * 100) if scored.score is not None else None, score_lower_bound=float(scored.score_lower_bound * 100) if scored.score_lower_bound is not None else None, score_upper_bound=float(scored.score_upper_bound * 100) if scored.score_upper_bound is not None else None, data_completeness=float(scored.data_completeness), mandatory_results=[{"requirement_id": m.requirement_id, "status": m.status, "evidence_ids": list(m.evidence_ids)} for m in scored.mandatory_results], inputs_hash=inputs_hash, category_detail={c: {"score": str(m.score) if m.score is not None else None, "status": m.status, "evidence_ids": list(m.evidence_ids), "confidence": str(m.confidence), "coverage": str(m.coverage)} for c,m in scored.categories.items()}, eligibility=scored.eligibility, review_signals=list(scored.review_signals), config_snapshot=snapshot)
            db.add(row); await db.flush()
        for ev in evidence:
            exists = (await db.execute(select(ScoreEvidenceRecord).where(ScoreEvidenceRecord.score_id == row.id, ScoreEvidenceRecord.evidence_id == ev.evidence_id))).scalar_one_or_none()
            if not exists:
                db.add(ScoreEvidenceRecord(company_id=app.company_id, score_id=row.id, application_id=app.id, evidence_id=ev.evidence_id, category=ev.category, signal_type=ev.signal_type, value=ev.value, evidence_data=_json(ev.__dict__)))
        await db.flush()
        verification = (await db.execute(select(VerificationResult).where(VerificationResult.application_id == app.id).order_by(VerificationResult.created_at.desc()))).scalars().all()
        if not verification:
            await CandidateIntelligenceService.verify(db, app.id)
            verification = (await db.execute(select(VerificationResult).where(VerificationResult.application_id == app.id).order_by(VerificationResult.created_at.desc()))).scalars().all()
        evidence_out = [_json(e.__dict__) for e in evidence]
        return {"application_id": str(app.id), "score_id": str(row.id), "score": float(row.score) if row.score is not None else None, "score_percent": float(row.score) if row.score is not None else None, "score_lower_bound": float(row.score_lower_bound) if row.score_lower_bound is not None else None, "score_upper_bound": float(row.score_upper_bound) if row.score_upper_bound is not None else None, "data_completeness": float(row.data_completeness), "mandatory_results": row.mandatory_results, "categories": row.category_detail, "eligibility": row.eligibility, "review_signals": row.review_signals, "evidence": evidence_out, "evidence_summary": {"exact_matches": sum(e.signal_type in {"exact_skill_match", "alias_skill_match"} and e.value is not None for e in evidence), "semantic_signals": sum(e.signal_type == "semantic_similarity" and e.value is not None for e in evidence), "llm_signals": sum(e.signal_type == "llm_relevance" and e.value is not None for e in evidence), "github_languages": github_result}, "analysis_summary": {"text": f"Candidate score is {float(row.score):.1f}% based on available evidence." if row.score is not None else "There is not enough candidate evidence to calculate a score.", "interpretation": "Scores and public GitHub language metadata are decision-support signals; they do not verify skill, employment, or identity."}, "verification": [{"check_type": v.check_type, "status": v.status, "signal": v.signal, "details": v.details} for v in verification], "scoring_version": row.scoring_version, "algorithm_version": row.algorithm_version, "config_snapshot": row.config_snapshot}

    @staticmethod
    async def rank(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, filters: dict):
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        reqs = list((await db.execute(select(JobRequirement).where(JobRequirement.job_id == job.id).order_by(JobRequirement.id))).scalars().all())
        apps = list((await db.execute(select(Application).where(Application.job_id == job.id).order_by(Application.created_at, Application.id))).scalars().all())
        rows = []
        scores_by_app = {}
        verification_by_app = {}
        for app in apps:
            analysis = await CandidateIntelligenceService.analyze(db, app.id)
            score = (await db.execute(select(CandidateScore).where(CandidateScore.id == uuid.UUID(analysis["score_id"])))).scalar_one()
            scores_by_app[str(app.id)] = score
            checks = (await db.execute(select(VerificationResult).where(VerificationResult.application_id == app.id).order_by(VerificationResult.created_at.desc()))).scalars().all()
            latest = {}
            for check in checks:
                latest.setdefault(check.check_type, check.status)
            verification_by_app[str(app.id)] = latest
            rows.append({"application_id": str(app.id), "application_created_at": app.created_at.isoformat(), "score": float(score.score) if score.score is not None else None, "eligibility": score.eligibility, "skills_score": (score.category_detail.get("skills") or {}).get("score"), "data_completeness": score.data_completeness, "status": app.status, "verification_statuses": list(latest.values())})
        page = rank_rows(rows, offset=filters.get("offset",0), limit=filters.get("limit",50), eligibility=filters.get("eligibility"), min_score=filters.get("min_score"), max_score=filters.get("max_score"), status=filters.get("status"))
        cfg = get_intelligence_settings()
        requirements_snapshot = [{"id": str(r.id), "category": str(r.category.value if hasattr(r.category,"value") else r.category), "name": r.name, "type": str(r.requirement_type.value if hasattr(r.requirement_type,"value") else r.requirement_type), "is_mandatory": r.is_mandatory, "weight": r.weight} for r in reqs]
        requirement_hash = hashlib.sha256(json.dumps(requirements_snapshot, sort_keys=True).encode()).hexdigest()
        config_snapshot = {"scoring_version": cfg.scoring_version, "algorithm_version": cfg.algorithm_version, "weights": {c: getattr(cfg, f"weight_{c}") for c in CATEGORIES}}
        run_id = uuid.uuid4()
        for item in page:
            score_row = scores_by_app[item["application_id"]]
            tie_key = {"score": item.get("score"), "eligibility": item.get("eligibility"), "skills_score": item.get("skills_score"), "data_completeness": item.get("data_completeness"), "application_created_at": item.get("application_created_at"), "application_id": item.get("application_id")}
            db.add(RankingHistory(company_id=job.company_id, job_id=job.id, run_id=run_id, application_id=uuid.UUID(item["application_id"]), candidate_score_id=score_row.id, rank=item["rank"], total_score=item.get("score"), tie_break_key=tie_key, requirements_snapshot=requirements_snapshot, requirements_hash=requirement_hash, ranked_items=page, filters_used=filters, scoring_version=cfg.scoring_version, algorithm_version=cfg.algorithm_version, config_snapshot=config_snapshot, triggered_by=user_id))
        await db.flush()
        return {"run_id": str(run_id), "count": len(page), "scoring_version": cfg.scoring_version, "algorithm_version": cfg.algorithm_version, "items": page}


class ScoringService:
    """Explicit score-write entry point. Read endpoints must not call this."""

    @staticmethod
    async def score_application(application_id: uuid.UUID, job_id: uuid.UUID, scoring_config=None, as_of: date | None = None, db: AsyncSession | None = None):
        if db is None:
            raise ValueError("AsyncSession is required")
        application = (await db.execute(select(Application).where(Application.id == application_id, Application.job_id == job_id))).scalar_one_or_none()
        if application is None:
            raise NotFoundException("Application not found")
        # The existing analysis orchestration is the scoring write path; this
        # method makes the write boundary explicit for the rank command.
        return await CandidateIntelligenceService.analyze(db, application_id)
