"""Provider implementations are lazy and settings-driven; tests use protocol fakes."""

from __future__ import annotations

import hashlib
import math
import re

from app.ai_features.schemas.analysis import StrictRelevanceOutput
from app.modules.candidate_intelligence.config import (
    CandidateIntelligenceSettings,
    get_intelligence_settings,
)
from app.modules.candidate_intelligence.interfaces import EmbeddingResult, RelevanceAnalysisResult

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "can",
        "demonstrated",
        "develop",
        "developing",
        "development",
        "ability",
        "excellent",
        "experience",
        "experienced",
        "familiar",
        "familiarity",
        "for",
        "from",
        "good",
        "great",
        "hands",
        "have",
        "having",
        "in",
        "including",
        "into",
        "is",
        "it",
        "its",
        "knowledge",
        "least",
        "minimum",
        "must",
        "nice",
        "of",
        "on",
        "or",
        "plus",
        "preferred",
        "proficiency",
        "proficient",
        "proven",
        "required",
        "requirement",
        "requirements",
        "role",
        "skill",
        "skills",
        "solid",
        "strong",
        "that",
        "the",
        "their",
        "this",
        "to",
        "understanding",
        "use",
        "using",
        "very",
        "well",
        "with",
        "work",
        "working",
        "year",
        "years",
        "yr",
        "yrs",
    }
)

_TOKEN_ALIASES = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "ts": "typescript",
    "node": "nodejs",
    "postgres": "postgresql",
    "psql": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
    "reactjs": "react",
    "vuejs": "vue",
    "angularjs": "angular",
    "expressjs": "express",
    "nextjs": "nextjs",
    "mongo": "mongodb",
    "sklearn": "scikitlearn",
    "ml": "machinelearning",
    "apis": "api",
    "microservices": "microservice",
    "services": "service",
    "systems": "system",
    "databases": "database",
    "applications": "application",
    "pipelines": "pipeline",
    "containers": "container",
    "architectures": "architecture",
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")


def _normalize_token(raw: str) -> str:
    cleaned = raw.casefold().strip(".,;:/-")
    if not cleaned:
        return ""
    compact = re.sub(r"[.\s-]+", "", cleaned)
    if compact in _TOKEN_ALIASES:
        return _TOKEN_ALIASES[compact]
    if cleaned in _TOKEN_ALIASES:
        return _TOKEN_ALIASES[cleaned]
    if len(cleaned) > 4 and cleaned.endswith("ies"):
        cleaned = cleaned[:-3] + "y"
    elif len(cleaned) > 4 and cleaned.endswith("es") and not cleaned.endswith(("ses", "ces")):
        cleaned = cleaned[:-2]
    elif len(cleaned) > 3 and cleaned.endswith("s") and not cleaned.endswith(
            ("ss", "us", "is", "js", "ts", "aws", "css")):
        cleaned = cleaned[:-1]
    return _TOKEN_ALIASES.get(cleaned, cleaned)


def _extract_tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.findall(text.casefold()):
        # Split slash- or hyphen-joined compounds while also keeping the whole token if useful
        parts = [p for p in re.split(r"[/,]", match) if p]
        for part in parts:
            norm = _normalize_token(part)
            if not norm or norm.isdigit():
                continue
            if drop_stopwords and norm in _STOPWORDS:
                continue
            tokens.append(norm)
            if "-" in part:
                for sub in part.split("-"):
                    sub_norm = _normalize_token(sub)
                    if sub_norm and not sub_norm.isdigit() and (not drop_stopwords or sub_norm not in _STOPWORDS):
                        tokens.append(sub_norm)
    return tokens


