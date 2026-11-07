"""Pure deterministic category formulas. Inputs are allowlisted extracted claims."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

D = Decimal


@dataclass(frozen=True)
class CategoryResult:
    category: str
    status: str
    match: Decimal | None
    weight: Decimal
    weighted_contribution: Decimal | None
    components: dict[str, Decimal | int | str | None]
    evidence_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AggregateResult:
    total_score: Decimal | None
    score_lower_bound: Decimal | None
    score_upper_bound: Decimal | None
    data_completeness: Decimal
    eligibility: str
    review_signals: tuple[str, ...]


def aggregate(categories: list[CategoryResult], mandatory_results: list[dict], completeness_threshold: Decimal = D("0.60")) -> AggregateResult:
    """Aggregate category results with fixed Decimal arithmetic."""
    ordered = sorted(categories, key=lambda c: c.category)
    applicable = [c for c in ordered if c.status != "not_applicable"]
    known = [c for c in applicable if c.status == "known" and c.match is not None]
    w_app = sum((c.weight for c in applicable), D(0)); w_known = sum((c.weight for c in known), D(0))
    known_sum = sum((c.weight * c.match for c in known), D(0))
    unknown_sum = sum((c.weight for c in applicable if c.status == "unknown"), D(0))
    total = (D(100) * known_sum / w_known).quantize(D("0.01"), rounding=ROUND_HALF_UP) if w_known else None
    lower = (D(100) * known_sum / w_app).quantize(D("0.01"), rounding=ROUND_HALF_UP) if w_app else None
    upper = (D(100) * (known_sum + unknown_sum) / w_app).quantize(D("0.01"), rounding=ROUND_HALF_UP) if w_app else None
    completeness = (w_known / w_app).quantize(D("0.001"), rounding=ROUND_HALF_UP) if w_app else D(0)
    statuses = {r.get("status") for r in mandatory_results}
    eligibility = "potentially_ineligible" if "not_met" in statuses else "needs_review" if "unknown" in statuses or total is None else "eligible"
    signals = []
    if total is None or completeness < completeness_threshold: signals.append("low_data_completeness")
    if "not_met" in statuses: signals.append("mandatory_not_met")
    if "unknown" in statuses: signals.append("mandatory_unknown")
    return AggregateResult(total, lower, upper, completeness, eligibility, tuple(signals))


def _result(category, match, weight, components=None, evidence=(), notes=(), status=None):
    q = D(str(match)).quantize(D("0.0001"), rounding=ROUND_HALF_UP) if match is not None else None
    state = status or ("known" if q is not None else "unknown")
    contribution = q * D(str(weight)) if q is not None else None
    return CategoryResult(category, state, q, D(str(weight)), contribution, components or {}, tuple(sorted(evidence)), tuple(sorted(set(notes))))


def skills_result(requirements: list[dict], credits: dict[str, tuple[Decimal | None, str | None]], weight: Decimal) -> CategoryResult:
    if not requirements:
        return _result("skills", None, weight, status="not_applicable")
    numerator = denominator = D(0); used = []
    for req in sorted(requirements, key=lambda r: str(r.get("id", r.get("name", "")))):
        key = str(req.get("id", req.get("name", "")))
        credit, evidence_id = credits.get(key, (None, None))
        if credit is None:
            continue
        rw = D(2) if req.get("is_mandatory") or req.get("requirement_type") == "mandatory" else D(1)
        numerator += rw * D(credit); denominator += rw
        if evidence_id: used.append(evidence_id)
    if not denominator:
        return _result("skills", None, weight, {"requirements_known": 0}, status="unknown")
    return _result("skills", numerator / denominator, weight, {"requirements_known": int(denominator)}, used)


def _month(value: Any):
    if not value: return None
    try:
        parts = str(value).split("-"); y = int(parts[0]); m = int(parts[1]) if len(parts) > 1 else 1
        return (y, m) if 1 <= m <= 12 else None
    except (ValueError, TypeError, IndexError): return None


def merged_relevant_years(entries: list[dict], relevances: dict[str, Decimal | None], as_of: date, relevance_min: Decimal = D("0.25")) -> Decimal:
    intervals = []
    today = (as_of.year, as_of.month)
    for row in sorted(entries, key=lambda e: str(e.get("id", ""))):
        rid = str(row.get("id", "")); rel = relevances.get(rid)
        if rel is None or D(rel) < relevance_min: continue
        start = _month(row.get("start_date")); end = _month(row.get("end_date")) or (today if row.get("is_current") or not row.get("end_date") else None)
        if start and end and end >= start:
            intervals.append((start[0]*12+start[1], end[0]*12+end[1]))
    intervals.sort(); merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else: merged.append((start, end))
    months = sum(end-start+1 for start, end in merged)
    return D(months) / D(12)


def experience_result(entries: list[dict], relevance: dict[str, Decimal | None], required_years: Decimal | None, as_of: date, weight: Decimal, years_component_weight: Decimal = D("0.5"), relevance_min: Decimal = D("0.25")) -> CategoryResult:
    known_rel = [(str(x.get("id", "")), D(relevance[str(x.get("id", ""))])) for x in entries if relevance.get(str(x.get("id", ""))) is not None]
    rel_score = sum((r for _, r in known_rel), D(0))/len(known_rel) if known_rel else None
    years_fit = None; years = None
    if required_years is not None and D(required_years) > 0:
        years = merged_relevant_years(entries, relevance, as_of, relevance_min)
        years_fit = min(years/D(required_years), D(1))
    if years_fit is None and rel_score is None: return _result("experience", None, weight, {"years_fit": None, "relevance": None, "relevant_years": years, "required_years": required_years})
    notes = []
    if years_fit is None: match = rel_score
    elif rel_score is None: match = years_fit; notes.append("partial_experience_evidence")
    else: match = years_component_weight*years_fit + (D(1)-years_component_weight)*rel_score
    return _result("experience", match, weight, {"years_fit": years_fit, "relevance": rel_score, "relevant_years": years, "required_years": required_years}, [i for i, _ in known_rel], notes)


def projects_result(projects: list[dict], relevance: dict[str, Decimal | None], weight: Decimal, top_n: int = 3) -> CategoryResult:
    known = sorted(((D(relevance[str(p.get("id", ""))]), str(p.get("id", ""))) for p in projects if relevance.get(str(p.get("id", ""))) is not None), key=lambda x: (-x[0], x[1]))[:top_n]
    if not known: return _result("projects", None, weight, {"top_n_used": 0, "mean": None, "ids_used": []})
    mean = sum((v for v, _ in known), D(0))/len(known)
    notes = ("fewer_than_n_projects",) if len(known) < top_n else ()
    return _result("projects", mean, weight, {"top_n_used": len(known), "mean": mean, "ids_used": [i for _, i in known]}, [i for _, i in known], notes)


def education_result(degrees: list[str], required: str | None, level_map: dict[str, int], weight: Decimal) -> CategoryResult:
    if required is None: return _result("education", None, weight, status="not_applicable")
    norm = lambda x: "".join(ch for ch in x.casefold() if ch.isalnum())
    levels = {norm(k): int(v) for k, v in level_map.items()}
    req_level = levels.get(norm(required)); cand = [levels[norm(x)] for x in degrees if norm(x) in levels]
    if req_level is None: return _result("education", None, weight, {"required_level": None}, notes=("unrecognized_degree",))
    if not cand: return _result("education", None, weight, {"required_level": req_level}, notes=("unrecognized_degree",) if degrees else ())
    gap = max(cand)-req_level
    match = D(1) if gap >= 0 else D("0.5") if gap == -1 else D(0)
    return _result("education", match, weight, {"candidate_level": max(cand), "required_level": req_level, "gap": gap})


def certifications_result(required: list[dict], held: list[dict], aliases: dict[str, str], weight: Decimal, as_of: date) -> CategoryResult:
    if not required: return _result("certifications", None, weight, status="not_applicable")
    norm = lambda x: "".join(ch for ch in str(x).casefold() if ch.isalnum())
    amap = {norm(k): norm(v) for k, v in aliases.items()}
    canon = lambda x: amap.get(norm(x), norm(x))
    candidates = {}
    notes = []
    for cert in held:
        name = cert.get("name", "")
        expiry = _month(cert.get("expiry_date"))
        if expiry and expiry < (as_of.year, as_of.month):
            notes.append("cert_expired"); continue
        if not cert.get("expiry_date"): notes.append("cert_expiry_unknown")
        candidates[canon(name)] = cert
    if not candidates: return _result("certifications", None, weight, {"requirements_known": 0}, notes=notes)
    numerator = denominator = D(0); used = []
    for req in sorted(required, key=lambda r: str(r.get("id", r.get("name", "")))):
        rw = D(2) if req.get("is_mandatory") or req.get("requirement_type") == "mandatory" else D(1)
        denominator += rw
        if canon(req.get("name", "")) in candidates:
            numerator += rw; used.append(str(req.get("id", req.get("name", ""))))
    return _result("certifications", numerator/denominator if denominator else None, weight, {"matched_weight": numerator, "listed_weight": denominator}, used, notes)


# Stable names consumed by the scoring orchestration layer.
score_skills = skills_result
score_experience = experience_result
score_projects = projects_result
score_education = education_result
score_certifications = certifications_result
