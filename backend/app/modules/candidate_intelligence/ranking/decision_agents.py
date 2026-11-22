"""Multi-agent hiring Decision Agent panel for ranked candidates.

Each candidate in a ranking run is evaluated by four complementary, transparent
decision agents (Balanced Hiring Manager, Strict Bar Raiser, Growth & Potential
Scout, and Verification & Risk Guard). Decisions are advisory recommendations
for human recruiters — they never mutate application statuses automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

DecisionAgentId = Literal["balanced", "bar_raiser", "growth_potential", "risk_guardian"]
DecisionOutcome = Literal["strong_advance", "advance", "review", "hold", "pass"]

DECISION_AGENT_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "balanced",
        "name": "Balanced Hiring Manager",
        "short_name": "Balanced",
        "tagline": "Weighs overall fit, mandatory requirements, skills, and verification evenly.",
    },
    {
        "id": "bar_raiser",
        "name": "Strict Bar Raiser",
        "short_name": "Bar Raiser",
        "tagline": "High technical bar requiring strong scores, mandatory pass, and verified proof.",
    },
    {
        "id": "growth_potential",
        "name": "Growth & Potential Scout",
        "short_name": "Growth Scout",
        "tagline": "Prioritizes strong skills, projects, and trajectory even with minor gaps.",
    },
    {
        "id": "risk_guardian",
        "name": "Verification & Risk Guard",
        "short_name": "Risk Guard",
        "tagline": "Prioritizes profile authenticity, data completeness, and clean verification.",
    },
)

DECISION_AGENT_IDS: tuple[DecisionAgentId, ...] = (
    "balanced",
    "bar_raiser",
    "growth_potential",
    "risk_guardian",
)

AGENT_NAME_BY_ID: dict[str, str] = {a["id"]: a["name"] for a in DECISION_AGENT_CATALOG}

DECISION_LABELS: dict[str, str] = {
    "strong_advance": "Strong Advance",
    "advance": "Advance",
    "review": "Manual Review",
    "hold": "Hold",
    "pass": "Do Not Advance",
}


def list_decision_agents() -> list[dict[str, str]]:
    return [dict(item) for item in DECISION_AGENT_CATALOG]


def normalize_agent_id(agent_id: str | None, default: str = "balanced") -> DecisionAgentId:
    if agent_id in AGENT_NAME_BY_ID:
        return agent_id  # type: ignore[return-value]
    return default if default in AGENT_NAME_BY_ID else "balanced"  # type: ignore[return-value]


def _pct(val: float | None) -> int | None:
    if val is None:
        return None
    f = float(val)
    if f <= 1.0:
        return round(f * 100)
    return round(f)


def _summarize_verification(
        verification_statuses: list[str] | None,
        verification_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    statuses = list(verification_statuses or [])
    vmap = dict(verification_map or {})
    if not statuses and vmap:
        statuses = list(vmap.values())
    failed = [k for k, v in vmap.items() if v == "failed"]
    needs_review = [k for k, v in vmap.items() if v == "needs_review"]
    passed = [k for k, v in vmap.items() if v == "passed"]
    fail_count = len(failed) if vmap else statuses.count("failed")
    review_count = len(needs_review) if vmap else statuses.count("needs_review")
    passed_count = len(passed) if vmap else statuses.count("passed")
    external_checks = {
        k: vmap[k]
        for k in ("github_profile", "portfolio_ai", "linkedin_profile", "project_links")
        if k in vmap
    }
    external_passed = sum(1 for v in external_checks.values() if v == "passed")
    external_failed = sum(1 for v in external_checks.values() if v == "failed")
    return {
        "fail_count": fail_count,
        "review_count": review_count,
        "passed_count": passed_count,
        "failed_checks": failed,
        "review_checks": needs_review,
        "external_passed": external_passed,
        "external_failed": external_failed,
        "has_checks": bool(statuses),
    }


def _make_decision(
        agent_id: DecisionAgentId,
        decision: DecisionOutcome,
        confidence: float,
        summary: str,
        next_step: str,
        key_factors: list[str],
        risk_flags: list[str],
        mode: str = "deterministic",
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "agent_name": AGENT_NAME_BY_ID[agent_id],
        "decision": decision,
        "confidence": round(max(0.0, min(1.0, float(confidence))), 2),
        "summary": summary.strip()[:220],
        "next_step": next_step.strip()[:120],
        "key_factors": [str(x).strip()[:120] for x in key_factors if str(x).strip()][:3],
        "risk_flags": [str(x).strip()[:120] for x in risk_flags if str(x).strip()][:3],
        "mode": mode,
    }


def deterministic_candidate_decisions(
        *,
        score: float | None,
        eligibility: str | None,
        skills_score: float | None,
        data_completeness: float | None,
        verification_statuses: list[str] | None = None,
        verification_map: dict[str, str] | None = None,
        category_detail: dict[str, Any] | None = None,
        mandatory_results: list[dict[str, Any]] | None = None,
        review_signals: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Calibrated deterministic decisions for all four specialized decision agents."""
    s = float(score) if score is not None else None
    elig = eligibility or "needs_review"
    sk = _pct(skills_score)
    comp = float(data_completeness) if data_completeness is not None else 0.0
    comp_pct = round(comp * 100) if comp <= 1.0 else round(comp)
    ver = _summarize_verification(verification_statuses, verification_map)
    cat = category_detail or {}
    proj_match = _pct((cat.get("projects") or {}).get("match"))
    exp_match = _pct((cat.get("experience") or {}).get("match"))

    failed_mandatory = [
        str(m.get("requirement") or m.get("name") or "Mandatory requirement")
        for m in (mandatory_results or [])
        if isinstance(m, dict) and m.get("status") in {"not_met", "failed", "missing"}
    ]

    base_strengths: list[str] = []
    if s is not None:
        base_strengths.append(f"Overall match score {round(s)}%")
    if sk is not None and sk >= 65:
        base_strengths.append(f"Strong skills alignment ({sk}%)")
    if exp_match is not None and exp_match >= 65:
        base_strengths.append(f"Relevant experience ({exp_match}%)")
    if proj_match is not None and proj_match >= 65:
        base_strengths.append(f"Relevant project portfolio ({proj_match}%)")
    if elig == "eligible":
        base_strengths.append("Meets mandatory requirements")
    if ver["external_passed"] > 0:
        base_strengths.append(f"{ver['external_passed']} external profile check(s) passed")

    base_risks: list[str] = []
    if elig == "potentially_ineligible":
        base_risks.append(
            f"Missing mandatory requirement: {failed_mandatory[0]}"
            if failed_mandatory
            else "May not meet mandatory requirements"
        )
    elif elig == "needs_review":
        base_risks.append("Mandatory requirements need manual confirmation")
    if ver["fail_count"] > 0:
        label = ", ".join(c.replace("_", " ") for c in ver["failed_checks"][:2]) or "verification"
        base_risks.append(f"Failed verification signal ({label})")
    elif ver["review_count"] > 0:
        label = ", ".join(c.replace("_", " ") for c in ver["review_checks"][:2]) or "verification"
        base_risks.append(f"Verification needs review ({label})")
    if comp_pct < 65:
        base_risks.append(f"Limited resume detail ({comp_pct}% completeness)")
    for sig in (review_signals or [])[:1]:
        clean_sig = str(sig).replace("_", " ").strip()
        if clean_sig and clean_sig not in base_risks:
            base_risks.append(clean_sig)

    base_conf = 0.55 + (0.25 if s is not None else 0.0) + (0.10 if comp_pct >= 70 else 0.0)
    if ver["has_checks"]:
        base_conf += 0.05

    decisions: dict[str, dict[str, Any]] = {}

    # 1. Balanced Hiring Manager
    if s is None:
        decisions["balanced"] = _make_decision(
            "balanced",
            "review",
            0.45,
            "Candidate has not been scored with enough information yet.",
            "Review resume manually or re-run scoring.",
            base_strengths[:2],
            base_risks[:2] or ["Score unavailable"],
        )
    elif elig == "potentially_ineligible" and s < 65:
        decisions["balanced"] = _make_decision(
            "balanced",
            "pass",
            min(0.92, base_conf),
            f"Score is {round(s)}% and mandatory requirements do not appear to be met.",
            "Do not advance unless requirements are flexible.",
            base_strengths[:2],
            base_risks[:3],
        )
    elif elig == "eligible" and s >= 80 and ver["fail_count"] == 0:
        decisions["balanced"] = _make_decision(
            "balanced",
            "strong_advance",
            min(0.95, base_conf),
            f"Strong overall match ({round(s)}%) meeting mandatory requirements with clean checks.",
            "Fast-track to hiring manager or technical interview.",
            base_strengths[:3],
            base_risks[:2],
        )
    elif elig == "eligible" and s >= 65 and ver["fail_count"] == 0:
        decisions["balanced"] = _make_decision(
            "balanced",
            "advance",
            min(0.90, base_conf),
            f"Solid match ({round(s)}%) that meets core job requirements.",
            "Schedule an initial recruiter or technical screen.",
            base_strengths[:3],
            base_risks[:2],
        )
    elif s >= 55 or (elig == "needs_review" and s >= 45):
        decisions["balanced"] = _make_decision(
            "balanced",
            "review",
            min(0.84, base_conf - 0.05),
            f"Moderate fit ({round(s)}%) with open requirement or verification questions.",
            "Review gaps and verification flags before deciding.",
            base_strengths[:2],
            base_risks[:3],
        )
    elif s >= 40:
        decisions["balanced"] = _make_decision(
            "balanced",
            "hold",
            min(0.85, base_conf - 0.05),
            f"Below target fit ({round(s)}%) compared with role requirements.",
            "Keep on hold while stronger applicants are interviewed.",
            base_strengths[:2],
            base_risks[:3],
        )
    else:
        decisions["balanced"] = _make_decision(
            "balanced",
            "pass",
            min(0.90, base_conf),
            f"Low alignment ({round(s)}%) with the role's required skills and experience.",
            "Do not advance for this position.",
            base_strengths[:1],
            base_risks[:3],
        )

    # 2. Strict Bar Raiser
    if s is None:
        decisions["bar_raiser"] = _make_decision(
            "bar_raiser",
            "hold",
            0.50,
            "Insufficient scored evidence to meet a high technical bar.",
            "Hold until complete evidence is available.",
            [],
            base_risks[:2] or ["Missing score"],
        )
    elif elig != "eligible" or ver["fail_count"] > 0:
        dec: DecisionOutcome = "pass" if (elig == "potentially_ineligible" or s < 70) else "review"
        decisions["bar_raiser"] = _make_decision(
            "bar_raiser",
            dec,
            min(0.93, base_conf),
            f"Does not clear the strict bar ({round(s)}%) due to unmet mandatory or verification flags.",
            "Verify gaps strictly before considering an interview." if dec == "review" else "Pass under strict bar criteria.",
            base_strengths[:2],
            base_risks[:3],
        )
    elif s >= 85 and (sk is None or sk >= 75) and comp_pct >= 75 and ver["review_count"] <= 1:
        decisions["bar_raiser"] = _make_decision(
            "bar_raiser",
            "strong_advance",
            min(0.95, base_conf),
            f"Exceeds the high technical bar ({round(s)}% overall) with strong skills and complete proof.",
            "Advance directly to deep technical loop.",
            base_strengths[:3],
            base_risks[:2],
        )
    elif s >= 75 and (sk is None or sk >= 65):
        decisions["bar_raiser"] = _make_decision(
            "bar_raiser",
            "advance",
            min(0.90, base_conf),
            f"Meets strict bar thresholds ({round(s)}%) with credible core skill depth.",
            "Proceed to structured technical assessment.",
            base_strengths[:3],
            base_risks[:2],
        )
    elif s >= 62:
        decisions["bar_raiser"] = _make_decision(
            "bar_raiser",
            "hold",
            min(0.86, base_conf - 0.04),
            f"Score ({round(s)}%) falls short of the strict bar threshold (75%+).",
            "Hold unless candidate demonstrates deeper role-specific proof.",
            base_strengths[:2],
            base_risks[:3] or ["Below strict bar threshold"],
        )
    else:
        decisions["bar_raiser"] = _make_decision(
            "bar_raiser",
            "pass",
            min(0.92, base_conf),
            f"Score ({round(s)}%) is well below the strict bar for this role.",
            "Do not advance under strict bar criteria.",
            base_strengths[:1],
            base_risks[:3],
        )

    # 3. Growth & Potential Scout
    potential_boost = (
            (10.0 if (sk is not None and sk >= 70) else 0.0)
            + (8.0 if (proj_match is not None and proj_match >= 65) else 0.0)
            + (6.0 if ver["external_passed"] >= 1 else 0.0)
    )
    eff_score = (s + potential_boost) if s is not None else None
    if eff_score is None:
        decisions["growth_potential"] = _make_decision(
            "growth_potential",
            "review",
            0.45,
            "Resume lacks enough scored signals to judge growth trajectory yet.",
            "Inspect projects and portfolio manually.",
            [],
            base_risks[:2],
        )
    elif ver["fail_count"] >= 2 or (elig == "potentially_ineligible" and s is not None and s < 45):
        decisions["growth_potential"] = _make_decision(
            "growth_potential",
            "pass",
            min(0.88, base_conf),
            f"Core fundamentals ({round(s or 0)}%) and required signals are too far from role needs.",
            "Do not advance; consider for a better-matched role.",
            base_strengths[:2],
            base_risks[:3],
        )
    elif eff_score >= 82 and elig != "potentially_ineligible":
        decisions["growth_potential"] = _make_decision(
            "growth_potential",
            "strong_advance",
            min(0.92, base_conf),
            f"High-upside profile ({round(s or 0)}% base score) with standout skills or hands-on projects.",
            "Prioritize for an exploratory or technical interview.",
            base_strengths[:3] or ["High growth potential signals"],
            base_risks[:2],
        )
    elif eff_score >= 62:
        decisions["growth_potential"] = _make_decision(
            "growth_potential",
            "advance",
            min(0.87, base_conf - 0.03),
            f"Promising transferable strengths ({round(s or 0)}% match) worth evaluating beyond rigid cutoffs.",
            "Run a focused screening call to test learning velocity.",
            base_strengths[:3] or ["Transferable potential"],
            base_risks[:2],
        )
    elif eff_score >= 45:
        decisions["growth_potential"] = _make_decision(
            "growth_potential",
            "review",
            min(0.80, base_conf - 0.08),
            f"Shows some potential ({round(s or 0)}% match), though key role gaps remain.",
            "Check portfolio or projects for hidden upside.",
            base_strengths[:2],
            base_risks[:3],
        )
    else:
        decisions["growth_potential"] = _make_decision(
            "growth_potential",
            "hold",
            min(0.82, base_conf - 0.05),
            f"Limited evidence of transferable skills ({round(s or 0)}%) for this position.",
            "Hold for junior or adjacent openings.",
            base_strengths[:1],
            base_risks[:3],
        )

    # 4. Verification & Risk Guard
    if ver["fail_count"] > 0 or ver["external_failed"] > 0:
        decisions["risk_guardian"] = _make_decision(
            "risk_guardian",
            "pass" if ver["fail_count"] >= 2 else "review",
            min(0.93, base_conf),
            f"Verification flagged {ver['fail_count']} failed check(s); authenticity needs scrutiny before advancing.",
            "Resolve failed verification checks before scheduling interviews.",
            base_strengths[:2],
            base_risks[:3],
        )
    elif not ver["has_checks"] or comp_pct < 60:
        decisions["risk_guardian"] = _make_decision(
            "risk_guardian",
            "review",
            min(0.82, base_conf - 0.06),
            f"Profile completeness is {comp_pct}% or verification signals are still incomplete.",
            "Run full verification checks and review resume gaps.",
            base_strengths[:2],
            base_risks[:3] or ["Incomplete verification coverage"],
        )
    elif ver["review_count"] >= 2:
        decisions["risk_guardian"] = _make_decision(
            "risk_guardian",
            "review",
            min(0.86, base_conf - 0.04),
            f"{ver['review_count']} verification signals need human review despite a {round(s or 0)}% fit score.",
            "Confirm flagged timeline or external profile items in screening.",
            base_strengths[:2],
            base_risks[:3],
        )
    elif s is not None and s >= 75 and elig == "eligible" and ver["review_count"] == 0:
        decisions["risk_guardian"] = _make_decision(
            "risk_guardian",
            "strong_advance",
            min(0.95, base_conf),
            f"Low-risk profile: {round(s)}% fit, {comp_pct}% completeness, and clean verification signals.",
            "Safe to advance directly into the interview pipeline.",
            base_strengths[:3],
            [],
        )
    elif s is not None and s >= 58 and elig != "potentially_ineligible":
        decisions["risk_guardian"] = _make_decision(
            "risk_guardian",
            "advance",
            min(0.89, base_conf),
            f"Consistent, low-risk profile ({round(s)}% fit, {comp_pct}% completeness).",
            "Advance to standard screening.",
            base_strengths[:3],
            base_risks[:2],
        )
    else:
        decisions["risk_guardian"] = _make_decision(
            "risk_guardian",
            "hold" if (s is not None and s >= 40) else "pass",
            min(0.88, base_conf),
            f"Verification is clean, but job alignment ({round(s or 0)}%) or eligibility is insufficient.",
            "Hold or pass based on role fit.",
            base_strengths[:2],
            base_risks[:3],
        )

    return decisions


