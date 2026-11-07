from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from collections.abc import Mapping

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
from app.modules.candidate_intelligence.evidence.providers import build_embedding_provider, build_llm_analyzer
from app.modules.candidate_intelligence.models import CandidateScore, RankingHistory, ScoreEvidenceRecord, VerificationResult
from app.modules.candidate_intelligence.ranking.service import rank_rows
from app.modules.candidate_intelligence.scoring import category_formulas as formulas
from app.modules.candidate_intelligence.types import ScoringInputs
from app.modules.candidate_intelligence.verification.checks import completeness_check, duplicate_signals, email_check, github_url_check, overall_status, phone_check, portfolio_url_check, timeline_check, url_reachability_check


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


def build_scoring_inputs(application, job, as_of: date, profile_data: dict | None = None, requirements: list | None = None) -> ScoringInputs:
    """Build the scorer's allowlist DTO; identity/contact/proxy keys are never copied."""
    profile_data = profile_data or {}
    requirements = requirements or []
    allowed_fields = {
        "skills": {"id", "name", "evidence", "section"},
        "employment": {"id", "title", "start_date", "end_date", "is_current", "description", "highlights"},
        "projects": {"id", "name", "description", "technologies"},
        "education": {"id", "degree", "field"},
        "certifications": {"id", "name", "expiry_date"},
    }
    claim_sets = {}
    for key, fields in allowed_fields.items():
        values = []
        raw_items = profile_data.get(key) or []
        clean_items = []
        for item in raw_items:
            if isinstance(item, dict):
                clean = {field: item[field] for field in fields if field in item}
            elif key == "skills" and isinstance(item, str):
                clean = {"name": item}
            else:
                continue
            clean_items.append(clean)
        clean_items.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
        for clean in clean_items:
            if not clean.get("id"):
                digest = hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]
                clean["id"] = f"{key}-{digest}"
            values.append(clean)
        claim_sets[key] = tuple(values)
    reqs = tuple({"id": str(r.id), "category": str(r.category.value if hasattr(r.category, "value") else r.category), "name": r.name, "requirement_type": str(r.requirement_type.value if hasattr(r.requirement_type, "value") else r.requirement_type), "is_mandatory": r.is_mandatory} for r in sorted(requirements, key=lambda x: str(x.id)))
    return ScoringInputs(claim_sets["skills"], claim_sets["employment"], claim_sets["projects"], claim_sets["education"], claim_sets["certifications"], reqs, as_of)


