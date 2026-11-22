"""
Anti-fabrication guard. After the model answers, every identifying value must be traceable to the source
text; anything that is not gets removed (not "corrected"), and evidence quotes that are not really in the
document are cleared and their confidence capped. Text-matching helpers are shared with the AI layer.
"""

from __future__ import annotations

import re

from app.ai_features.ai.grounding import Haystack
from app.ai_features.schemas.resume_extraction import ExtractedProfileData, Sourced


def ground_profile(
        profile: ExtractedProfileData, text: str
) -> tuple[ExtractedProfileData, list[str]]:
    hay = Haystack(text)
    warnings: list[str] = []
    cleared = 0

    def check_evidence(item) -> None:
        nonlocal cleared
        ev = getattr(item, "evidence", None)
        if not ev:
            return
        if hay.has(ev):
            return
        # On 2-column / OCR-extracted resumes, valid quotes may span a column break or minor OCR glyph.
        toks = [t for t in re.findall(r"\w+", ev.casefold()) if len(t) >= 3]
        if len(toks) >= 3 and hay.has_loose(ev, threshold=0.75):
            return
        item.evidence = None
        item.confidence = min(item.confidence if item.confidence is not None else 0.4, 0.4)
        cleared += 1

    def drop(sourced: Sourced, label: str) -> None:
        warnings.append(f"{label} was not found in the document and was removed.")
        sourced.value = sourced.evidence = sourced.confidence = None

    # name
    n = profile.full_name
    if n.value and not all(hay.has(t) for t in re.findall(r"\w{2,}", n.value)):
        drop(n, "full_name")
    # contact
    c = profile.contact
    if c.email.value and not hay.has(c.email.value):
        drop(c.email, "contact.email")
    if c.phone.value and not hay.has_phone(c.phone.value):
        drop(c.phone, "contact.phone")
    for label in ("linkedin_url", "github_url", "portfolio_url"):
        s: Sourced = getattr(c, label)
        if s.value and not hay.has_url(s.value):
            drop(s, f"contact.{label}")
    if c.location.value and not hay.has_loose(c.location.value):
        drop(c.location, "contact.location")
    for s in (n, *vars(c).values()):
        if isinstance(s, Sourced) and s.value:
            check_evidence(s)

    # list items: keep only what is traceable to the document
    def keep(items, test, label):
        kept = [i for i in items if test(i)]
        if len(kept) != len(items):
            warnings.append(
                f"{len(items) - len(kept)} {label} item(s) not found in the document were removed."
            )
        for i in kept:
            check_evidence(i)
        return kept

    profile.skills = keep(
        profile.skills,
        lambda s: hay.has(s.name) or (s.evidence and hay.has(s.evidence)),
        "skill",
    )
    profile.employment = keep(
        profile.employment,
        lambda e: hay.has_loose(e.company) or hay.has_loose(e.title),
        "employment",
    )
    profile.education = keep(
        profile.education,
        lambda e: hay.has_loose(e.institution) or hay.has_loose(e.degree),
        "education",
    )
    profile.certifications = keep(
        profile.certifications, lambda x: hay.has_loose(x.name), "certification"
    )
    profile.projects = keep(profile.projects, lambda p: hay.has_loose(p.name), "project")
    profile.experience_claims = keep(
        profile.experience_claims,
        lambda x: x.evidence is not None and hay.has(x.evidence) or hay.has_loose(x.statement),
        "experience claim",
    )
    if cleared:
        warnings.append(
            f"{cleared} evidence quote(s) could not be matched to the document; confidence was lowered."
        )
    return profile, warnings