def _trigrams(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+# ]+", " ", text.casefold())).strip()
    if len(compact) < 3:
        return [compact] if compact else []
    return [compact[i: i + 3] for i in range(len(compact) - 2)]


def _hash_feature(feature: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    val = int.from_bytes(digest, "little")
    idx = val % dimension
    sign = 1.0 if ((val >> 63) & 1) == 0 else -1.0
    return idx, sign


def _embed_hashed_features(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    tokens = _extract_tokens(text, drop_stopwords=True)
    if not tokens:
        tokens = _extract_tokens(text, drop_stopwords=False)
    for tok in tokens:
        idx, sign = _hash_feature(f"w:{tok}", dimension)
        vector[idx] += 2.0 * sign
    for a, b in zip(tokens, tokens[1:]):
        idx, sign = _hash_feature(f"b:{a}_{b}", dimension)
        vector[idx] += 1.0 * sign
    for tri in _trigrams(text):
        idx, sign = _hash_feature(f"c:{tri}", dimension)
        vector[idx] += 0.5 * sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 1e-12:
        seed = hashlib.sha512(text.encode("utf-8")).digest()
        vector = [(seed[i % len(seed)] / 127.5) - 1.0 for i in range(dimension)]
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _find_grounded_quotes(claim_text: str, full_resume_text: str) -> list[str]:
    if not full_resume_text:
        return []
    stripped_claim = claim_text.strip()
    if stripped_claim and stripped_claim in full_resume_text:
        return [stripped_claim[:300]]
    claim_tokens = set(_extract_tokens(claim_text, drop_stopwords=False))
    lines = [line.strip() for line in full_resume_text.splitlines() if line.strip()]
    if not lines:
        return []
    scored: list[tuple[int, str]] = []
    for line in lines:
        if line not in full_resume_text:
            continue
        if stripped_claim and line in stripped_claim:
            scored.append((1000 + len(line), line))
            continue
        line_tokens = set(_extract_tokens(line, drop_stopwords=False))
        overlap = len(claim_tokens & line_tokens)
        if overlap > 0:
            scored.append((overlap, line))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored:
        return [line[:300] for _, line in scored[:2]]
    return [lines[0][:300]]


def _tokens_match(req_tok: str, claim_tokens: set[str]) -> bool:
    if req_tok in claim_tokens:
        return True
    if len(req_tok) >= 4:
        for ct in claim_tokens:
            if len(ct) >= 4 and (ct.startswith(req_tok) or req_tok.startswith(ct)):
                return True
    return False


def _deterministic_relevance(
        requirement_text: str,
        claim_text: str,
        full_resume_text: str,
        rating_map: dict[str, float],
        model_name: str,
        model_version: str,
        prompt_version: str,
) -> RelevanceAnalysisResult:
    digest = hashlib.sha256(
        (requirement_text + "\0" + claim_text + "\0" + full_resume_text).encode()
    ).hexdigest()
    quotes = _find_grounded_quotes(claim_text, full_resume_text)
    if not claim_text.strip() or not quotes:
        return RelevanceAnalysisResult(
            "insufficient_information",
            None,
            "Insufficient claim text to infer relevance",
            [],
            False,
            [],
            digest,
            model_name,
            model_version,
            prompt_version,
        )
    req_tokens = list(dict.fromkeys(_extract_tokens(requirement_text, drop_stopwords=True)))
    claim_tokens = set(_extract_tokens(claim_text, drop_stopwords=True))
    if not req_tokens:
        req_tokens = list(dict.fromkeys(_extract_tokens(requirement_text, drop_stopwords=False)))
        claim_tokens = set(_extract_tokens(claim_text, drop_stopwords=False))

    if req_tokens and claim_tokens:
        matched = [t for t in req_tokens if _tokens_match(t, claim_tokens)]
        coverage = len(matched) / len(req_tokens)
        # Also reward matching multiple distinct required terms in a broad list
        # (e.g. matching 3+ distinct skills out of a 8-skill job list is strong role relevance).
        broad_bonus = min(len(matched) / 3.0, 1.0) if len(req_tokens) >= 4 and len(matched) >= 2 else 0.0
        v_req = _embed_hashed_features(requirement_text, 128)
        v_claim = _embed_hashed_features(claim_text, 128)
        cosine = max(0.0, sum(a * b for a, b in zip(v_req, v_claim)))
        score_signal = max(coverage, 0.75 * broad_bonus, 0.65 * cosine if matched else 0.0)
    else:
        matched = []
        score_signal = 0.0

    if score_signal >= 0.55:
        rating = "high"
    elif score_signal >= 0.28:
        rating = "medium"
    elif score_signal >= 0.12:
        rating = "low"
    else:
        rating = "none"

    rationale = (
        f"Matched requirement terms ({', '.join(matched[:6])}) in claim"
        if matched
        else "No direct term overlap between requirement and claim"
    )
    return RelevanceAnalysisResult(
        rating,
        rating_map.get(rating),
        rationale,
        quotes,
        True,
        [],
        digest,
        model_name,
        model_version,
        prompt_version,
    )


class DeterministicMockEmbeddingProvider:
    def __init__(self, model_name="deterministic-mock", model_version="1", dimension=384):
        self.model_name, self.model_version, self.dimension = model_name, model_version, dimension

    def embed_text(self, text: str) -> EmbeddingResult:
        digest = hashlib.sha256(text.encode()).hexdigest()
        vector = _embed_hashed_features(text, self.dimension)
        return EmbeddingResult(
            vector, self.model_name, self.model_version, self.dimension, digest
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self.embed_text(text) for text in texts]


def build_embedding_provider(settings: CandidateIntelligenceSettings | None = None):
    cfg = settings or get_intelligence_settings()
    if cfg.embedding_provider == "mock":
        return DeterministicMockEmbeddingProvider(
            cfg.semantic_model_name, cfg.semantic_model_version, cfg.embedding_dimension
        )
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers must be installed for the production embedding provider"
        ) from exc
    return SentenceTransformerProvider(
        SentenceTransformer(cfg.semantic_model_name),
        cfg.semantic_model_name,
        cfg.semantic_model_version,
    )


class SentenceTransformerProvider:
    def __init__(self, model, model_name: str, model_version: str):
        self.model, self.model_name, self.model_version = model, model_name, model_version

    def embed_text(self, text: str) -> EmbeddingResult:
        vector = self.model.encode(text, normalize_embeddings=True).tolist()
        return EmbeddingResult(
            vector,
            self.model_name,
            self.model_version,
            len(vector),
            hashlib.sha256(text.encode()).hexdigest(),
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self.embed_text(text) for text in texts]


def prompt_for_relevance(requirement: str, claim: str, resume: str) -> str:
    """Compact structured payload for relevance analysis (rubric & safety live in RELEVANCE_INSTRUCTIONS)."""
    trimmed_resume = (resume or "").strip()
    if len(trimmed_resume) > 2500:
        # Keep the claim neighborhood if present, otherwise first 2500 chars
        idx = trimmed_resume.find(claim.strip()[:80]) if claim and claim.strip() else -1
        if idx >= 0:
            start = max(0, idx - 600)
            trimmed_resume = trimmed_resume[start: start + 2500]
        else:
            trimmed_resume = trimmed_resume[:2500]
    return (
        f"<requirement>{requirement.strip()[:300]}</requirement>\n"
        f"<claim>{claim.strip()[:600]}</claim>\n"
        f"<untrusted_resume>\n{trimmed_resume}\n</untrusted_resume>"
    )


def build_llm_analyzer(settings: CandidateIntelligenceSettings | None = None):
    cfg = settings or get_intelligence_settings()
    if cfg.llm_provider == "mock" or cfg.llm_model == "heuristic":
        return MockLLMAnalyzer(
            rating_map=cfg.relevance_scores,
            model_name=cfg.llm_model or "heuristic",
            prompt_version=cfg.llm_prompt_version,
        )
    return PydanticAIRelevanceAnalyzer(cfg)


class MockLLMAnalyzer:
    def __init__(
            self,
            rating_map: dict[str, float] | None = None,
            model_name: str = "heuristic",
            prompt_version: str = "relevance-v1",
    ):
        self.rating_map = rating_map or {
            "high": 1.0,
            "medium": 0.6,
            "low": 0.25,
            "none": 0.0,
        }
        self.model_name = model_name
        self.prompt_version = prompt_version

    async def analyze_relevance(
            self, requirement_text: str, claim_text: str, full_resume_text: str
    ) -> RelevanceAnalysisResult:
        return _deterministic_relevance(
            requirement_text,
            claim_text,
            full_resume_text,
            self.rating_map,
            self.model_name,
            "1",
            self.prompt_version,
        )


class PydanticAIRelevanceAnalyzer:
    """Routes relevance analysis via task-specific AI engine (DSPy ChainOfThought in auto mode, Pydantic AI fallback)."""

    def __init__(self, settings: CandidateIntelligenceSettings):
        self.settings = settings

    async def analyze_relevance(
            self, requirement_text: str, claim_text: str, full_resume_text: str
    ) -> RelevanceAnalysisResult:
        import asyncio
        from app.ai_features.ai.settings import get_ai_settings
        from app.ai_features.ai.tasks import build_extractor, get_extractor

        ai_settings = get_ai_settings()
        target_model = self.settings.llm_model
        use_default_extractor = False
        if (not target_model or target_model == "heuristic") and not ai_settings.offline:
            target_model = ai_settings.model
            use_default_extractor = True
        elif target_model == ai_settings.model:
            use_default_extractor = True
        if not target_model or target_model in {"heuristic", "test"}:
            return _deterministic_relevance(
                requirement_text,
                claim_text,
                full_resume_text,
                self.settings.relevance_scores,
                "heuristic",
                self.settings.llm_prompt_version,
                self.settings.llm_prompt_version,
            )

        digest = hashlib.sha256(
            (requirement_text + "\0" + claim_text + "\0" + full_resume_text).encode()
        ).hexdigest()
        prompt = prompt_for_relevance(requirement_text, claim_text, full_resume_text)
        try:
            if use_default_extractor:
                extractor = get_extractor("relevance_analysis")
            else:
                run_settings = ai_settings.model_copy(
                    update={
                        "model": target_model,
                        "timeout_seconds": float(self.settings.llm_timeout_seconds),
                    }
                )
                extractor = build_extractor("relevance_analysis", run_settings)
            run = await asyncio.wait_for(
                extractor.run(prompt), timeout=self.settings.llm_timeout_seconds
            )
            output = run.output
            quotes = [q for q in output.supporting_quotes if q in full_resume_text]
            invalid = [q for q in output.supporting_quotes if q not in full_resume_text]
            active_model = run.model.split(",")[0] if run.model else target_model
            return RelevanceAnalysisResult(
                output.rating,
                self.settings.relevance_scores.get(output.rating),
                output.rationale,
                quotes,
                bool(quotes) and not invalid,
                invalid,
                digest,
                f"{run.engine}:{active_model}",
                run.prompt_version,
                run.prompt_version,
            )
        except Exception:
            return _deterministic_relevance(
                requirement_text,
                claim_text,
                full_resume_text,
                self.settings.relevance_scores,
                f"{target_model}:heuristic-fallback",
                self.settings.llm_prompt_version,
                self.settings.llm_prompt_version,
            )
