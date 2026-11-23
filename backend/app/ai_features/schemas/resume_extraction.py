"""
Pydantic schema for LLM output. Everything is a CLAIM from the resume, never a verified fact.
Validators are forgiving on shape (truncate, null-out bad values) but never invent data:
unknown stays None / [].
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
_DATE_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
_MONTHS = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}
_MON_YEAR_RE = re.compile(
    r"^([A-Za-z]{3,9})\.?\s*(?:[,/\-]\s*)?((?:19|20)\d{2}|'\d{2})$"
)
_YEAR_MON_NAME_RE = re.compile(r"^((?:19|20)\d{2})\s*[,/\-\s]\s*([A-Za-z]{3,9})\.?$")
_YEAR_MON_RE = re.compile(r"^((?:19|20)\d{2})\s*[-/]\s*(\d{1,2})(?:\s*[-/]\s*(\d{1,2}))?$")
_SLASH_MY_RE = re.compile(r"^(\d{1,2})\s*[-/]\s*((?:19|20)\d{2})$")
_CURRENT_MARKERS = frozenset(
    {"present", "current", "now", "ongoing", "pursuing", "till date", "to date", "active"}
)
_DATE_PREFIX_RE = re.compile(
    r"^(?:expected|est\.?|estimated|graduating|anticipated|since|from)\s+", re.I
)
_LEADING_GLYPH_RE = re.compile(r"^(?:</>|[•·▪●▸➢❖✓✔➤►→–—\-|&€©®⟟]+\s+)+")
_TRAILING_JUNK_RE = re.compile(r"[\s,;|•·–—]+$")
_SKILL_PROFICIENCY_RE = re.compile(
    r"\s*(?:[-–—:|(]\s*)?(?:expert|export|advanced|intermediate|beginner|proficient|highly proficient|native speaker|fluent|basic)\)?$",
    re.I,
)


def _trim(n: int):
    def f(v: Any):
        if v is None or isinstance(v, (dict, list)):
            return None
        s = re.sub(r"\s+", " ", str(v)).strip()
        return s[:n] if s else None

    return f


def _clean_entity(n: int):
    def f(v: Any):
        if v is None or isinstance(v, (dict, list)):
            return None
        s = re.sub(r"\s+", " ", str(v)).strip()
        s = _LEADING_GLYPH_RE.sub("", s).strip()
        s = _TRAILING_JUNK_RE.sub("", s).strip()
        return s[:n] if s else None

    return f


def _clean_skill_name(v: Any):
    if v is None or isinstance(v, (dict, list)):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    s = _LEADING_GLYPH_RE.sub("", s).strip()
    s = _SKILL_PROFICIENCY_RE.sub("", s).strip()
    s = _TRAILING_JUNK_RE.sub("", s).strip()
    # Reject empty, purely numeric, or full-sentence action bullets masquerading as skills
    if not s or re.fullmatch(r"[\d\W_]+", s) or len(s.split()) > 6:
        return None
    return s[:100]


def _normalize_url_value(v: str | None) -> str | None:
    if not v:
        return None
    s = v.strip().strip("<>()[]\"'.,;")
    if not s or " " in s:
        return None
    low = s.casefold()
    if low.startswith(("http://", "https://")):
        return s[:300]
    if low.startswith(("www.", "linkedin.com/", "github.com/")) or re.match(
        r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/\S*)?$", low
    ):
        return f"https://{s}"[:300]
    return s[:300]


def _expand_two_digit_year(raw_year: str) -> str:
    if raw_year.startswith("'") and len(raw_year) == 3 and raw_year[1:].isdigit():
        yy = int(raw_year[1:])
        return f"{1900 + yy if yy >= 50 else 2000 + yy}"
    return raw_year


def _date(v: Any):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    s = _DATE_PREFIX_RE.sub("", s).strip()
    if not s or s.casefold() in _CURRENT_MARKERS:
        return None
    if _DATE_RE.match(s):
        return s
    if m := _MON_YEAR_RE.match(s):
        mon = _MONTHS.get(m.group(1).casefold())
        if mon:
            return f"{_expand_two_digit_year(m.group(2))}-{mon}"
    if m := _YEAR_MON_NAME_RE.match(s):
        mon = _MONTHS.get(m.group(2).casefold())
        if mon:
            return f"{m.group(1)}-{mon}"
    if m := _YEAR_MON_RE.match(s):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)) if m.group(3) else None
        if 1 <= mo <= 12:
            if d is not None and 1 <= d <= 31:
                return f"{y}-{mo:02d}-{d:02d}"
            return f"{y}-{mo:02d}"
    if m := _SLASH_MY_RE.match(s):
        mo, y = int(m.group(1)), m.group(2)
        if 1 <= mo <= 12:
            return f"{y}-{mo:02d}"
    return None


def _conf(v: Any):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 1.0 else None


def _cap(n: int, allow_str: bool = False):
    """Cap list length and silently drop items that can't be objects (one bad item must not sink the profile)."""
    ok = (dict, str) if allow_str else (dict,)
    return lambda v: [x for x in v if isinstance(x, ok)][:n] if isinstance(v, list) else []


Str100 = Annotated[str | None, BeforeValidator(_trim(100))]
Str200 = Annotated[str | None, BeforeValidator(_trim(200))]
Str300 = Annotated[str | None, BeforeValidator(_trim(300))]
Str400 = Annotated[str | None, BeforeValidator(_trim(400))]
Str1000 = Annotated[str | None, BeforeValidator(_trim(1000))]
Str2000 = Annotated[str | None, BeforeValidator(_trim(2000))]
Entity200 = Annotated[str | None, BeforeValidator(_clean_entity(200))]
Entity300 = Annotated[str | None, BeforeValidator(_clean_entity(300))]
SkillName = Annotated[str | None, BeforeValidator(_clean_skill_name)]
PartialDate = Annotated[str | None, BeforeValidator(_date)]  # YYYY | YYYY-MM | YYYY-MM-DD
Confidence = Annotated[float | None, BeforeValidator(_conf)]


