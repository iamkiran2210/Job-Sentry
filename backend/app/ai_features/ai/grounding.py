"""Generic helpers to check that a model-produced value really appears in the source text."""

from __future__ import annotations

import re
import unicodedata

_YEAR_RANGE_RE = re.compile(r"^(?:19|20)\d{2}\s*[-–—/]\s*(?:19|20)\d{2}$")

_SKILL_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "aws": ("amazon web services",),
    "amazon web services": ("aws",),
    "gcp": ("google cloud platform", "google cloud"),
    "google cloud": ("gcp", "google cloud platform"),
    "google cloud platform": ("gcp", "google cloud"),
    "k8s": ("kubernetes",),
    "kubernetes": ("k8s",),
    "js": ("javascript",),
    "javascript": ("js",),
    "ts": ("typescript",),
    "typescript": ("ts",),
    "ml": ("machine learning",),
    "machine learning": ("ml",),
    "dl": ("deep learning",),
    "deep learning": ("dl",),
    "nlp": ("natural language processing",),
    "natural language processing": ("nlp",),
    "cv": ("computer vision",),
    "computer vision": ("cv",),
    "postgres": ("postgresql",),
    "postgresql": ("postgres",),
    "node.js": ("nodejs", "node js"),
    "nodejs": ("node.js", "node js"),
    "react": ("reactjs", "react.js"),
    "reactjs": ("react", "react.js"),
    "next.js": ("nextjs", "next js"),
    "nextjs": ("next.js", "next js"),
    "ci/cd": ("continuous integration", "continuous deployment", "continuous delivery"),
    "scikit-learn": ("sklearn", "scikit learn"),
    "sklearn": ("scikit-learn", "scikit learn"),
    "rest apis": ("rest api", "restful api", "restful apis"),
    "rest api": ("rest apis", "restful api", "restful apis"),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).casefold().strip()


def _alnum(s: str) -> str:
    return re.sub(r"[\W_]+", "", _norm(s))


def _boundary_pattern(token: str) -> str:
    prefix = r"(?<!\w)" if token and token[0].isalnum() else ""
    suffix = r"(?!\w)" if token and token[-1].isalnum() else ""
    return f"{prefix}{re.escape(token)}{suffix}"


class Haystack:
    def __init__(self, text: str) -> None:
        self.norm = _norm(text)
        self.alnum = _alnum(text)
        self.digits = re.sub(r"\D", "", text)

    def has(self, needle: str | None) -> bool:
        n = _norm(needle or "")
        if not n:
            return False
        if len(n) < 4:  # short tokens like "C", "R", "Go", "C++", "C#" must respect word boundaries
            return re.search(_boundary_pattern(n), self.norm) is not None
        a = _alnum(n)
        return n in self.norm or (len(a) >= 4 and a in self.alnum)

    def has_loose(self, needle: str | None, *, threshold: float = 0.6) -> bool:
        """Most significant words appear (tolerates 'Google LLC' vs 'Google' or OCR column breaks)."""
        toks = [t for t in re.findall(r"\w+", _norm(needle or "")) if len(t) >= 3]
        if not toks:
            return self.has(needle)
        hits = sum(1 for t in toks if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", self.norm))
        return hits / len(toks) >= threshold

    def has_name(self, name: str | None) -> bool:
        """Verify name tokens appear in document, tolerating OCR kerning splits (e.g. 'J ohn Doe')."""
        if not name or not name.strip():
            return False
        toks = re.findall(r"\w{2,}", name)
        if not toks:
            return False
        if all(self.has(t) for t in toks):
            return True
        # Handle OCR kerning splits inside short tokens (e.g. "J ohn" -> "John", "L i" -> "Li")
        collapsed = _alnum(name)
        if len(collapsed) >= 4 and collapsed in self.alnum:
            return True
        return False

    def has_email(self, email: str | None) -> bool:
        """Verify email is grounded, including line-wrapped emails and 1-char OCR '@' misreads."""
        e = (email or "").strip().casefold()
        if not e or "@" not in e:
            return False
        if self.has(e):
            return True
        local, _, domain = e.partition("@")
        local_a = _alnum(local)
        domain_a = _alnum(domain)
        if len(local_a) < 3 or len(domain_a) < 4:
            return False
        # Allow a single OCR-misread separator character between local and domain (e.g. "userSgmail.com")
        pattern = re.escape(local_a) + r".{0,2}" + re.escape(domain_a)
        return re.search(pattern, self.alnum) is not None

    def has_phone(self, phone: str) -> bool:
        if _YEAR_RANGE_RE.match((phone or "").strip()):
            return False
        d = re.sub(r"\D", "", phone)
        return 7 <= len(d) <= 15 and d in self.digits

    def has_url(self, url: str) -> bool:
        core = re.sub(r"^(https?://)?(www\.)?", "", url.strip().casefold()).rstrip("/")
        if not core:
            return False
        if core in self.norm:
            return True
        # Handle PDF line-wrapped URLs (e.g. "github.com/\nusername")
        core_alnum = _alnum(core)
        if len(core_alnum) >= 8 and core_alnum in self.alnum:
            return True
        # Handle icon + bare GitHub/LinkedIn handle in OCR/styled resumes when handle is present verbatim
        m = re.match(r"^(?:github\.com|linkedin\.com/in)/([a-z0-9][a-z0-9._-]{3,})$", core)
        if m:
            handle = m.group(1)
            if re.search(rf"(?<!\w){re.escape(handle)}(?!\w)", self.norm):
                return True
        return False

    def has_skill(self, name: str | None, evidence: str | None = None) -> bool:
        n = _norm(name or "")
        if not n:
            return False
        if self.has(n):
            return True
        for alias in _SKILL_EQUIVALENTS.get(n, ()):
            if self.has(alias):
                return True
        if evidence and self.has(evidence):
            # Require the skill or one of its meaningful tokens/aliases to be backed by the evidence
            ev_norm = _norm(evidence)
            if n in ev_norm or any(a in ev_norm for a in _SKILL_EQUIVALENTS.get(n, ())):
                return True
            toks = [t for t in re.findall(r"\w+", n) if len(t) >= 3]
            if toks and sum(1 for t in toks if t in ev_norm) / len(toks) >= 0.6:
                return True
        return False
