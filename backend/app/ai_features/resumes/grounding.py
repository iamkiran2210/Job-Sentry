"""
Anti-fabrication guard and contact/entity hygiene. After the model answers, every identifying value must be
traceable to the source text; fabricated values, malformed emails, and resume-builder watermarks are removed,
and evidence quotes that are not really in the document are cleared with their confidence capped.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.ai_features.ai.grounding import Haystack
from app.ai_features.schemas.resume_extraction import (
    ExtractedProfileData,
    Sourced,
    _normalize_url_value,
)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_NON_NAME_HEADERS = frozenset(
    {
        "resume",
        "curriculum vitae",
        "cv",
        "profile",
        "summary",
        "professional summary",
        "career objective",
        "objective",
        "contact",
        "details",
        "personal details",
        "work experience",
        "education",
        "skills",
    }
)
_TEMPLATE_BUILDER_DOMAINS = frozenset(
    {
        "qwikresume.com",
        "zety.com",
        "novoresume.com",
        "resume.io",
        "resumegenius.com",
        "livecareer.com",
        "enhancv.com",
        "myperfectresume.com",
        "visualcv.com",
        "resumebuilder.com",
        "kickresume.com",
        "flowcv.com",
        "tealhq.com",
        "canva.com",
        "overleaf.com",
        "cakeresume.com",
        "standardresume.co",
    }
)
_TEMPLATE_EMAIL_DOMAINS = frozenset(
    {
        "qwikresume.com",
        "zety.com",
        "novoresume.com",
        "resume.io",
        "resumegenius.com",
        "livecareer.com",
        "myperfectresume.com",
        "enhancv.com",
        "canva.com",
    }
)
_TEMPLATE_LOCAL_PREFIXES = frozenset({"support", "info", "help", "hello", "contact", "noreply", "no-reply"})
_CERTIFICATE_HOST_SNIPPETS = (
    "udemy.com/certificate",
    "coursera.org/verify",
    "coursera.org/account/accomplishments",
    "credly.com/",
    "credential.net/",
    "badgr.com/",
)
_DEGREE_PAREN_FIELD_RE = re.compile(
    r"^(B\.?Tech|B\.?E\.?|B\.?Sc\.?|B\.?S\.?|B\.?A\.?|M\.?Tech|M\.?Sc\.?|M\.?S\.?|Bachelor[^()]*|Master[^()]*)\s*\(([^()]{3,80})\)$",
    re.I,
)


def _extract_host(url: str) -> str:
    norm = _normalize_url_value(url) or url.strip()
    try:
        host = (urlparse(norm).hostname or "").casefold()
    except Exception:
        host = ""
    return host.removeprefix("www.")


def _is_template_watermark_url(url: str) -> bool:
    host = _extract_host(url)
    return any(host == d or host.endswith(f".{d}") for d in _TEMPLATE_BUILDER_DOMAINS)


def _is_certificate_url(url: str) -> bool:
    low = url.casefold()
    return any(snippet in low for snippet in _CERTIFICATE_HOST_SNIPPETS)


def _is_template_support_email(email: str) -> bool:
    local, _, domain = email.strip().casefold().partition("@")
    return domain in _TEMPLATE_EMAIL_DOMAINS and local in _TEMPLATE_LOCAL_PREFIXES


def _sanitize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().strip("<>()[]\"',;:")
    if s.casefold().startswith("mailto:"):
        s = s[7:].split("?", 1)[0].strip()
    # Clean lossless OCR whitespace directly adjacent to '@' or '.'
    s = re.sub(r"\s*@\s*", "@", s)
    s = re.sub(r"\s*\.\s*", ".", s)
    return s if _EMAIL_RE.match(s) else None


def _clean_ocr_name(name: str) -> str:
    # Fix OCR kerning split of a single leading capital from lowercase remainder (e.g. "J ohn Doe" -> "John Doe")
    # without touching real initials like "C KIRAN BABU" or "John A Smith".
    return re.sub(r"\b([A-Z])\s+([a-z]{2,})\b", r"\1\2", name).strip()


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

    def drop(sourced: Sourced, label: str, reason: str | None = None) -> None:
        warnings.append(reason or f"{label} was not found in the document and was removed.")
        sourced.value = sourced.evidence = sourced.confidence = None

    # full_name
    n = profile.full_name
    if n.value:
        n.value = _clean_ocr_name(n.value)
        if n.value.casefold() in _NON_NAME_HEADERS:
            drop(n, "full_name", "full_name appeared to be a section header and was removed.")
        elif not hay.has_name(n.value):
            drop(n, "full_name")

    # contact
    c = profile.contact
    if c.email.value:
        cleaned_email = _sanitize_email(c.email.value)
        if not cleaned_email:
            drop(
                c.email,
                "contact.email",
                "contact.email was malformed (likely OCR corruption) and was removed.",
            )
        elif _is_template_support_email(cleaned_email):
            drop(
                c.email,
                "contact.email",
                "contact.email belonged to a resume template watermark and was removed.",
            )
        elif not hay.has_email(cleaned_email):
            drop(c.email, "contact.email")
        else:
            c.email.value = cleaned_email

    if c.phone.value and not hay.has_phone(c.phone.value):
        drop(c.phone, "contact.phone")

    # Cross-route misclassified portfolio URLs (LinkedIn / GitHub profile mistakenly put in portfolio_url)
    if c.portfolio_url.value:
        port_norm = _normalize_url_value(c.portfolio_url.value)
        if port_norm:
            host = _extract_host(port_norm)
            if "linkedin.com" in host and "/in/" in port_norm.casefold():
                if not c.linkedin_url.value:
                    c.linkedin_url.value = port_norm
                    c.linkedin_url.evidence = c.portfolio_url.evidence
                    c.linkedin_url.confidence = c.portfolio_url.confidence
                c.portfolio_url.value = c.portfolio_url.evidence = c.portfolio_url.confidence = None
            elif host == "github.com" and re.fullmatch(
                r"https?://(?:www\.)?github\.com/[a-z0-9][a-z0-9._-]*/?", port_norm, re.I
            ):
                if not c.github_url.value:
                    c.github_url.value = port_norm
                    c.github_url.evidence = c.portfolio_url.evidence
                    c.github_url.confidence = c.portfolio_url.confidence
                c.portfolio_url.value = c.portfolio_url.evidence = c.portfolio_url.confidence = None

    for label in ("linkedin_url", "github_url", "portfolio_url"):
        s: Sourced = getattr(c, label)
        if not s.value:
            continue
        norm_url = _normalize_url_value(s.value)
        if not norm_url:
            drop(s, f"contact.{label}", f"contact.{label} was not a valid URL and was removed.")
            continue
        host = _extract_host(norm_url)
        if label == "linkedin_url" and "linkedin.com" not in host:
            drop(s, f"contact.{label}", "contact.linkedin_url was not a LinkedIn URL and was removed.")
            continue
        if label == "github_url" and "github.com" not in host:
            drop(s, f"contact.{label}", "contact.github_url was not a GitHub URL and was removed.")
            continue
        if label == "portfolio_url" and (_is_template_watermark_url(norm_url) or _is_certificate_url(norm_url)):
            drop(
                s,
                f"contact.{label}",
                "contact.portfolio_url was a template watermark or certificate link and was removed.",
            )
            continue
        if not hay.has_url(norm_url):
            drop(s, f"contact.{label}")
        else:
            s.value = norm_url

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
        lambda s: hay.has_skill(s.name, s.evidence),
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
    for edu in profile.education:
        if edu.degree and not edu.field_of_study:
            m = _DEGREE_PAREN_FIELD_RE.match(edu.degree.strip())
            if m:
                edu.degree = m.group(1).strip()
                edu.field_of_study = m.group(2).strip()

    profile.certifications = keep(
        profile.certifications, lambda x: hay.has_loose(x.name), "certification"
    )
    profile.projects = keep(profile.projects, lambda p: hay.has_loose(p.name), "project")
    for proj in profile.projects:
        if proj.url:
            norm_url = _normalize_url_value(proj.url)
            if not norm_url or _is_template_watermark_url(norm_url) or not hay.has_url(norm_url):
                proj.url = None
                warnings.append(f"project '{proj.name}' URL was invalid or not found in the document and was removed.")
            else:
                proj.url = norm_url

    profile.experience_claims = keep(
        profile.experience_claims,
        lambda x: (x.evidence is not None and hay.has(x.evidence)) or hay.has_loose(x.statement),
        "experience claim",
    )
    if cleared:
        warnings.append(
            f"{cleared} evidence quote(s) could not be matched to the document; confidence was lowered."
        )
    return profile, warnings
