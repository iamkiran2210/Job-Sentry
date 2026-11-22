from __future__ import annotations

import hashlib
import re
import threading
import uuid

from app.modules.candidate_intelligence.interfaces import EmbeddingProvider, LLMAnalyzer
from app.modules.candidate_intelligence.types import ScoreEvidence

_EMBEDDING_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _cached_embedding(provider: EmbeddingProvider, text: str):
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    model = getattr(provider, "model_name", type(provider).__name__)
    version = getattr(provider, "model_version", "unknown")
    key = (model, version, text_hash)
    with _CACHE_LOCK:
        cached = _EMBEDDING_CACHE.get(key)
    if cached is not None:
        return cached
    result = provider.embed_text(text)
    with _CACHE_LOCK:
        return _EMBEDDING_CACHE.setdefault(key, result)


_GENERIC_SKILL_WORDS = frozenset(
    {
        "and",
        "or",
        "of",
        "in",
        "with",
        "for",
        "to",
        "the",
        "a",
        "an",
        "experience",
        "experienced",
        "years",
        "year",
        "yrs",
        "yr",
        "strong",
        "solid",
        "good",
        "proficiency",
        "proficient",
        "knowledge",
        "familiar",
        "familiarity",
        "skills",
        "skill",
        "development",
        "developer",
        "engineering",
        "engineer",
        "programming",
        "language",
        "languages",
        "framework",
        "frameworks",
        "library",
        "libraries",
        "database",
        "databases",
        "tool",
        "tools",
        "platform",
        "platforms",
        "service",
        "services",
        "system",
        "systems",
        "web",
        "cloud",
        "data",
        "design",
        "testing",
        "management",
        "software",
        "application",
        "applications",
        "backend",
        "frontend",
        "fullstack",
        "plus",
        "preferred",
        "required",
        "hands",
        "on",
        "using",
        "use",
    }
)

_VERSION_SUFFIX_RE = re.compile(r"\s+v?\d+(?:\.\d+)*\+?$")


def _strip_version(value: str) -> str:
    return _VERSION_SUFFIX_RE.sub("", value.strip()).strip()


def _skill_subterms(value: str, aliases: dict[str, str]) -> list[str]:
    """Extract normalized canonical sub-terms from compound skill phrases like 'AWS (EC2, S3)' or 'Python / FastAPI'."""
    parts = [value]
    # Split parenthetical qualifiers: "AWS (EC2, S3)" -> "AWS", "EC2", "S3"
    base = re.sub(r"\([^)]*\)", " ", value).strip()
    if base and base != value:
        parts.append(base)
    for paren in re.findall(r"\(([^)]+)\)", value):
        parts.append(paren)
    expanded: list[str] = []
    for part in parts:
        expanded.append(part)
        for piece in re.split(r"[/,|;&]+|\band\b|\bor\b", part, flags=re.IGNORECASE):
            piece = piece.strip()
            if piece:
                expanded.append(piece)
    seen: set[str] = set()
    terms: list[str] = []
    for piece in expanded:
        for variant in (piece, _strip_version(piece)):
            if not variant:
                continue
            canon, _ = canonical_skill(variant, aliases)
            if canon and canon not in _GENERIC_SKILL_WORDS and canon not in seen:
                seen.add(canon)
                terms.append(canon)
    return terms


def _word_boundary_match(term: str, text: str) -> bool:
    if not term or not text:
        return False
    pattern = rf"(?<![a-z0-9+#]){re.escape(term.casefold())}(?![a-z0-9+#])"
    return bool(re.search(pattern, text.casefold()))


def canonical_skill(value: str, aliases: dict[str, str]) -> tuple[str, str | None]:
    normalized = re.sub(r"[^a-z0-9+#]+", "", value.casefold())
    alias_map = {
        re.sub(r"[^a-z0-9+#]+", "", k.casefold()): re.sub(r"[^a-z0-9+#]+", "", v.casefold())
        for k, v in aliases.items()
    }
    return alias_map.get(normalized, normalized), (normalized if normalized in alias_map else None)


