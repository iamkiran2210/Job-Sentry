"""
Cautious identity matching. Auto-link ONLY when exactly one existing candidate shares the same
normalized email and the names do not conflict. Everything else becomes a review suggestion.
Pure functions, no DB access.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir"}


def normalize_email(v: str | None) -> str | None:
    v = (v or "").strip().lower()
    return v if _EMAIL_RE.match(v) else None


def normalize_phone(v: str | None) -> str | None:
    d = re.sub(r"\D", "", v or "")
    return d[-10:] if len(d) >= 7 else None  # compare national number, ignore country prefix


def normalize_name(v: str | None) -> str | None:
    if not v:
        return None
    s = unicodedata.normalize("NFKD", v)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    toks = [t for t in re.findall(r"[a-z0-9']+", s) if t not in _HONORIFICS]
    return " ".join(toks) or None


@dataclass(frozen=True)
class Signals:
    name: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class CandidateSnapshot:
    id: uuid.UUID
    name: str | None
    email: str | None
    phone: str | None
    applied_to_job: bool


@dataclass
class Suggestion:
    other_candidate_id: uuid.UUID
    strength: str  # "strong" | "weak"
    reasons: list[str]


@dataclass
class IdentityDecision:
    action: str  # "link_existing" | "create_new"
    candidate_id: uuid.UUID | None = None
    suggestions: list[Suggestion] = field(default_factory=list)


def name_relation(a: str | None, b: str | None) -> str:
    if not a or not b:
        return "unknown"
    if a == b:
        return "exact"
    ta, tb = set(a.split()), set(b.split())
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 2 and small <= big:  # "john smith" vs "john a smith"
        return "compatible"
    if SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() >= 0.85:
        return "similar"
    return "conflict"


def decide(
        signals: Signals, candidates: list[CandidateSnapshot], max_suggestions: int = 5
) -> IdentityDecision:
    strong: list[tuple[CandidateSnapshot, list[str]]] = []
    weak: list[Suggestion] = []
    for c in candidates:
        rel = name_relation(signals.name, c.name)
        email = bool(signals.email and signals.email == c.email)
        phone = bool(signals.phone and signals.phone == c.phone)
        if email and rel != "conflict":
            strong.append((c, ["email_match", f"name_{rel}"] + (["phone_match"] if phone else [])))
        elif email:
            weak.append(Suggestion(c.id, "weak", ["email_match", "name_conflict"]))
        elif phone:
            weak.append(Suggestion(c.id, "weak", ["phone_match", f"name_{rel}"]))
        elif rel == "exact" and len(signals.name.split()) >= 2:
            weak.append(Suggestion(c.id, "weak", ["name_match_only"]))

    if len(strong) == 1 and not strong[0][0].applied_to_job:
        c, _ = strong[0]
        return IdentityDecision("link_existing", c.id, weak[:max_suggestions])
    sugg = [
        Suggestion(
            c.id,
            "strong",
            reasons
            + (
                ["same_job_resubmission"]
                if c.applied_to_job
                else ["ambiguous_multiple_matches"]
                if len(strong) > 1
                else []
            ),
        )
        for c, reasons in strong
    ]
    return IdentityDecision("create_new", None, (sugg + weak)[:max_suggestions])