def deterministic_decisions_from_row(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compute fallback agent decisions from a legacy RankingHistory row dict."""
    return deterministic_candidate_decisions(
        score=row.get("score"),
        eligibility=row.get("eligibility"),
        skills_score=row.get("skills_score"),
        data_completeness=row.get("data_completeness"),
        verification_statuses=row.get("verification_statuses") or [],
    )


async def evaluate_candidate_decisions(
        *,
        job_title: str,
        score: float | None,
        eligibility: str | None,
        skills_score: float | None,
        data_completeness: float | None,
        category_detail: dict[str, Any] | None = None,
        mandatory_results: list[dict[str, Any]] | None = None,
        review_signals: list[str] | None = None,
        verification_checks: list[dict[str, Any]] | None = None,
        ai_enabled: bool = True,
        timeout: float = 25.0,
) -> dict[str, dict[str, Any]]:
    """Run all four Decision Agents for a single candidate (DSPy/AI with deterministic fallback)."""
    verification_map = {
        str(c.get("check_type")): str(c.get("status"))
        for c in (verification_checks or [])
        if c.get("check_type") and c.get("status")
    }
    baseline = deterministic_candidate_decisions(
        score=score,
        eligibility=eligibility,
        skills_score=skills_score,
        data_completeness=data_completeness,
        verification_statuses=list(verification_map.values()),
        verification_map=verification_map,
        category_detail=category_detail,
        mandatory_results=mandatory_results,
        review_signals=review_signals,
    )
    if not ai_enabled:
        return baseline

    try:
        from app.ai_features.ai.settings import get_ai_settings
        from app.ai_features.ai.tasks import get_extractor

        ai_settings = get_ai_settings()
        if ai_settings.model in {"heuristic", "test"} or not ai_settings.model or ai_settings.offline:
            return baseline

        compact_categories = {}
        for cname, cdata in (category_detail or {}).items():
            if isinstance(cdata, dict):
                compact_categories[cname] = {
                    "status": cdata.get("status"),
                    "match_pct": _pct(cdata.get("match")),
                    "notes": (cdata.get("notes") or [])[:2],
                }

        compact_checks = [
            {
                "check": c.get("check_type"),
                "status": c.get("status"),
                "signal": str(c.get("signal") or "")[:160],
            }
            for c in (verification_checks or [])
            if isinstance(c, dict)
        ]

        payload = json.dumps(
            {
                "job_title": job_title[:160],
                "overall_score_pct": round(float(score), 1) if score is not None else None,
                "eligibility": eligibility,
                "skills_match_pct": _pct(skills_score),
                "data_completeness_pct": _pct(data_completeness),
                "categories": compact_categories,
                "mandatory_results": (mandatory_results or [])[:12],
                "review_signals": (review_signals or [])[:8],
                "verification_checks": compact_checks[:12],
                "baseline_decisions": {
                    aid: d["decision"] for aid, d in baseline.items()
                },
            },
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        extractor = get_extractor("candidate_decision_agent")
        run = await asyncio.wait_for(extractor.run(payload), timeout=timeout)
        active_model = run.model.split(",")[0] if run.model else ai_settings.model
        mode = f"{run.engine}:{active_model}"
        merged = dict(baseline)
        for item in run.output.decisions:
            if item.agent_id in AGENT_NAME_BY_ID:
                merged[item.agent_id] = _make_decision(
                    item.agent_id,
                    item.decision,
                    item.confidence,
                    item.summary,
                    item.next_step,
                    list(item.key_factors),
                    list(item.risk_flags),
                    mode=mode,
                )
        return merged
    except Exception as exc:
        logger.info(
            "Decision agent panel fell back to deterministic calibration",
            extra={"error_type": type(exc).__name__},
        )
        return baseline


def compute_threshold_outcome(
        *,
        score: float | None,
        eligibility: str | None,
        decision: str | None,
        min_accept_threshold: float | None,
        verification_statuses: list[str] | None = None,
) -> Literal["accept", "reject", "review"]:
    """Derive Accept / Reject / Review outcome against a configurable minimum fitness threshold.

    When `min_accept_threshold` is explicitly supplied by the recruiter, the numeric score threshold
    is authoritative (subject only to mandatory eligibility and failed-verification guardrails).
    """
    if score is None:
        return "review"
    ver = list(verification_statuses or [])
    if eligibility == "potentially_ineligible":
        return "reject"

    if min_accept_threshold is not None:
        threshold = float(min_accept_threshold)
        if float(score) >= threshold:
            # Guardrail: never auto-accept if a verification check explicitly failed
            if "failed" in ver:
                return "review"
            return "accept"
        return "reject"

    # Default mode (no explicit recruiter threshold): combine 65% baseline with agent verdict
    default_threshold = 65.0
    if "failed" in ver and decision in {"review", "hold", "pass"}:
        return "reject" if decision == "pass" else "review"
    if decision == "pass":
        return "reject"
    if float(score) >= default_threshold and eligibility == "eligible" and decision in {"strong_advance", "advance"}:
        return "accept"
    if float(score) < max(0.0, default_threshold - 15.0) or decision == "hold":
        return "reject"
    return "review"


def attach_active_decision(
        row: dict[str, Any],
        agent_id: str | None = None,
        min_accept_threshold: float | None = None,
) -> dict[str, Any]:
    """Ensure a ranked row has `agent_decisions` and sets `decision` for the chosen agent."""
    out = dict(row)
    selected_agent = normalize_agent_id(agent_id)
    agent_decisions = out.get("agent_decisions")
    if not isinstance(agent_decisions, dict) or not agent_decisions:
        agent_decisions = deterministic_decisions_from_row(out)
        out["agent_decisions"] = agent_decisions
    if min_accept_threshold is not None:
        enriched: dict[str, Any] = {}
        for aid, dec in agent_decisions.items():
            if isinstance(dec, dict):
                d_copy = dict(dec)
                d_copy["threshold_outcome"] = compute_threshold_outcome(
                    score=out.get("score"),
                    eligibility=out.get("eligibility"),
                    decision=d_copy.get("decision"),
                    min_accept_threshold=min_accept_threshold,
                    verification_statuses=out.get("verification_statuses"),
                )
                enriched[aid] = d_copy
        out["agent_decisions"] = enriched
        agent_decisions = enriched
    else:
        for dec in agent_decisions.values():
            if isinstance(dec, dict) and not dec.get("threshold_outcome"):
                dec["threshold_outcome"] = compute_threshold_outcome(
                    score=out.get("score"),
                    eligibility=out.get("eligibility"),
                    decision=dec.get("decision"),
                    min_accept_threshold=None,
                    verification_statuses=out.get("verification_statuses"),
                )
    active = agent_decisions.get(selected_agent) or next(iter(agent_decisions.values()), None)
    out["decision"] = active
    return out
