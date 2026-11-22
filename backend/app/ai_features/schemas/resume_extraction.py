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
_MON_YEAR_RE = re.compile(r"^([A-Za-z]{3,9})\.?\s*,?\s*((?:19|20)\d{2})$")
_YEAR_MON_RE = re.compile(r"^((?:19|20)\d{2})\s*[-/]\s*(\d{1,2})(?:\s*[-/]\s*(\d{1,2}))?$")
_SLASH_MY_RE = re.compile(r"^(\d{1,2})\s*[-/]\s*((?:19|20)\d{2})$")


def _trim(n: int):
    def f(v: Any):
        if v is None or isinstance(v, (dict, list)):
            return None
        s = str(v).strip()
        return s[:n] if s else None

    return f


def _date(v: Any):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.casefold() in {"present", "current", "now", "ongoing", "pursuing", "till date"}:
        return None
    if _DATE_RE.match(s):
        return s
    if m := _MON_YEAR_RE.match(s):
        mon = _MONTHS.get(m.group(1).casefold())
        if mon:
            return f"{m.group(2)}-{mon}"
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
PartialDate = Annotated[str | None, BeforeValidator(_date)]  # YYYY | YYYY-MM | YYYY-MM-DD
Confidence = Annotated[float | None, BeforeValidator(_conf)]


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
    name: Str100 = None
    category: Str100 = None
    confidence: Confidence = None
    evidence: Str400 = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v):
        return {"name": v} if isinstance(v, str) else v


class Employment(_Base):
    company: Str200 = None
    title: Str200 = None
    location: Str200 = None
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
    institution: Str200 = None
    degree: Str200 = None
    field_of_study: Str200 = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    grade: Str100 = None
    confidence: Confidence = None
    evidence: Str400 = None


class Certification(_Base):
    name: Str200 = None
    issuer: Str200 = None
    issue_date: PartialDate = None
    expiry_date: PartialDate = None
    credential_id: Str100 = None
    confidence: Confidence = None
    evidence: Str400 = None


class Project(_Base):
    name: Str200 = None
    description: Str1000 = None
    role: Str200 = None
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
        seen: set[str] = set()
        skills = []
        for s in self.skills:
            k = (s.name or "").casefold()
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
