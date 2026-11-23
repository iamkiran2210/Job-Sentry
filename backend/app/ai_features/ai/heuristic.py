"""
Offline DEVELOPMENT model (AI_MODEL=heuristic): rule-based extraction behind a Pydantic AI FunctionModel.

It exists so the whole pipeline (upload -> worker -> extraction -> API) runs on a laptop/CI with no API key
and no network, through the SAME Agent code path as production (same validation, same retries).
It is deliberately simple and NOT a quality baseline for real resumes: use `python -m app.ai_features.ai evaluate`
against a real model before trusting production extraction. Production refuses to start with it.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{6,}\d(?![\w/])")
_URL = re.compile(
    r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/|github\.com/)[\w./-]+|https?://[\w./-]+",
    re.I,
)
_BULLET = re.compile(r"^[\s\-*•·▪●–—]+")
_DATE = (
    r"(?:\d{4}(?:-\d{2})?|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?(?:\s*/\s*|\s+)\d{4})"
)
_DATE_RANGE = re.compile(
    rf"(?P<s>{_DATE})\s*(?:to|-|–|—)\s*(?P<e>{_DATE}|Present|Current|Now|Ongoing)",
    re.I,
)
_YEAR_RANGE_LINE = re.compile(r"^(?:19|20)\d{2}\s*[-–—/]\s*(?:19|20)\d{2}$")
_NON_NAME_WORDS = frozenset(
    {
        "resume",
        "curriculum vitae",
        "cv",
        "professional summary",
        "summary",
        "career objective",
        "objective",
        "work experience",
        "experience",
        "education",
        "skills",
        "technical skills",
        "details",
        "contact",
    }
)
_TEMPLATE_DOMAINS = (
    "qwikresume.com",
    "zety.com",
    "novoresume.com",
    "resume.io",
    "canva.com",
    "livecareer.com",
    "resumegenius.com",
)
_SKILL_PREFIX_RE = re.compile(
    r"^(?:languages|frameworks|databases|tools|backend|frontend|cloud|devops|ai|ml|ml/dl|ai/ml|skills|technologies|libraries)\s*:\s*",
    re.I,
)
_SKILL_LEVEL_SUFFIX_RE = re.compile(
    r"\s+(?:expert|export|advanced|intermediate|beginner|native speaker|highly proficient|fluent)$",
    re.I,
)
_EMPLOY = re.compile(
    rf"^(?P<title>[^,|@(]+?)\s*(?:,|\s+at\s+|\s+@\s+|\s*\|\s*)\s*(?P<company>[^,|(]+?)\s*(?:,|\(|\|)\s*"
    rf"(?P<s>{_DATE})\s*(?:to|-|–|—)\s*(?P<e>{_DATE}|Present|Current|Now)\)?\s*$",
    re.I,
)
_DEGREE = re.compile(
    r"\b(B\.?Sc\.?|B\.?A\.?|B\.?S\.?|B\.?Tech|B\.?E\.?|Bachelor[^,]*|M\.?Sc\.?|M\.?A\.?|M\.?S\.?|M\.?Tech|MBA|Master[^,]*|Ph\.?D\.?|Diploma|Associate[^,]*|Intermediate[^,]*|SSC)\b",
    re.I,
)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I)
_SECTIONS = {
    "summary": "summary",
    "professional summary": "summary",
    "career objective": "summary",
    "profile": "summary",
    "objective": "summary",
    "about": "summary",
    "about me": "summary",
    "skills": "skills",
    "technical skills": "skills",
    "technical proficiencies": "skills",
    "key skills": "skills",
    "core skills": "skills",
    "core competencies": "skills",
    "technologies": "skills",
    "experience": "experience",
    "work experience": "experience",
    "work history": "experience",
    "employment": "experience",
    "employment history": "experience",
    "professional experience": "experience",
    "internships": "experience",
    "internship": "experience",
    "education": "education",
    "academic background": "education",
    "certifications": "certifications",
    "certificates": "certifications",
    "licenses": "certifications",
    "licenses & certifications": "certifications",
    "projects": "projects",
    "personal projects": "projects",
    "academic projects": "projects",
    "key projects": "projects",
    "selected projects": "projects",
}


def _user_text(messages: list[ModelMessage]) -> str:
    for msg in reversed(messages):
        parts = [
            p.content
            for p in getattr(msg, "parts", [])
            if isinstance(p, UserPromptPart) and isinstance(p.content, str)
        ]
        if parts:
            text = "\n".join(parts)
            m = re.search(r"<document>\n?(.*?)\n?</document>", text, re.S)
            return m.group(1) if m else text
    return ""


def _clean(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _split_sections(lines: list[str]) -> dict[str | None, list[str]]:
    out: dict[str | None, list[str]] = {None: []}
    cur: str | None = None
    for raw in lines:
        key = (
            _SECTIONS.get(raw.strip().rstrip(":").strip().lower())
            if len(raw.strip()) <= 32
            else None
        )
        if key:
            cur = key
            out.setdefault(cur, [])
        else:
            out[cur].append(raw)
    return out


def extract_resume(text: str) -> dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    sec = _split_sections(lines)
    head = sec.get(None, [])
    result: dict[str, Any] = {}

    # name: first plausible name line before any section (supports initials like "C KIRAN BABU")
    for ln in head[:5]:
        cand = ln.strip()
        if (
            "@" not in cand
            and cand.casefold() not in _NON_NAME_WORDS
            and re.fullmatch(r"[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){1,3}", cand)
        ):
            result["full_name"] = {
                "value": cand,
                "confidence": 0.7,
                "evidence": cand,
            }
            break

    contact: dict[str, Any] = {}
    for m in _EMAIL.finditer(text):
        email_val = m.group(0)
        low_em = email_val.casefold()
        if any(low_em.endswith(f"@{d}") and low_em.split("@", 1)[0] in {"support", "info", "help"} for d in _TEMPLATE_DOMAINS):
            continue
        contact["email"] = {
            "value": email_val,
            "confidence": 0.95,
            "evidence": email_val,
        }
        break
    for ln in head[:6]:
        if _EMAIL.search(ln) or _PHONE.search(ln):
            stripped_line = _EMAIL.sub("", ln)
            if p := _PHONE.search(stripped_line):
                pval = p.group(0).strip()
                if not _YEAR_RANGE_LINE.match(pval) and 7 <= len(re.sub(r"\D", "", pval)) <= 15:
                    contact["phone"] = {
                        "value": pval,
                        "confidence": 0.9,
                        "evidence": pval,
                    }
            rest = [
                x.strip()
                for x in re.split(r"[|•·]", _PHONE.sub("", stripped_line))
                if x.strip(" -")
            ]
            if rest and re.fullmatch(r"[A-Za-z .,'-]{2,40}", rest[-1]):
                contact["location"] = {
                    "value": rest[-1],
                    "confidence": 0.5,
                    "evidence": rest[-1],
                }
            break
    if "phone" not in contact:
        for ln in lines:
            if p := _PHONE.search(_EMAIL.sub("", ln)):
                pval = p.group(0).strip()
                if not _YEAR_RANGE_LINE.match(pval) and 7 <= len(re.sub(r"\D", "", pval)) <= 15:
                    contact["phone"] = {
                        "value": pval,
                        "confidence": 0.8,
                        "evidence": pval,
                    }
                    break
    for u in _URL.findall(text):
        low_u = u.casefold()
        if any(d in low_u for d in _TEMPLATE_DOMAINS) or "udemy.com/certificate" in low_u:
            continue
        key = (
            "linkedin_url"
            if "linkedin" in low_u
            else "github_url"
            if "github" in low_u
            else "portfolio_url"
        )
        contact.setdefault(key, {"value": u, "confidence": 0.85, "evidence": u})
    if contact:
        result["contact"] = contact

    if sec.get("summary"):
        result["summary"] = " ".join(_clean(x) for x in sec["summary"])[:1000]

    skills: list[dict] = []
    for ln in sec.get("skills", []):
        cleaned_ln = _SKILL_PREFIX_RE.sub("", _clean(ln))
        for item in re.split(r"[,;|•·\n]", cleaned_ln):
            item = _SKILL_LEVEL_SUFFIX_RE.sub("", item.strip(" .:")).strip()
            if item and len(item) <= 40 and len(item.split()) <= 4 and not item.endswith(":"):
                skills.append({"name": item, "confidence": 0.7, "evidence": _clean(ln)[:200]})
    result["skills"] = skills

    employment: list[dict] = []
    exp_lines = sec.get("experience", [])
    for idx, ln in enumerate(exp_lines):
        c = _clean(ln)
        if not c:
            continue
        if m := _EMPLOY.match(c):
            end = m["e"]
            current = end.lower() in {"present", "current", "now"}
            employment.append(
                {
                    "title": m["title"].strip(),
                    "company": m["company"].strip(),
                    "start_date": m["s"],
                    "end_date": None if current else end,
                    "is_current": True if current else None,
                    "highlights": [],
                    "confidence": 0.7,
                    "evidence": c[:300],
                }
            )
        elif (dm := _DATE_RANGE.search(c)) and not _BULLET.match(ln):
            prefix = c[: dm.start()].strip(" |,-–—()")
            parts = [p.strip() for p in re.split(r"\s*[|—–]\s*|\s+at\s+|\s*,\s*", prefix) if p.strip()]
            title = parts[0] if parts else (
                _clean(exp_lines[idx - 1])[:120]
                if idx > 0 and not _BULLET.match(exp_lines[idx - 1])
                else None
            )
            company = parts[1] if len(parts) > 1 else None
            end = dm["e"]
            current = end.lower() in {"present", "current", "now"}
            if title or company:
                employment.append(
                    {
                        "title": title,
                        "company": company,
                        "start_date": dm["s"],
                        "end_date": None if current else end,
                        "is_current": True if current else None,
                        "highlights": [],
                        "confidence": 0.65,
                        "evidence": c[:300],
                    }
                )
        elif employment:
            employment[-1]["highlights"].append(c[:400])
    result["employment"] = employment

    claims = []
    for ln in lines:
        if m := _YEARS.search(ln):
            after = ln[m.end():]
            a = re.search(r"\b(?:of|in|with|using)\s+([A-Za-z][\w.+#]*)", after)
            claims.append(
                {
                    "statement": _clean(ln)[:300],
                    "area": a.group(1) if a else None,
                    "years": float(m.group(1)),
                    "confidence": 0.6,
                    "evidence": _clean(ln)[:300],
                }
            )
    result["experience_claims"] = claims[:10]

    education: list[dict] = []
    for ln in sec.get("education", []):
        c = _clean(ln)
        parts = [p.strip() for p in c.split(",")]
        year = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", c)
        entry: dict[str, Any] = {"confidence": 0.6, "evidence": c[:300]}
        if parts and (d := _DEGREE.search(parts[0])):
            entry["degree"] = d.group(0).strip()
            field = parts[0][d.end():].strip(" -in")
            entry["field_of_study"] = field or None
            inst = next(
                (
                    p
                    for p in parts[1:]
                    if re.search(r"univers|college|institut|school|academy", p, re.I)
                ),
                parts[1] if len(parts) > 1 else None,
            )
            entry["institution"] = inst
        else:
            entry["institution"] = next(
                (
                    p
                    for p in parts
                    if re.search(r"univers|college|institut|school|academy", p, re.I)
                ),
                None,
            )
        if year:
            entry["end_date"] = year[-1]
        if entry.get("institution") or entry.get("degree"):
            education.append(entry)
    result["education"] = education

    result["certifications"] = [
        {"name": _clean(ln)[:200], "confidence": 0.6, "evidence": _clean(ln)[:300]}
        for ln in sec.get("certifications", [])
        if _clean(ln)
    ]

    skill_names = {s["name"].lower(): s["name"] for s in skills}
    projects = []
    for ln in sec.get("projects", []):
        c = _clean(ln)
        if not c:
            continue
        bits = re.split(r"\s+[-–—]\s+|:\s+", c, maxsplit=1)
        name, desc = bits[0], (bits[1] if len(bits) > 1 else "")
        techs = [
            v
            for k, v in skill_names.items()
            if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", desc.lower())
        ]
        projects.append(
            {
                "name": name.strip()[:200],
                "description": desc.strip()[:1000] or None,
                "technologies": techs,
                "confidence": 0.6,
                "evidence": c[:300],
            }
        )
    result["projects"] = projects
    return result


_MANDATORY = re.compile(r"\b(must|required|mandatory|minimum|at least|need to|essential)\b", re.I)
_PREFERRED = re.compile(r"\b(nice to have|preferred|bonus|plus|desirable|ideally)\b", re.I)
_LANG = re.compile(
    r"\b(english|spanish|german|french|hindi|mandarin|arabic|portuguese|japanese)\b",
    re.I,
)

_KNOWN_TECH = re.compile(
    r"\b(Python|Java|Go|Golang|Rust|JavaScript|TypeScript|C\+\+|C#|Ruby|PHP|Swift|Kotlin|Scala|SQL|PostgreSQL|MySQL|MongoDB|Redis|FastAPI|Django|Flask|Spring|Node\.js|React|Svelte|Vue|Angular|Next\.js|Docker|Kubernetes|AWS|GCP|Azure|Terraform|Ansible|Kafka|RabbitMQ|GraphQL|gRPC|REST|Linux|Git|CI/CD|PyTorch|TensorFlow|Scikit-learn|Spark|Airflow|Snowflake|Machine Learning|Deep Learning|NLP|Distributed Systems|Microservices|System Design)\b",
    re.I,
)


def extract_requirements(text: str) -> dict[str, Any]:
    section, reqs = None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.rstrip(":").lower()
        if len(line) <= 40 and (
                line.endswith(":")
                or line.isupper()
                or low
                in {
                    "requirements",
                    "qualifications",
                    "responsibilities",
                    "nice to have",
                    "preferred qualifications",
                }
        ):
            section = low
            continue
        if not _BULLET.match(raw) and section is None:
            continue
        item = _clean(line).rstrip(".")
        if not item or len(item) > 255:
            continue
        in_pref = bool(_PREFERRED.search(item)) or bool(section and _PREFERRED.search(section))
        mandatory = not in_pref and (
                bool(_MANDATORY.search(item))
                or bool(section and re.search(r"require|qualif|must", section))
        )
        if section and "responsib" in section:
            cat, mandatory = "responsibility", False
        elif _YEARS.search(item):
            cat = "experience"
        elif re.search(r"degree|bachelor|master|phd|diploma", item, re.I):
            cat = "education"
        elif re.search(r"certif", item, re.I):
            cat = "certification"
        elif _LANG.search(item):
            cat = "language"
        else:
            cat = "skills"
        reqs.append(
            {
                "category": cat,
                "name": item,
                "requirement_type": "mandatory" if mandatory else "preferred",
                "importance": "high" if mandatory else "medium",
                "weight": 0.0,
                "evidence": _clean(line)[:300],
            }
        )

    # Fallback for plain-paragraph descriptions without bullets or section headers
    if not reqs and text.strip():
        seen_names: set[str] = set()
        for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
            s = _clean(sent).rstrip(".")
            if not s:
                continue
            in_pref = bool(_PREFERRED.search(s))
            is_mand = not in_pref and bool(_MANDATORY.search(s))
            if ym := _YEARS.search(s):
                name = s[:120] if len(s) <= 120 else ym.group(0) + " experience"
                if name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    reqs.append(
                        {
                            "category": "experience",
                            "name": name,
                            "requirement_type": "mandatory" if is_mand else "preferred",
                            "importance": "high",
                            "weight": 0.0,
                            "evidence": s[:300],
                        }
                    )
            if dm := _DEGREE.search(s):
                deg = dm.group(0).strip()
                if deg.lower() not in seen_names:
                    seen_names.add(deg.lower())
                    reqs.append(
                        {
                            "category": "education",
                            "name": deg,
                            "requirement_type": "mandatory" if is_mand else "preferred",
                            "importance": "medium",
                            "weight": 0.0,
                            "evidence": s[:300],
                        }
                    )
            for tm in _KNOWN_TECH.finditer(s):
                tech = tm.group(0)
                if tech.lower() not in seen_names:
                    seen_names.add(tech.lower())
                    reqs.append(
                        {
                            "category": "skills",
                            "name": tech,
                            "requirement_type": "mandatory" if is_mand else "preferred",
                            "importance": "high" if is_mand else "medium",
                            "weight": 0.0,
                            "evidence": s[:300],
                        }
                    )

    return {"requirements": reqs}


_TASKS = {"resume_profile": extract_resume, "job_requirements": extract_requirements}


def heuristic_model(task: str) -> FunctionModel:
    fn = _TASKS.get(task)
    if fn is None:
        raise ValueError(f"no heuristic extractor for task {task!r}")

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        data = fn(_user_text(messages))
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=data)])

    return FunctionModel(respond, model_name=f"heuristic-{task}")
