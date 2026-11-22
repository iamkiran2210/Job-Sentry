"""Scoring for resume extraction. Rewards correct items, penalises wrong/extra ones (precision) and any
value that is not traceable to the source text (fabrication)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai_features.schemas.resume_extraction import ExtractedProfileData


@dataclass
class Score:
    total: float
    fields: dict[str, float] = field(default_factory=dict)
    fabricated: bool = False


def _f1(gold: set[str], pred: set[str]) -> float:
    if not gold and not pred:
        return 1.0
    if not gold or not pred:
        return 0.0
    tp = len(gold & pred)
    p, r = tp / len(pred), tp / len(gold)
    return 0.0 if tp == 0 else 2 * p * r / (p + r)


def _n(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").casefold()).strip()


def _digits(s: str | None) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:]


def score_profile(gold: dict[str, Any], pred: ExtractedProfileData, source_text: str) -> Score:
    from app.ai_features.resumes.grounding import (
        ground_profile,
    )  # fabrication check shared with production

    f: dict[str, float] = {
        "name": float(_n(pred.full_name.value) == _n(gold.get("full_name"))),
        "email": float(_n(pred.contact.email.value) == _n(gold.get("email"))),
        "phone": float(_digits(pred.contact.phone.value) == _digits(gold.get("phone"))),
        "skills": _f1({_n(s) for s in gold.get("skills", [])}, {_n(s.name) for s in pred.skills}),
        "employment": _f1(
            {(_n(e["company"]), _n(e["title"])) for e in gold.get("employment", [])},
            {(_n(e.company), _n(e.title)) for e in pred.employment},
        ),
        "education": _f1(
            {_n(x) for x in gold.get("education", [])},
            {_n(e.institution) for e in pred.education if e.institution},
        ),
        "certifications": _f1(
            {_n(x) for x in gold.get("certifications", [])},
            {_n(c.name) for c in pred.certifications},
        ),
        "projects": _f1(
            {_n(x) for x in gold.get("projects", [])},
            {_n(p.name) for p in pred.projects},
        ),
    }
    _, warnings = ground_profile(pred.model_copy(deep=True), source_text)
    fabricated = any("removed" in w for w in warnings)
    total = sum(f.values()) / len(f) * (0.5 if fabricated else 1.0)
    return Score(round(total, 4), f, fabricated)
