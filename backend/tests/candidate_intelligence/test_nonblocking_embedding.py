import asyncio
import time
from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.candidate_intelligence.interfaces import EmbeddingResult
from app.modules.candidate_intelligence.service import ScoringService
from app.modules.candidate_intelligence.types import ScoringInputs


@pytest.mark.asyncio
async def test_sync_embedding_does_not_block_the_event_loop(monkeypatch):
    ticker_ticks = 0
    ticks_during_embedding = []

    class SlowEmbedder:
        model_name = "slow-test"
        model_version = "1"

        def embed_text(self, text: str) -> EmbeddingResult:
            time.sleep(0.04)
            ticks_during_embedding.append(ticker_ticks)
            return EmbeddingResult([1.0, 0.0], self.model_name, self.model_version, 2, text)

    cfg = SimpleNamespace(
        skill_aliases={},
        semantic_min=0.5,
        semantic_full=0.9,
        semantic_credit_cap=0.6,
        semantic_model_version="1",
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_embedding_provider",
        lambda _cfg: SlowEmbedder(),
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_llm_analyzer",
        lambda _cfg: object(),
    )
    inputs = ScoringInputs(
        skills=({"id": "skill-1", "name": "Python"},),
        experience=(),
        projects=(),
        education=(),
        certifications=(),
        requirements=({"id": "req-1", "category": "skills", "name": "Python"},),
        as_of=date(2026, 1, 1),
    )

    async def ticker():
        nonlocal ticker_ticks
        for _ in range(8):
            await asyncio.sleep(0.005)
            ticker_ticks += 1

    await asyncio.gather(ScoringService._collect_evidence(inputs, cfg), ticker())

    assert ticker_ticks == 8
    assert ticks_during_embedding and max(ticks_during_embedding) > 0
