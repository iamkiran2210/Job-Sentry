"""Pure deterministic category formulas. Inputs are allowlisted extracted claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

D = Decimal
CATEGORIES = ("skills", "experience", "projects", "education", "certifications")

_MONTH_NAMES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_DEGREE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "doctorate",
        re.compile(r"\b(?:ph\.?\s*d\.?|doctorate|doctoral|d\.?\s*phil|doctor\s+of)\b", re.I),
    ),
    (
        "master",
        re.compile(
            r"\b(?:master(?:'?s)?|m\.?\s*sc\.?|m\.?\s*s\.?|m\.?\s*tech\.?|m\.?\s*e\.?|m\.?\s*eng\.?|mba|m\.?\s*b\.?\s*a\.?|m\.?\s*a\.?|mca|post[\s-]?grad\w*)\b",
            re.I,
        ),
    ),
    (
        "bachelor",
        re.compile(
            r"\b(?:bachelor(?:'?s)?|b\.?\s*sc\.?|b\.?\s*s\.?|b\.?\s*tech\.?|b\.?\s*e\.?|b\.?\s*eng\.?|b\.?\s*a\.?|bca|b\.?\s*com\.?|undergrad\w*|4[\s-]?year\s+degree)\b",
            re.I,
        ),
    ),
    (
        "associate",
        re.compile(r"\b(?:associate(?:'?s)?|a\.?\s*s\.?|a\.?\s*a\.?|polytechnic|diploma\s+in)\b", re.I),
    ),
    (
        "high_school",
        re.compile(r"\b(?:high\s+school|secondary\s+school|ged|hsc|12th|matriculation)\b", re.I),
    ),
)

_CERT_STOPWORDS = frozenset(
    {"certified", "certification", "certificate", "professional", "exam", "the", "of", "in", "for", "and", "a", "an"})


def normalize_category(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).casefold()
    return {
        "certification": "certifications",
        "project": "projects",
        "responsibility": "projects",
        "language": "skills",
        "other": "skills",
    }.get(text, text)


def resolve_education_level(value: str, level_map: dict[str, int]) -> int | None:
    if not value or not str(value).strip():
        return None
    norm = lambda x: "".join(ch for ch in str(x).casefold() if ch.isalnum())
    levels = {norm(k): int(v) for k, v in level_map.items()}
    aliases = {
        "btech": "bachelor",
        "be": "bachelor",
        "bsc": "bachelor",
        "bs": "bachelor",
        "ba": "bachelor",
        "beng": "bachelor",
        "bca": "bachelor",
        "bcom": "bachelor",
        "mtech": "master",
        "ms": "master",
        "msc": "master",
        "mba": "master",
        "meng": "master",
        "mca": "master",
        "ma": "master",
        "phd": "doctorate",
        "phddegree": "doctorate",
        "highschool": "highschool",
        "highschooldiploma": "highschool",
        "ged": "highschool",
    }
    key = norm(value)
    direct = levels.get(aliases.get(key, key))
    if direct is not None:
        return direct
    text = str(value)
    for canonical_name, pattern in _DEGREE_PATTERNS:
        if pattern.search(text):
            resolved = levels.get(norm(canonical_name))
            if resolved is not None:
                return resolved
    return None


def certification_matches(req_name: str, held_name: str, aliases: dict[str, str] | None = None) -> bool:
    aliases = aliases or {}
    norm = lambda x: "".join(ch for ch in str(x).casefold() if ch.isalnum())
    amap = {norm(k): norm(v) for k, v in aliases.items()}
    canon = lambda x: amap.get(norm(x), norm(x))
    req_c = canon(req_name)
    held_c = canon(held_name)
    if not req_c or not held_c:
        return False
    if req_c == held_c:
        return True
    if len(req_c) >= 4 and (req_c in held_c or held_c in req_c):
        return True
    toks = lambda s: {
        t
        for t in re.findall(r"[a-z0-9+#]+", str(s).casefold())
        if t not in _CERT_STOPWORDS and len(t) >= 2
    }
    rt = toks(req_name)
    ht = toks(held_name)
    if rt and ht:
        overlap = len(rt & ht)
        if rt <= ht or (overlap >= 2 and overlap / len(rt) >= 0.7):
            return True
    return False


def validate_weights(weights: dict[str, Decimal | float | str]) -> dict[str, Decimal]:
    """Return stable Decimal weights or reject an invalid scoring configuration."""
    converted = {key: D(str(value)) for key, value in sorted(weights.items())}
    if (
            tuple(sorted(converted)) != tuple(sorted(CATEGORIES))
            or any(value < 0 for value in converted.values())
            or sum(converted.values(), D(0)) != D("1")
    ):
        raise ValueError(
            "Category weights must contain all categories, be non-negative and sum to 1.0"
        )
    return converted


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


@dataclass(frozen=True)
class MandatoryEvaluation:
    results: tuple[dict, ...]
    eligibility: str
    review_signals: tuple[str, ...]


def evaluate_mandatory(requirements: list[dict], evidence_rows: list) -> MandatoryEvaluation:
    results = []
    trusted = {
        "exact_skill_match",
        "alias_skill_match",
        "exact",
        "alias",
        "rule",
        "rule_based_match",
    }
    for req in sorted(
            (
                    r
                    for r in requirements
                    if r.get("is_mandatory") or r.get("requirement_type") == "mandatory"
            ),
            key=lambda r: str(r.get("id", "")),
    ):
        name = str(req.get("name", "")).casefold()
        req_category = normalize_category(req.get("category"))
        related = [
            e
            for e in evidence_rows
            if getattr(e, "value", None) is not None
               and str(getattr(e, "requirement_term", "")).casefold() == name
        ]
        met = [
            e
            for e in related
            if getattr(e, "signal_type", "") in trusted and float(getattr(e, "value", 0)) > 0
        ]
        known = [
            e
            for e in evidence_rows
            if normalize_category(getattr(e, "category", None)) == req_category
               and getattr(e, "value", None) is not None
        ]
        status = "met" if met else "not_met" if known else "unknown"
        results.append(
            {
                "requirement_id": str(req.get("id", name)),
                "requirement_name": str(req.get("name", "")),
                "status": status,
                "evidence_ids": sorted(str(e.evidence_id) for e in met),
            }
        )
    statuses = {r["status"] for r in results}
    eligibility = (
        "potentially_ineligible"
        if "not_met" in statuses
        else "needs_review"
        if "unknown" in statuses
        else "eligible"
    )
    signals = tuple(
        x
        for x in (
            "mandatory_not_met" if "not_met" in statuses else None,
            "mandatory_unknown" if "unknown" in statuses else None,
        )
        if x
    )
    return MandatoryEvaluation(tuple(results), eligibility, signals)


def aggregate(
        categories: list[CategoryResult],
        mandatory_results: list[dict],
        completeness_threshold: Decimal = D("0.60"),
) -> AggregateResult:
    """Aggregate category results with fixed Decimal arithmetic."""
    ordered = sorted(categories, key=lambda c: c.category)
    applicable = [c for c in ordered if c.status != "not_applicable"]
    known = [c for c in applicable if c.status == "known" and c.match is not None]
    w_app = sum((c.weight for c in applicable), D(0))
    w_known = sum((c.weight for c in known), D(0))
    known_sum = sum((c.weight * c.match for c in known), D(0))
    unknown_sum = sum((c.weight for c in applicable if c.status == "unknown"), D(0))
    total = (
        (D(100) * known_sum / w_known).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        if w_known
        else None
    )
    lower = (
        (D(100) * known_sum / w_app).quantize(D("0.01"), rounding=ROUND_HALF_UP) if w_app else None
    )
    upper = (
        (D(100) * (known_sum + unknown_sum) / w_app).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        if w_app
        else None
    )
    completeness = (w_known / w_app).quantize(D("0.001"), rounding=ROUND_HALF_UP) if w_app else D(0)
    statuses = {r.get("status") for r in mandatory_results}
    eligibility = (
        "potentially_ineligible"
        if "not_met" in statuses
        else "needs_review"
        if "unknown" in statuses or total is None
        else "eligible"
    )
    signals = []
    if total is None or completeness < completeness_threshold:
        signals.append("low_data_completeness")
    if "not_met" in statuses:
        signals.append("mandatory_not_met")
    if "unknown" in statuses:
        signals.append("mandatory_unknown")
    return AggregateResult(total, lower, upper, completeness, eligibility, tuple(signals))


def _result(category, match, weight, components=None, evidence=(), notes=(), status=None):
    raw = D(str(match)) if match is not None else None
    q = (
        max(D(0), min(D(1), raw)).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
        if raw is not None
        else None
    )
    state = status or ("known" if q is not None else "unknown")
    contribution = q * D(str(weight)) if q is not None else None
    return CategoryResult(
        category,
        state,
        q,
        D(str(weight)),
        contribution,
        components or {},
        tuple(sorted(evidence)),
        tuple(sorted(set(notes))),
    )


def skills_result(
        requirements: list[dict], credits: dict[str, tuple[Decimal | None, str | None]], weight: Decimal
) -> CategoryResult:
    if not requirements:
        return _result("skills", None, weight, status="not_applicable")
    is_mand = lambda r: bool(r.get("is_mandatory") or r.get("requirement_type") == "mandatory")
    pref_weights = [
        D(str(r["weight"]))
        for r in requirements
        if not is_mand(r) and r.get("weight") is not None and D(str(r["weight"])) > 0
    ]
    pref_sum = sum(pref_weights, D(0))
    pref_count = len(pref_weights)

    numerator = denominator = D(0)
    used = []
    known_count = 0
    for req in sorted(requirements, key=lambda r: str(r.get("id", r.get("name", "")))):
        key = str(req.get("id", req.get("name", "")))
        credit, evidence_id = credits.get(key, (None, None))
        if credit is None:
            continue
        known_count += 1
        if is_mand(req):
            rw = D(2)
        elif req.get("weight") is not None and D(str(req["weight"])) > 0 and pref_sum > 0:
            rw = (D(str(req["weight"])) / pref_sum) * D(pref_count)
        else:
            rw = D(1)
        numerator += rw * max(D(0), min(D(1), D(credit)))
        denominator += rw
        if evidence_id:
            used.append(evidence_id)
    if not denominator:
        return _result("skills", None, weight, {"requirements_known": 0}, status="unknown")
    return _result(
        "skills", numerator / denominator, weight, {"requirements_known": known_count}, used
    )


def _month(value: Any):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parts = text.split("-")
        y = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 1
        return (y, m) if 1900 <= y <= 2200 and 1 <= m <= 12 else None
    except (ValueError, TypeError, IndexError):
        pass
    # Handle MM/YYYY or YYYY/MM
    m_slash = re.match(r"^(\d{1,2})/(\d{4})$", text)
    if m_slash:
        mm, yy = int(m_slash.group(1)), int(m_slash.group(2))
        if 1 <= mm <= 12 and 1900 <= yy <= 2200:
            return (yy, mm)
    y_slash = re.match(r"^(\d{4})/(\d{1,2})$", text)
    if y_slash:
        yy, mm = int(y_slash.group(1)), int(y_slash.group(2))
        if 1 <= mm <= 12 and 1900 <= yy <= 2200:
            return (yy, mm)
    # Handle "Jan 2020" / "January 2020"
    m_word = re.match(r"^([a-zA-Z]+)\.?\s+(\d{4})$", text)
    if m_word:
        mm = _MONTH_NAMES.get(m_word.group(1).casefold())
        yy = int(m_word.group(2))
        if mm and 1900 <= yy <= 2200:
            return (yy, mm)
    return None


def merged_relevant_years(
        entries: list[dict],
        relevances: dict[str, Decimal | None],
        as_of: date,
        relevance_min: Decimal = D("0.25"),
) -> Decimal:
    intervals = []
    claimed_fallback = D(0)
    today = (as_of.year, as_of.month)
    for row in sorted(entries, key=lambda e: str(e.get("id", ""))):
        rid = str(row.get("id", ""))
        rel = relevances.get(rid)
        if rel is None or D(rel) < relevance_min:
            continue
        start = _month(row.get("start_date"))
        end = _month(row.get("end_date")) or (
            today if row.get("is_current") or not row.get("end_date") else None
        )
        if start and end and end >= start:
            intervals.append((start[0] * 12 + start[1], end[0] * 12 + end[1]))
        elif row.get("claimed_years") is not None:
            try:
                cy = D(str(row["claimed_years"]))
                if cy > claimed_fallback:
                    claimed_fallback = cy
            except Exception:
                pass
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    months = sum(end - start + 1 for start, end in merged)
    if months > 0:
        return D(months) / D(12)
    return claimed_fallback


def experience_result(
        entries: list[dict],
        relevance: dict[str, Decimal | None],
        required_years: Decimal | None,
        as_of: date,
        weight: Decimal,
        years_component_weight: Decimal = D("0.5"),
        relevance_min: Decimal = D("0.25"),
) -> CategoryResult:
    if not entries:
        return _result(
            "experience",
            None,
            weight,
            {
                "years_fit": None,
                "relevance": None,
                "relevant_years": None,
                "required_years": required_years,
            },
        )
    known_rel = [
        (str(x.get("id", "")), D(relevance[str(x.get("id", ""))]))
        for x in entries
        if relevance.get(str(x.get("id", ""))) is not None
    ]
    rel_score = sum((r for _, r in known_rel), D(0)) / len(known_rel) if known_rel else None
    years_fit = None
    years = None
    if required_years is not None and D(required_years) > 0 and known_rel:
        years = merged_relevant_years(entries, relevance, as_of, relevance_min)
        years_fit = min(years / D(required_years), D(1))
    if years_fit is None and rel_score is None:
        return _result(
            "experience",
            None,
            weight,
            {
                "years_fit": None,
                "relevance": None,
                "relevant_years": years,
                "required_years": required_years,
            },
        )
    notes = []
    if years_fit is None:
        match = rel_score
        if rel_score is not None:
            notes.append("partial_experience_evidence")
    elif rel_score is None:
        match = years_fit
        notes.append("partial_experience_evidence")
    else:
        match = years_component_weight * years_fit + (D(1) - years_component_weight) * rel_score
    return _result(
        "experience",
        match,
        weight,
        {
            "years_fit": years_fit,
            "relevance": rel_score,
            "relevant_years": years,
            "required_years": required_years,
        },
        [i for i, _ in known_rel],
        notes,
    )


def projects_result(
        projects: list[dict], relevance: dict[str, Decimal | None], weight: Decimal, top_n: int = 3
) -> CategoryResult:
    known = sorted(
        (
            (D(relevance[str(p.get("id", ""))]), str(p.get("id", "")))
            for p in projects
            if relevance.get(str(p.get("id", ""))) is not None
        ),
        key=lambda x: (-x[0], x[1]),
    )[:top_n]
    if not known:
        return _result(
            "projects",
            None,
            weight,
            {"top_n_used": 0, "mean": None, "ids_used": []},
            notes=("fewer_than_n_projects",),
        )
    mean = sum((v for v, _ in known), D(0)) / len(known)
    notes = ("fewer_than_n_projects",) if len(known) < top_n else ()
    return _result(
        "projects",
        mean,
        weight,
        {"top_n_used": len(known), "mean": mean, "ids_used": [i for _, i in known]},
        [i for _, i in known],
        notes,
    )


def education_result(
        degrees: list[str], required: str | None, level_map: dict[str, int], weight: Decimal
) -> CategoryResult:
    if required is None:
        return _result("education", None, weight, status="not_applicable")
    req_level = resolve_education_level(required, level_map)
    cand = [level for x in degrees if (level := resolve_education_level(x, level_map)) is not None]
    if req_level is None:
        return _result(
            "education", None, weight, {"required_level": None}, notes=("unrecognized_degree",)
        )
    if not cand:
        return _result(
            "education",
            None,
            weight,
            {"required_level": req_level},
            notes=("unrecognized_degree",) if degrees else (),
        )
    gap = max(cand) - req_level
    match = D(1) if gap >= 0 else D("0.5") if gap == -1 else D(0)
    return _result(
        "education",
        match,
        weight,
        {"candidate_level": max(cand), "required_level": req_level, "gap": gap},
    )


def certifications_result(
        required: list[dict], held: list[dict], aliases: dict[str, str], weight: Decimal, as_of: date
) -> CategoryResult:
    if not required:
        return _result("certifications", None, weight, status="not_applicable")
    valid_held: list[dict] = []
    notes = []
    for cert in held:
        expiry = _month(cert.get("expiry_date"))
        if expiry and expiry < (as_of.year, as_of.month):
            notes.append("cert_expired")
            continue
        if not cert.get("expiry_date"):
            notes.append("cert_expiry_unknown")
        valid_held.append(cert)
    if not held:
        return _result("certifications", None, weight, {"requirements_known": 0}, notes=notes)
    numerator = denominator = D(0)
    used = []
    for req in sorted(required, key=lambda r: str(r.get("id", r.get("name", "")))):
        rw = D(2) if req.get("is_mandatory") or req.get("requirement_type") == "mandatory" else D(1)
        denominator += rw
        req_name = str(req.get("name", ""))
        if any(certification_matches(req_name, str(c.get("name", "")), aliases) for c in valid_held):
            numerator += rw
            used.append(str(req.get("id", req_name)))
    return _result(
        "certifications",
        numerator / denominator if denominator else None,
        weight,
        {"matched_weight": numerator, "listed_weight": denominator},
        used,
        notes,
    )


# Stable names consumed by the scoring orchestration layer.
score_skills = skills_result
score_experience = experience_result
score_projects = projects_result
score_education = education_result
score_certifications = certifications_result