def evidence_to_category_inputs(evidence_rows, inputs: ScoringInputs):
    """Adapt collected evidence into pure-formula arguments without doing score math."""
    reqs = list(inputs.requirements)
    by_name = {}
    for requirement in reqs:
        by_name.setdefault(str(requirement.get("name", "")).casefold(), []).append(requirement)
    skill_credits = {}
    relevance = {"experience": {}, "projects": {}}
    for row in sorted(evidence_rows, key=lambda e: (str(getattr(e, "category", "")), str(getattr(e, "evidence_id", "")))):
        category = str(getattr(row, "category", ""))
        matched_requirements = by_name.get(str(getattr(row, "requirement_term", "")).casefold(), [])
        location = str(getattr(row, "source_location", "") or "")
        if category == "skills" and matched_requirements and getattr(row, "value", None) is not None:
            credit = Decimal(str(row.value))
            for req in matched_requirements:
                old = skill_credits.get(req["id"])
                if old is None or credit > old[0]:
                    skill_credits[req["id"]] = (credit, str(row.evidence_id))
        elif category in relevance and getattr(row, "signal_type", None) == "llm_relevance" and getattr(row, "value", None) is not None and ":" in location:
            item_id = location.split(":", 1)[1]
            key = category, item_id
            current = relevance[category].get(item_id)
            value = Decimal(str(row.value))
            if current is None or value > current[0]:
                relevance[category][item_id] = (value, str(row.evidence_id))
    for req in reqs:
        if req.get("category") == "skills" and req["id"] not in skill_credits and inputs.skills:
            skill_credits[req["id"]] = (Decimal(0), None)
    return {"skill_credits": skill_credits,
            "experience_relevance": {k: v[0] for k, v in relevance["experience"].items()},
            "project_relevance": {k: v[0] for k, v in relevance["projects"].items()},
            "evidence_ids": {k: v[1] for group in relevance.values() for k, v in group.items()}}


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
        cfg = get_intelligence_settings()
        result_set = [email_check(email), phone_check(phone, cfg.phone_region),
                      completeness_check(profile, profile_row.source_text if profile_row else None,
                                         cfg.completeness_review_threshold, cfg.completeness_fail_threshold),
                      timeline_check(profile.get("employment") or [], date.today()),
                      duplicate_signals(email, phone, resume.sha256 if resume else None, existing, str(app.company_id))]
        for key in ("github_url", "portfolio_url"):
            value = ((contact.get(key) or {}).get("value"))
            checker = github_url_check if key == "github_url" else portfolio_url_check
            url_result = await url_reachability_check(value, cfg.reachability_timeout_seconds, key) if cfg.reachability_check_enabled and value else checker(value)
            result_set.append(url_result)
        for result in result_set:
            db.add(VerificationResult(company_id=app.company_id, application_id=app.id, check_type=result.check_type, status=result.status, signal=result.signal, details=result.details))
        await db.flush()
        return result_set

    @staticmethod
    async def analyze(db: AsyncSession, application_id: uuid.UUID):
        app, _, _, _ = await CandidateIntelligenceService._bundle(db, application_id)
        row = (await db.execute(select(CandidateScore).where(CandidateScore.application_id == app.id, CandidateScore.job_id == app.job_id).order_by(CandidateScore.created_at.desc()).limit(1))).scalar_one_or_none()
        verifications = (await db.execute(select(VerificationResult).where(VerificationResult.application_id == app.id).order_by(VerificationResult.created_at.desc()))).scalars().all()
        latest_verifications = {}
        for verification in verifications:
            latest_verifications.setdefault(verification.check_type, verification)
        evidence_rows = []
        if row:
            evidence_rows = (await db.execute(select(ScoreEvidenceRecord).where(ScoreEvidenceRecord.score_id == row.id).order_by(ScoreEvidenceRecord.created_at))).scalars().all()
        return {"application_id": str(app.id), "score_id": str(row.id) if row else None,
                "score": float(row.score) if row and row.score is not None else None,
                "score_percent": float(row.score) if row and row.score is not None else None,
                "score_lower_bound": float(row.score_lower_bound) if row else None,
                "score_upper_bound": float(row.score_upper_bound) if row else None,
                "data_completeness": float(row.data_completeness) if row else None,
                "mandatory_results": row.mandatory_results if row else [],
                "categories": row.category_detail if row else {}, "eligibility": row.eligibility if row else None,
                "review_signals": row.review_signals if row else [],
                "evidence": [x.evidence_data for x in evidence_rows],
                "analysis_summary": {"text": "Candidate analysis is not scored yet." if row is None else "Score reflects available job-relevant evidence.",
                    "interpretation": "Scores and public profile metadata are decision-support signals; they do not verify skill, employment, or identity."},
                "verification": [{"check_type": v.check_type, "status": v.status, "signal": v.signal, "details": v.details} for v in latest_verifications.values()],
                "scoring_version": row.scoring_version if row else None,
                "algorithm_version": row.algorithm_version if row else None,
                "config_snapshot": row.config_snapshot if row else None}

    @staticmethod
    async def rank(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, filters: dict):
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        reqs = list((await db.execute(select(JobRequirement).where(JobRequirement.job_id == job.id).order_by(JobRequirement.id))).scalars().all())
        apps = list((await db.execute(select(Application).where(Application.job_id == job.id).order_by(Application.created_at, Application.id))).scalars().all())
        rows = []
        scores_by_app = {}
        verification_by_app = {}
        for app in apps:
            cfg = get_intelligence_settings()
            score = await ScoringService.score_application(app.id, job.id, cfg, as_of=date.today(), db=db)
            scores_by_app[str(app.id)] = score
            checks = (await db.execute(select(VerificationResult).where(VerificationResult.application_id == app.id).order_by(VerificationResult.created_at.desc()))).scalars().all()
            latest = {}
            for check in checks:
                latest.setdefault(check.check_type, check.status)
            verification_by_app[str(app.id)] = latest
            rows.append({"application_id": str(app.id), "application_created_at": app.created_at.isoformat(), "score": float(score.score) if score.score is not None else None, "eligibility": score.eligibility, "skills_score": (score.category_detail.get("skills") or {}).get("match"), "data_completeness": float(score.data_completeness), "status": app.status, "verification_statuses": list(latest.values())})
        all_ranked = rank_rows(rows, offset=0, limit=len(rows) or 1,
            eligibility=filters.get("eligibility"), min_score=filters.get("min_score"),
            max_score=filters.get("max_score"), status=filters.get("status"),
            verification_status=filters.get("verification_status"))
        offset, limit = filters.get("offset", 0), filters.get("limit", 50)
        page = all_ranked[offset:offset + limit]
        cfg = get_intelligence_settings()
        requirements_snapshot = [{"id": str(r.id), "category": str(r.category.value if hasattr(r.category,"value") else r.category), "name": r.name, "type": str(r.requirement_type.value if hasattr(r.requirement_type,"value") else r.requirement_type), "is_mandatory": r.is_mandatory, "weight": r.weight} for r in reqs]
        requirement_hash = hashlib.sha256(json.dumps(requirements_snapshot, sort_keys=True).encode()).hexdigest()
        config_snapshot = {"scoring_version": cfg.scoring_version, "algorithm_version": cfg.algorithm_version,
                           "weights": {c: getattr(cfg, f"weight_{c}") for c in CATEGORIES},
                           "semantic_min": cfg.semantic_min, "semantic_full": cfg.semantic_full,
                           "semantic_credit_cap": cfg.semantic_credit_cap,
                           "low_completeness_threshold": cfg.low_completeness_threshold,
                           "skill_aliases": cfg.skill_aliases, "relevance_scores": cfg.relevance_scores}
        provider_snapshot = {"embedding_provider": cfg.embedding_provider, "embedding_model": cfg.semantic_model_name,
                             "embedding_version": cfg.semantic_model_version, "llm_provider": cfg.llm_provider,
                             "llm_model": cfg.llm_model, "llm_prompt_version": cfg.llm_prompt_version}
        config_hash = hashlib.sha256(json.dumps({"config": config_snapshot, "providers": provider_snapshot}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        run_id = uuid.uuid4()
        for item in all_ranked:
            score_row = scores_by_app[item["application_id"]]
            tie_key = {"score": item.get("score"), "eligibility": item.get("eligibility"), "skills_score": item.get("skills_score"), "data_completeness": item.get("data_completeness"), "application_created_at": item.get("application_created_at"), "application_id": item.get("application_id")}
            db.add(RankingHistory(company_id=job.company_id, job_id=job.id, run_id=run_id, application_id=uuid.UUID(item["application_id"]), candidate_score_id=score_row.id, rank=item["rank"], total_score=item.get("score"), tie_break_key=tie_key, requirements_snapshot=requirements_snapshot, requirements_hash=requirement_hash, ranked_items=all_ranked, filters_used=filters, scoring_version=cfg.scoring_version, algorithm_version=cfg.algorithm_version, config_snapshot=config_snapshot, config_hash=config_hash, provider_snapshot=provider_snapshot, triggered_by=user_id))
        if not all_ranked:
            db.add(RankingHistory(company_id=job.company_id, job_id=job.id, run_id=run_id,
                application_id=None, candidate_score_id=None, rank=None, total_score=None,
                tie_break_key={}, requirements_snapshot=requirements_snapshot,
                requirements_hash=requirement_hash, ranked_items=[], filters_used=filters,
                scoring_version=cfg.scoring_version, algorithm_version=cfg.algorithm_version,
                config_snapshot=config_snapshot, config_hash=config_hash,
                provider_snapshot=provider_snapshot, triggered_by=user_id))
        await db.flush()
        return {"run_id": str(run_id), "count": len(page), "total_count": len(all_ranked),
                "offset": offset, "limit": limit, "scoring_version": cfg.scoring_version,
                "algorithm_version": cfg.algorithm_version, "config_hash": config_hash,
                "provider_snapshot": provider_snapshot, "items": page}


class ScoringService:
    """Explicit score-write entry point. Read endpoints must not call this."""

    @staticmethod
    async def score_application(application_id: uuid.UUID, job_id: uuid.UUID, scoring_config=None, as_of: date | None = None, db: AsyncSession | None = None):
        if db is None:
            raise ValueError("AsyncSession is required")
        application = (await db.execute(select(Application).where(Application.id == application_id, Application.job_id == job_id))).scalar_one_or_none()
        if application is None:
            raise NotFoundException("Application not found")
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        resume = (await db.execute(select(Resume).where(Resume.application_id == application_id).order_by(Resume.created_at.desc()).limit(1))).scalar_one_or_none()
        profile_row = (await db.execute(select(ExtractedProfile).where(ExtractedProfile.resume_id == resume.id).limit(1))).scalar_one_or_none() if resume else None
        profile = profile_row.profile_data if profile_row and isinstance(profile_row.profile_data, dict) else {}
        requirements = list((await db.execute(select(JobRequirement).where(JobRequirement.job_id == job_id).order_by(JobRequirement.id))).scalars().all())
        scoring_config = scoring_config or get_intelligence_settings()
        as_of = as_of or date.today()
        inputs = build_scoring_inputs(application, job, as_of, profile, requirements)
        evidence = await ScoringService._collect_evidence(inputs, scoring_config)
        adapted = evidence_to_category_inputs(evidence, inputs)
        reqs = list(inputs.requirements)
        cat = lambda req: {"certification": "certifications", "project": "projects", "responsibility": "projects"}.get(req["category"], req["category"])
        skills_reqs = [r for r in reqs if cat(r) == "skills"]
        cert_reqs = [r for r in reqs if cat(r) == "certifications"]
        education_reqs = [r for r in reqs if cat(r) == "education"]
        experience_reqs = [r for r in reqs if cat(r) == "experience"]
        project_weight = Decimal(str(scoring_config.weight_projects))
        weights = formulas.validate_weights({name: getattr(scoring_config, f"weight_{name}") for name in ("skills", "experience", "projects", "education", "certifications")})
        skills = formulas.score_skills(skills_reqs, adapted["skill_credits"], weights["skills"])
        required_years = None
        for req in experience_reqs:
            try:
                required_years = Decimal(req["name"].split()[0])
                break
            except Exception:
                continue
        experience = formulas.score_experience(list(inputs.experience), adapted["experience_relevance"], required_years, as_of, weights["experience"])
        projects = formulas.score_projects(list(inputs.projects), adapted["project_relevance"], project_weight)
        level_map = {"none": 0, "high_school": 1, "high school": 1, "associate": 2, "bachelor": 3, "b.tech": 3, "be": 3, "bsc": 3, "ba": 3, "master": 4, "m.tech": 4, "ms": 4, "msc": 4, "mba": 4, "doctorate": 5, "phd": 5}
        education = formulas.score_education([str(x.get("degree", "")) for x in inputs.education if x.get("degree")], education_reqs[0]["name"] if education_reqs else None, level_map, weights["education"])
        certifications = formulas.score_certifications(cert_reqs, list(inputs.certifications), scoring_config.skill_aliases, weights["certifications"], as_of)
        mandatory = formulas.evaluate_mandatory(reqs, evidence)
        config_snapshot = {"scoring_version": scoring_config.scoring_version, "algorithm_version": scoring_config.algorithm_version,
            "weights": {k: str(v) for k, v in weights.items()}, "semantic_min": scoring_config.semantic_min,
            "semantic_full": scoring_config.semantic_full, "semantic_credit_cap": scoring_config.semantic_credit_cap,
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
            "reproducibility_inputs": _json(inputs.__dict__)}
        aggregate = formulas.aggregate([skills, experience, projects, education, certifications], list(mandatory.results), Decimal(str(scoring_config.low_completeness_threshold)))
        input_payload = {"inputs": _json(inputs.__dict__), "config": config_snapshot,
            "evidence": sorted((e.evidence_id, e.value, e.signal_type) for e in evidence)}
        inputs_hash = hashlib.sha256(json.dumps(input_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        category_scores = {r.category: {"status": r.status, "match": str(r.match) if r.match is not None else None,
            "weight": str(r.weight), "weighted_contribution": str(r.weighted_contribution) if r.weighted_contribution is not None else None,
            "components": _json(r.components), "evidence_ids": list(r.evidence_ids), "notes": list(r.notes)}
            for r in (skills, experience, projects, education, certifications)}
        snapshot = {**config_snapshot, "category_scores": category_scores, "as_of_date": as_of.isoformat(), "inputs_hash": inputs_hash}
        score_row = (await db.execute(select(CandidateScore).where(CandidateScore.application_id == application_id, CandidateScore.job_id == job_id, CandidateScore.scoring_version == scoring_config.scoring_version, CandidateScore.inputs_hash == inputs_hash))).scalar_one_or_none()
        if score_row is None:
            score_row = CandidateScore(company_id=application.company_id, application_id=application_id, job_id=job_id,
                scoring_version=scoring_config.scoring_version, algorithm_version=scoring_config.algorithm_version,
                score=aggregate.total_score, score_lower_bound=aggregate.score_lower_bound,
                score_upper_bound=aggregate.score_upper_bound, data_completeness=aggregate.data_completeness,
                mandatory_results=list(mandatory.results), inputs_hash=inputs_hash, as_of_date=as_of, category_detail=category_scores,
                eligibility=aggregate.eligibility, review_signals=list(aggregate.review_signals), config_snapshot=snapshot)
            db.add(score_row)
            await db.flush()
        for ev in evidence:
            exists = (await db.execute(select(ScoreEvidenceRecord).where(ScoreEvidenceRecord.score_id == score_row.id, ScoreEvidenceRecord.evidence_id == ev.evidence_id))).scalar_one_or_none()
            if exists is None:
                db.add(ScoreEvidenceRecord(company_id=application.company_id, score_id=score_row.id, application_id=application_id,
                    evidence_id=ev.evidence_id, category=ev.category, signal_type=ev.signal_type, value=ev.value,
                    evidence_data=_json(ev.__dict__), source_location=ev.source_location, matched_term=ev.matched_term,
                    requirement_term=ev.requirement_term, canonical_term=ev.canonical_term, alias_used=ev.alias_used,
                    match_type=ev.match_type, compared_texts=list(ev.compared_texts) if ev.compared_texts else None,
                    model_version=ev.model_version, similarity=ev.similarity, rationale=ev.rationale,
                    supporting_quotes=list(ev.supporting_quotes), error=ev.error,
                    model_name=ev.model_name, input_hash=ev.input_hash,
                    embedding=list(ev.embedding) if ev.embedding else None,
                    embedding_model_name=ev.embedding_model, embedding_model_version=ev.embedding_model_version,
                    embedding_dimension=ev.embedding_dim, embedding_model=ev.embedding_model,
                    embedding_dim=ev.embedding_dim, llm_model=ev.llm_model,
                    prompt_version=ev.prompt_version, source_start=ev.source_start, source_end=ev.source_end,
                    grounded=ev.grounded if ev.grounded is not None else False,
                    is_proof=ev.signal_type in {"exact_skill_match", "alias_skill_match"}))
        await db.flush()
        return score_row

    @staticmethod
    async def _collect_evidence(inputs: ScoringInputs, cfg):
        evidence = []
        category_name = lambda r: {"certification": "certifications", "project": "projects", "responsibility": "projects"}.get(r["category"], r["category"])
        safe_resume_text = "\n".join(
            str(value)
            for group, fields in ((inputs.skills, ("name", "evidence")), (inputs.experience, ("title", "description")),
                                  (inputs.projects, ("name", "description", "technologies")),
                                  (inputs.education, ("degree", "field")), (inputs.certifications, ("name",)))
            for item in group for field in fields if (value := item.get(field))
        )
        skill_reqs = [r["name"] for r in inputs.requirements if category_name(r) == "skills"]
        evidence.extend(exact_skill_evidence(skill_reqs, [dict(item) for item in inputs.skills], cfg.skill_aliases))
        embedder, analyzer = build_embedding_provider(cfg), build_llm_analyzer(cfg)
        for item in inputs.skills:
            claim = str(item.get("name", ""))
            if not claim:
                continue
            for requirement in skill_reqs:
                try:
                    from dataclasses import replace
                    sem = semantic_evidence(requirement, claim, embedder, cfg.semantic_min, cfg.semantic_model_version, "skills", cfg.semantic_full, cfg.semantic_credit_cap)
                    evidence.append(replace(sem, source_location=f"skills:{item['id']}"))
                except Exception:
                    pass
        for category, items in (("experience", inputs.experience), ("projects", inputs.projects)):
            reqs = [r["name"] for r in inputs.requirements if category_name(r) == category]
            for item in items:
                item_id = str(item.get("id", ""))
                claim = " ".join(str(v) for v in (item.get("title"), item.get("name"), item.get("description"), " ".join(item.get("highlights") or []), " ".join(item.get("technologies") or [])) if v)
                if not claim.strip():
                    continue
                for requirement in reqs:
                    try:
                        sem = semantic_evidence(requirement, claim, embedder, cfg.semantic_min, cfg.semantic_model_version, category, cfg.semantic_full, cfg.semantic_credit_cap)
                        from dataclasses import replace
                        sem_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sem.evidence_id}:{category}:{item_id}"))
                        evidence.append(replace(sem, evidence_id=sem_id, source_location=f"{category}:{item_id}"))
                    except Exception:
                        pass
                    if safe_resume_text:
                        llm = await llm_relevance_evidence(requirement, claim, safe_resume_text, analyzer, cfg.relevance_scores, category)
                        from dataclasses import replace
                        llm_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{llm.evidence_id}:{category}:{item_id}"))
                        evidence.append(replace(llm, evidence_id=llm_id, source_location=f"{category}:{item_id}"))
        return sorted(evidence, key=lambda e: (e.category, e.signal_type, e.evidence_id))