def _skill_dedup_key(name: str) -> str:
    return re.sub(r"[\s\-_.]+", "", name.casefold())


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Sourced(_Base):
    value: Str300 = None
    confidence: Confidence = None
    evidence: Str400 = None  # verbatim quote from the resume

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v):
        if v is None:
            return {}
        return {"value": v} if isinstance(v, str) else v


class ContactDetails(_Base):
    email: Sourced = Field(default_factory=Sourced)
    phone: Sourced = Field(default_factory=Sourced)
    location: Sourced = Field(default_factory=Sourced)
    linkedin_url: Sourced = Field(default_factory=Sourced)
    github_url: Sourced = Field(default_factory=Sourced)
    portfolio_url: Sourced = Field(default_factory=Sourced)

    @model_validator(mode="before")
    @classmethod
    def _none(cls, v):
        return {} if v is None else v


class Skill(_Base):
    name: SkillName = None
    category: Str100 = None
    confidence: Confidence = None
    evidence: Str400 = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v):
        return {"name": v} if isinstance(v, str) else v


class Employment(_Base):
    company: Entity200 = None
    title: Entity200 = None
    location: Entity200 = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    is_current: bool | None = None
    description: Str2000 = None
    highlights: Annotated[
        list[str],
        BeforeValidator(
            lambda v: [str(x).strip()[:400] for x in v[:15] if x] if isinstance(v, list) else []
        ),
    ] = []
    confidence: Confidence = None
    evidence: Str400 = None

    @model_validator(mode="before")
    @classmethod
    def _infer_is_current(cls, v):
        if isinstance(v, dict):
            raw_end = v.get("end_date")
            if (
                v.get("is_current") is None
                and isinstance(raw_end, str)
                and raw_end.strip().casefold() in _CURRENT_MARKERS
            ):
                v = {**v, "is_current": True}
        return v


class ExperienceClaim(_Base):
    """A stated amount of experience, e.g. '5+ years of Python'. Never computed from dates."""

    statement: Str300 = None
    area: Str100 = None  # None = overall experience
    years: Annotated[
        float | None,
        BeforeValidator(
            lambda v: float(v) if isinstance(v, (int, float)) and 0 <= v <= 60 else None
        ),
    ] = None
    confidence: Confidence = None
    evidence: Str400 = None


class Education(_Base):
    institution: Entity200 = None
    degree: Entity200 = None
    field_of_study: Entity200 = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    grade: Str100 = None
    confidence: Confidence = None
    evidence: Str400 = None


class Certification(_Base):
    name: Entity200 = None
    issuer: Entity200 = None
    issue_date: PartialDate = None
    expiry_date: PartialDate = None
    credential_id: Str100 = None
    confidence: Confidence = None
    evidence: Str400 = None


class Project(_Base):
    name: Entity200 = None
    description: Str1000 = None
    role: Entity200 = None
    url: Str300 = None
    technologies: Annotated[
        list[str],
        BeforeValidator(
            lambda v: [str(x).strip()[:100] for x in v[:30] if x] if isinstance(v, list) else []
        ),
    ] = []
    confidence: Confidence = None
    evidence: Str400 = None


class ExtractedProfileData(_Base):
    full_name: Sourced = Field(default_factory=Sourced)
    contact: ContactDetails = Field(default_factory=ContactDetails)
    summary: Str1000 = None
    skills: Annotated[list[Skill], BeforeValidator(_cap(150, allow_str=True))] = []
    employment: Annotated[list[Employment], BeforeValidator(_cap(30))] = []
    experience_claims: Annotated[list[ExperienceClaim], BeforeValidator(_cap(40))] = []
    education: Annotated[list[Education], BeforeValidator(_cap(15))] = []
    certifications: Annotated[list[Certification], BeforeValidator(_cap(30))] = []
    projects: Annotated[list[Project], BeforeValidator(_cap(30))] = []

    @model_validator(mode="before")
    @classmethod
    def _none(cls, v):
        return {} if v is None else v

    @model_validator(mode="after")
    def _drop_empty_items(self):
        if self.full_name.value:
            self.full_name.value = _clean_entity(300)(self.full_name.value)
        if self.contact.location.value:
            self.contact.location.value = _clean_entity(300)(self.contact.location.value)
        seen: set[str] = set()
        skills = []
        for s in self.skills:
            k = _skill_dedup_key(s.name) if s.name else ""
            if k and k not in seen:
                seen.add(k)
                skills.append(s)
        self.skills = skills
        self.employment = [e for e in self.employment if e.company or e.title]
        self.experience_claims = [
            c for c in self.experience_claims if c.statement or c.years is not None
        ]
        self.education = [e for e in self.education if e.institution or e.degree]
        self.certifications = [c for c in self.certifications if c.name]
        self.projects = [p for p in self.projects if p.name]
        return self

    def all_confidences(self) -> list[float]:
        out: list[float] = []
        singles = [self.full_name, *vars(self.contact).values()]
        out += [
            s.confidence for s in singles if isinstance(s, Sourced) and s.confidence is not None
        ]
        for group in (
                self.skills,
                self.employment,
                self.experience_claims,
                self.education,
                self.certifications,
                self.projects,
        ):
            out += [i.confidence for i in group if i.confidence is not None]
        return out
