from __future__ import annotations

import hashlib
import re
import uuid
import threading

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


def canonical_skill(value: str, aliases: dict[str, str]) -> tuple[str, str | None]:
    normalized = re.sub(r"[^a-z0-9+#]+", "", value.casefold())
    alias_map = {re.sub(r"[^a-z0-9+#]+", "", k.casefold()): re.sub(r"[^a-z0-9+#]+", "", v.casefold()) for k, v in aliases.items()}
    return alias_map.get(normalized, normalized), (normalized if normalized in alias_map else None)


def exact_skill_evidence(requirements: list[str], resume_skills: list[dict], aliases: dict[str, str]) -> list[ScoreEvidence]:
    found = []
    for req in sorted(set(requirements), key=str.casefold):
        canonical, _ = canonical_skill(req, aliases)
        for i, skill in enumerate(resume_skills):
            term = skill.get("name") if isinstance(skill, dict) else skill
            if not term:
                continue
            candidate, used = canonical_skill(str(term), aliases)
            if canonical == candidate:
                found.append(ScoreEvidence(
                    evidence_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"skill:{req}:{term}:{i}")),
                    category="skills", signal_type="alias_skill_match" if used else "exact_skill_match",
                    value=1.0, source_location=f"profile_data.skills[{i}]",
                    matched_term=str(term), requirement_term=req, canonical_term=canonical,
                    alias_used=used, match_type="exact" if not used else "alias",
                ))
                break
    return found


def semantic_evidence(requirement: str, claim: str, provider: EmbeddingProvider, threshold: float = .55, model_version: str = "1", category: str = "skills", full_threshold: float = .85, credit_cap: float = .60) -> ScoreEvidence:
    a, b = _cached_embedding(provider, requirement), _cached_embedding(provider, claim)
    if len(a.vector) != len(b.vector) or not a.vector:
        raise ValueError("Embedding dimensions do not match")
    dot = sum(x * y for x, y in zip(a.vector, b.vector))
    denom = (sum(x*x for x in a.vector) ** .5) * (sum(y*y for y in b.vector) ** .5)
    similarity = max(-1.0, min(1.0, dot / denom)) if denom else 0.0
    credit = credit_cap * max(0.0, min(1.0, (similarity - threshold) / max(full_threshold - threshold, 1e-12)))
    return ScoreEvidence(str(uuid.uuid5(uuid.NAMESPACE_URL, f"semantic:{category}:{a.content_hash}:{b.content_hash}:{model_version}")), category, "semantic_similarity", credit, source_location="extracted_resume_claim", requirement_term=requirement, compared_texts=(requirement[:500], claim[:500]), model_version=b.model_version or model_version, similarity=similarity, rationale="Semantic similarity is a relevance signal, not proof of skill or experience", embedding=tuple(b.vector), embedding_model=b.model_name, embedding_model_version=b.model_version, embedding_dim=b.dimension)


async def llm_relevance_evidence(requirement: str, claim: str, resume_text: str, analyzer: LLMAnalyzer, rating_map: dict[str, float], category: str = "projects") -> ScoreEvidence:
    digest = hashlib.sha256((requirement + "\0" + claim + "\0" + resume_text).encode()).hexdigest()
    try:
        result = await analyzer.analyze_relevance(requirement, claim, resume_text)
        grounded = tuple(q for q in result.supporting_quotes if q and q in resume_text)
        ungrounded = tuple(q for q in result.supporting_quotes if q and q not in resume_text)
        valid = not ungrounded and bool(grounded)
        score = rating_map.get(result.rating) if valid else None
        return ScoreEvidence(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{category}:{digest}")), category, "llm_relevance", score, requirement_term=requirement, supporting_quotes=grounded, grounded=valid, rationale=result.rationale if valid else "Ungrounded or absent quotes; signal downgraded", error=("ungrounded_quotes" if ungrounded else None), model_name=result.model_name, input_hash=digest, llm_model=result.model_name, model_version=result.model_version, prompt_version=result.prompt_version or result.model_version or "unknown")
    except Exception as exc:  # provider timeouts/schema errors are unknown signals
        return ScoreEvidence(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{category}:{digest}")), category, "llm_relevance", None, requirement_term=requirement, grounded=False, error=type(exc).__name__, model_name="unknown", input_hash=digest, llm_model="unknown", prompt_version="unknown")
