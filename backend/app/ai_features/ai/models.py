"""Resolve AI_MODEL (+ fallbacks) into Pydantic AI models, with a production safety guard."""

from __future__ import annotations

import re
from typing import Any

from pydantic_ai.models import Model, infer_model

from .errors import AIError, AIErrorKind, classify_exception
from .settings import OFFLINE_MODELS, AISettings

_OPENAI_REASONING_RE = re.compile(
    r"^(?:openai(?:-chat)?:)?(?:o[1345](?:-(?:mini|nano|pro))?(?:-\d{4}-\d{2}-\d{2})?|"
    r"gpt-5(?:\.\d+)*(?!-chat)(?:-.*)?)$",
    re.IGNORECASE,
)


def _single(name: str, task: str, settings: AISettings) -> Model:
    if name == "heuristic":
        from .heuristic import heuristic_model

        return heuristic_model(task)
    if name == "test":
        from pydantic_ai.models.test import TestModel

        return TestModel()
    if name.startswith("google:") and settings.google_api_key is not None:
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        provider = GoogleProvider(api_key=settings.google_api_key.get_secret_value())
        return GoogleModel(name.removeprefix("google:"), provider=provider)
    if name.startswith("openai:") and settings.openai_api_key is not None:
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value())
        return OpenAIResponsesModel(name.removeprefix("openai:"), provider=provider)
    if name.startswith("openai-chat:") and settings.openai_api_key is not None:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value())
        return OpenAIChatModel(name.removeprefix("openai-chat:"), provider=provider)
    if name.startswith("anthropic:") and settings.anthropic_api_key is not None:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key=settings.anthropic_api_key.get_secret_value())
        return AnthropicModel(name.removeprefix("anthropic:"), provider=provider)
    return infer_model(name)  # raises UserError if the provider's API key / base URL is missing


def build_model(
        settings: AISettings,
        task: str,
        *,
        model_chain: list[str] | None = None,
) -> Model:
    chain = model_chain or settings.model_chain
    models = [_single(n, task, settings) for n in chain]
    if len(models) == 1:
        return models[0]
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(*models)


def model_settings(
        settings: AISettings,
        *,
        thinking_budget: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        primary_model: str | None = None,
) -> dict[str, Any]:
    effective_max = (
        min(settings.max_tokens, int(max_tokens))
        if max_tokens is not None
        else settings.max_tokens
    )
    out: dict[str, Any] = {
        "max_tokens": effective_max,
        "timeout": settings.timeout_seconds,
    }
    primary = primary_model or (settings.model_chain[0] if settings.model_chain else "")
    is_openai_reasoning = bool(_OPENAI_REASONING_RE.fullmatch(primary))
    if settings.temperature is not None:
        if not is_openai_reasoning:
            out["temperature"] = settings.temperature
    elif primary and primary not in OFFLINE_MODELS and not is_openai_reasoning:
        # Deterministic temperature for reproducible structured extraction & verification.
        out["temperature"] = 0.0
    if is_openai_reasoning and reasoning_effort and reasoning_effort != "none":
        out["openai_reasoning_effort"] = reasoning_effort
    if thinking_budget is not None and primary.startswith(("google:", "google-gla:")):
        out["google_thinking_config"] = {"thinking_budget": thinking_budget}
    return out


def check_ai_config(
        settings: AISettings,
        tasks: tuple[str, ...] = ("resume_profile", "job_requirements"),
) -> dict[str, Any]:
    """Fail fast. Call at API/worker startup (and from `python -m app.ai_features.ai check`)."""
    offline = [m for m in settings.model_chain if m in OFFLINE_MODELS]
    if settings.is_production and offline:
        raise AIError(
            AIErrorKind.NOT_CONFIGURED,
            detail=f"AI_MODEL={','.join(offline)} is offline-only and not allowed when AI_ENV=production",
        )
    try:
        for t in tasks:
            build_model(settings, t)
    except Exception as exc:  # noqa: BLE001
        raise classify_exception(exc) from None
    if settings.engine in {"dspy", "auto"}:
        if settings.engine == "dspy" and settings.model.strip() == "test":
            raise AIError(
                AIErrorKind.NOT_CONFIGURED,
                detail="AI_MODEL=test is Pydantic AI only; use heuristic or a real model with AI_ENGINE=dspy",
            )
        try:
            import dspy  # noqa: F401
        except ImportError:
            if settings.engine == "dspy":
                raise AIError(
                    AIErrorKind.NOT_CONFIGURED,
                    detail="AI_ENGINE=dspy requires `pip install dspy`",
                ) from None
    return {
        "env": settings.env,
        "engine": settings.engine,
        "models": settings.model_chain,
        "offline": bool(offline),
    }
