"""Generic helpers to check that a model-produced value really appears in the source text."""

from __future__ import annotations

import re
import unicodedata


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).casefold().strip()


def _alnum(s: str) -> str:
    return re.sub(r"[\W_]+", "", _norm(s))


class Haystack:
    def __init__(self, text: str) -> None:
        self.norm = _norm(text)
        self.alnum = _alnum(text)
        self.digits = re.sub(r"\D", "", text)

    def has(self, needle: str | None) -> bool:
        n = _norm(needle or "")
        if not n:
            return False
        if len(n) < 4:  # short tokens like "C", "R", "Go" must match on word boundaries
            return re.search(rf"(?<!\w){re.escape(n)}(?!\w)", self.norm) is not None
        a = _alnum(n)
        return n in self.norm or (len(a) >= 4 and a in self.alnum)

    def has_loose(self, needle: str | None, *, threshold: float = 0.6) -> bool:
        """Most significant words appear (tolerates 'Google LLC' vs 'Google' or OCR column breaks)."""
        toks = [t for t in re.findall(r"\w+", _norm(needle or "")) if len(t) >= 3]
        if not toks:
            return self.has(needle)
        hits = sum(1 for t in toks if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", self.norm))
        return hits / len(toks) >= threshold

    def has_phone(self, phone: str) -> bool:
        d = re.sub(r"\D", "", phone)
        return len(d) >= 7 and d in self.digits

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