def exact_skill_evidence(
        requirements: list[str], resume_skills: list[dict], aliases: dict[str, str]
) -> list[ScoreEvidence]:
    found = []
    for req in sorted(set(requirements), key=str.casefold):
        canonical, _ = canonical_skill(req, aliases)
        matched = False
        # Pass 1: exact / alias canonical match
        for i, skill in enumerate(resume_skills):
            term = skill.get("name") if isinstance(skill, dict) else skill
            if not term:
                continue
            candidate, used = canonical_skill(str(term), aliases)
            if canonical == candidate:
                found.append(
                    ScoreEvidence(
                        evidence_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"skill:{req}:{term}:{i}")),
                        category="skills",
                        signal_type="alias_skill_match" if used else "exact_skill_match",
                        value=1.0,
                        source_location=f"profile_data.skills[{i}]",
                        matched_term=str(term),
                        requirement_term=req,
                        canonical_term=canonical,
                        alias_used=used,
                        match_type="exact" if not used else "alias",
                    )
                )
                matched = True
                break
        if matched:
            continue
        # Pass 2: version-stripped & compound/phrase-aware token match
        req_subterms = _skill_subterms(req, aliases)
        req_words = {
            canonical_skill(w, aliases)[0]
            for w in re.findall(r"[a-zA-Z0-9+#.]+", req)
            if canonical_skill(w, aliases)[0] not in _GENERIC_SKILL_WORDS
               and not w.isdigit()
        }
        for i, skill in enumerate(resume_skills):
            term = skill.get("name") if isinstance(skill, dict) else skill
            if not term:
                continue
            term_str = str(term).strip()
            cand_subterms = _skill_subterms(term_str, aliases)
            cand_canon, _ = canonical_skill(_strip_version(term_str), aliases)
            if not cand_canon or cand_canon in _GENERIC_SKILL_WORDS:
                continue
            is_match = (
                    cand_canon in req_subterms
                    or any(cs in req_subterms for cs in cand_subterms)
                    or (cand_canon in req_words and (len(cand_canon) >= 2))
                    or (
                            len(req_subterms) == 1
                            and len(req_subterms[0]) >= 2
                            and _word_boundary_match(_strip_version(req), term_str)
                    )
                    or (len(cand_canon) >= 2 and _word_boundary_match(_strip_version(term_str), req))
            )
            if is_match:
                found.append(
                    ScoreEvidence(
                        evidence_id=str(
                            uuid.uuid5(uuid.NAMESPACE_URL, f"skill-phrase:{req}:{term_str}:{i}")
                        ),
                        category="skills",
                        signal_type="alias_skill_match",
                        value=1.0,
                        source_location=f"profile_data.skills[{i}]",
                        matched_term=term_str,
                        requirement_term=req,
                        canonical_term=canonical or cand_canon,
                        alias_used=cand_canon,
                        match_type="alias",
                        rationale=f"Matched skill '{term_str}' to requirement '{req}'",
                    )
                )
                break
    return found


def resume_context_skill_evidence(
        requirements: list[str],
        projects: list[dict],
        experience: list[dict],
        aliases: dict[str, str],
) -> list[ScoreEvidence]:
    """Find grounded skill matches inside project technologies and work/project descriptions."""
    found: list[ScoreEvidence] = []
    # Build reverse alias expansions so requirement "Node.js" also finds "nodejs" / "Node JS"
    alias_groups: dict[str, set[str]] = {}
    for k, v in aliases.items():
        canon_v, _ = canonical_skill(v, aliases)
        alias_groups.setdefault(canon_v, set()).update({k.casefold(), v.casefold(), canon_v})

    for req in sorted(set(requirements), key=str.casefold):
        req_canon, _ = canonical_skill(req, aliases)
        req_subterms = _skill_subterms(req, aliases)
        search_phrases: set[str] = {req.casefold(), _strip_version(req).casefold()}
        for sub in req_subterms:
            search_phrases.add(sub)
            search_phrases.update(alias_groups.get(sub, set()))
        search_phrases = {p for p in search_phrases if p and p not in _GENERIC_SKILL_WORDS}

        matched = False
        # 1. Check project technologies list (strong structured signal)
        for proj in projects:
            pid = str(proj.get("id", ""))
            for tech in proj.get("technologies") or []:
                tech_str = str(tech).strip()
                if not tech_str:
                    continue
                t_canon, _ = canonical_skill(_strip_version(tech_str), aliases)
                if t_canon == req_canon or t_canon in req_subterms:
                    found.append(
                        ScoreEvidence(
                            evidence_id=str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL, f"proj-tech:{req}:{pid}:{tech_str}"
                                )
                            ),
                            category="skills",
                            signal_type="alias_skill_match",
                            value=0.95,
                            source_location=f"projects:{pid}",
                            matched_term=tech_str,
                            requirement_term=req,
                            canonical_term=req_canon or t_canon,
                            alias_used=t_canon,
                            match_type="alias",
                            supporting_quotes=(tech_str,),
                            grounded=True,
                            rationale=f"Skill '{tech_str}' listed in project technologies",
                        )
                    )
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue

        # 2. Check employment and project text descriptions/highlights for whole-word match
        sources = [
                      ("experience", item) for item in experience
                  ] + [
                      ("projects", item) for item in projects
                  ]
        for section, item in sources:
            item_id = str(item.get("id", ""))
            text_parts = [
                str(v)
                for v in (
                    item.get("title"),
                    item.get("name"),
                    item.get("role"),
                    item.get("description"),
                    *(item.get("highlights") or []),
                )
                if v
            ]
            for part in text_parts:
                hit_phrase = next(
                    (
                        p
                        for p in sorted(search_phrases, key=lambda s: (-len(s), s))
                        if _word_boundary_match(p, part)
                    ),
                    None,
                )
                if hit_phrase:
                    found.append(
                        ScoreEvidence(
                            evidence_id=str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL, f"ctx-skill:{req}:{section}:{item_id}"
                                )
                            ),
                            category="skills",
                            signal_type="rule_based_match",
                            value=0.85,
                            source_location=f"{section}:{item_id}",
                            matched_term=hit_phrase,
                            requirement_term=req,
                            canonical_term=req_canon,
                            match_type="rule",
                            supporting_quotes=(part[:300],),
                            grounded=True,
                            rationale=f"Skill '{req}' demonstrated in {section} description",
                        )
                    )
                    matched = True
                    break
            if matched:
                break
    return found


