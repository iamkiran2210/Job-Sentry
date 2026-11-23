"""Adapter between the pipeline and the shared AI layer (app/ai: Pydantic AI runtime + DSPy-compiled prompts)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Protocol

from app.ai_features.ai.errors import AIError, AIErrorKind
from app.ai_features.ai.settings import AISettings, get_ai_settings
from app.ai_features.ai.tasks import build_extractor, get_extractor

from .errors import FailureCode, PipelineError

log = logging.getLogger("resumes.llm")

_PROVIDER_COOLDOWN_SECONDS = 60.0
_CLOUD_TIMEOUT_CAP_SECONDS = 75.0
_provider_cooldown_until: dict[str, float] = {}

_CODE = {
    AIErrorKind.NOT_CONFIGURED: FailureCode.LLM_NOT_CONFIGURED,
    AIErrorKind.UNAVAILABLE: FailureCode.LLM_UNAVAILABLE,
    AIErrorKind.INVALID_OUTPUT: FailureCode.LLM_INVALID_OUTPUT,
}


def reset_provider_cooldown() -> None:
    _provider_cooldown_until.clear()


@dataclass
class LLMResult:
    data: (
        dict  # validated structured output as JSON; the pipeline re-validates and grounds it anyway
    )
    provider: str  # engine: pydantic_ai | dspy
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider(Protocol):
    async def extract_profile(self, *, resume_text: str) -> LLMResult: ...


class AIProfileProvider:
    """Runs the `resume_profile` task with fast-fail cooldown so Celery workers never stall on 429/401."""

    async def extract_profile(self, *, resume_text: str) -> LLMResult:
        settings = get_ai_settings()
        extractor = get_extractor("resume_profile")
        model_key = extractor.model_label
        now = time.monotonic()
        use_heuristic = now < _provider_cooldown_until.get(model_key, 0.0)

        run = None
        if not use_heuristic:
            try:
                timeout = min(float(settings.timeout_seconds), _CLOUD_TIMEOUT_CAP_SECONDS)
                run = await asyncio.wait_for(extractor.run(resume_text), timeout=timeout)
            except (AIError, asyncio.TimeoutError) as exc:
                if isinstance(exc, asyncio.TimeoutError) or exc.kind in {
                    AIErrorKind.UNAVAILABLE,
                    AIErrorKind.NOT_CONFIGURED,
                }:
                    _provider_cooldown_until[model_key] = time.monotonic() + _PROVIDER_COOLDOWN_SECONDS
                    log.warning(
                        "Cloud resume extractor unavailable; activating %.0fs heuristic cooldown model=%s",
                        _PROVIDER_COOLDOWN_SECONDS,
                        model_key,
                    )
                use_heuristic = True

        if use_heuristic or run is None:
            try:
                run = await build_extractor(
                    "resume_profile",
                    AISettings(_env_file=None, model="heuristic", fallback_models=""),
                ).run(resume_text)
            except AIError as exc:
                raise PipelineError(_CODE[exc.kind], retryable=exc.retryable) from None

        return LLMResult(
            run.output.model_dump(mode="json"),
            run.engine,
            run.model,
            run.prompt_version,
            run.input_tokens,
            run.output_tokens,
        )


def get_llm_provider() -> LLMProvider:
    return AIProfileProvider()
