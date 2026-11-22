"""Protocol and ABC interfaces for embedding and LLM analysis components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class EmbeddingResult:
    vector: list[float]
    model_name: str
    model_version: str
    dimension: int
    content_hash: str


@dataclass
class RelevanceAnalysisResult:
    rating: str  # high | medium | low | none | insufficient_information
    score: float | None  # mapped 0.0 - 1.0 from rating
    rationale: str
    supporting_quotes: list[str]
    is_grounded: bool
    ungrounded_quotes: list[str]
    input_hash: str
    model_name: str
    model_version: str
    prompt_version: str | None = None


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for generating text embeddings."""

    def embed_text(self, text: str) -> EmbeddingResult:
        """Synchronously or deterministically generate an embedding vector."""
        ...

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts."""
        ...


@runtime_checkable
class LLMAnalyzer(Protocol):
    """Protocol for LLM-based relevance analysis with strict grounding."""

    async def analyze_relevance(
        self,
        requirement_text: str,
        claim_text: str,
        full_resume_text: str,
    ) -> RelevanceAnalysisResult:
        """Analyze relevance of candidate claim to requirement with verbatim grounding."""
        ...