def semantic_evidence(
        requirement: str,
        claim: str,
        provider: EmbeddingProvider,
        threshold: float = 0.55,
        model_version: str = "1",
        category: str = "skills",
        full_threshold: float = 0.85,
        credit_cap: float = 0.60,
) -> ScoreEvidence:
    a, b = _cached_embedding(provider, requirement), _cached_embedding(provider, claim)
    if len(a.vector) != len(b.vector) or not a.vector:
        raise ValueError("Embedding dimensions do not match")
    dot = sum(x * y for x, y in zip(a.vector, b.vector))
    denom = (sum(x * x for x in a.vector) ** 0.5) * (sum(y * y for y in b.vector) ** 0.5)
    similarity = max(-1.0, min(1.0, dot / denom)) if denom else 0.0
    credit = credit_cap * max(
        0.0, min(1.0, (similarity - threshold) / max(full_threshold - threshold, 1e-12))
    )
    return ScoreEvidence(
        str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"semantic:{category}:{a.content_hash}:{b.content_hash}:{model_version}",
            )
        ),
        category,
        "semantic_similarity",
        credit,
        source_location="extracted_resume_claim",
        requirement_term=requirement,
        compared_texts=(requirement[:500], claim[:500]),
        model_version=b.model_version or model_version,
        similarity=similarity,
        rationale="Semantic similarity is a relevance signal, not proof of skill or experience",
        embedding=tuple(b.vector),
        embedding_model=b.model_name,
        embedding_model_version=b.model_version,
        embedding_dim=b.dimension,
    )


async def llm_relevance_evidence(
        requirement: str,
        claim: str,
        resume_text: str,
        analyzer: LLMAnalyzer,
        rating_map: dict[str, float],
        category: str = "projects",
) -> ScoreEvidence:
    digest = hashlib.sha256((requirement + "\0" + claim + "\0" + resume_text).encode()).hexdigest()
    try:
        result = await analyzer.analyze_relevance(requirement, claim, resume_text)
        grounded = tuple(q for q in result.supporting_quotes if q and q in resume_text)
        ungrounded = tuple(q for q in result.supporting_quotes if q and q not in resume_text)
        valid = not ungrounded and bool(grounded)
        score = rating_map.get(result.rating) if valid else None
        return ScoreEvidence(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{category}:{digest}")),
            category,
            "llm_relevance",
            score,
            requirement_term=requirement,
            supporting_quotes=grounded,
            grounded=valid,
            rationale=result.rationale
            if valid
            else "Ungrounded or absent quotes; signal downgraded",
            error=("ungrounded_quotes" if ungrounded else None),
            model_name=result.model_name,
            input_hash=digest,
            llm_model=result.model_name,
            model_version=result.model_version,
            prompt_version=result.prompt_version or result.model_version or "unknown",
        )
    except Exception as exc:  # provider timeouts/schema errors are unknown signals
        return ScoreEvidence(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{category}:{digest}")),
            category,
            "llm_relevance",
            None,
            requirement_term=requirement,
            grounded=False,
            error=type(exc).__name__,
            model_name="unknown",
            input_hash=digest,
            llm_model="unknown",
            prompt_version="unknown",
        )
