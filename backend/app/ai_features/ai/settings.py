"""
AI configuration. One env var switches the whole stack from laptop to production:

    development (default)   AI_MODEL=heuristic          offline, no keys, no network, deterministic
    local LLM               AI_MODEL=ollama:qwen2.5:7b  (+ OLLAMA_BASE_URL)
    production              AI_MODEL=anthropic:claude-sonnet-5-5   (+ ANTHROPIC_API_KEY)
                            AI_FALLBACK_MODELS=openai:gpt-5        (optional)

Any Pydantic AI model id works ("provider:model"). Production refuses the offline models.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
OFFLINE_MODELS = frozenset({"heuristic", "test"})


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_", env_file=".env", extra="ignore", populate_by_name=True
    )

    env: str = Field(
        "development", validation_alias=AliasChoices("AI_ENV", "APP_ENV", "ENVIRONMENT")
    )
    model: str = "heuristic"
    fast_model: str = ""  # lower-cost, low-latency tier for reasoning/verification/decision tasks
    nano_model: str = ""  # ultra-low-cost tier for high-volume micro-classification tasks
    fallback_models: str = ""  # comma separated, tried in order if the primary fails
    google_api_key: SecretStr | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    engine: Literal["auto", "pydantic_ai", "dspy"] = "pydantic_ai"
    dspy_lm: str | None = None  # explicit LiteLLM name; default is derived from `model`

    timeout_seconds: float = 90.0
    max_tokens: int = 8192
    temperature: float | None = (
        None  # unset = deterministic 0.0 for non-reasoning models
    )
    thinking_budget_extraction: int = 0  # fast structured extraction on Gemini thinking models
    thinking_budget_reasoning: int = 256  # bounded reasoning for analysis/verification tasks
    reasoning_effort_extraction: Literal["none", "minimal", "low", "medium", "high"] = "low"
    reasoning_effort_reasoning: Literal["none", "minimal", "low", "medium", "high"] = "low"
    output_retries: int = 2  # Pydantic AI re-asks the model when output fails validation
    request_limit: int = 6  # hard cap on model calls per extraction

    cache_enabled: bool = True  # content-addressed L1 LRU + L2 Redis response cache
    cache_ttl_seconds: int = 86400

    use_compiled: bool = True  # load DSPy-optimized prompts from compiled_dir when present
    compiled_dir: Path = PACKAGE_DIR / "compiled"

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in {"production", "prod"}

    @property
    def model_chain(self) -> list[str]:
        return [
            self.model.strip().strip("\"'"),
            *[
                m.strip().strip("\"'")
                for m in self.fallback_models.split(",")
                if m.strip().strip("\"'")
            ],
        ]

    def _inferred_tier_model(self, tier: Literal["primary", "fast", "nano"]) -> str | None:
        if tier == "primary" or self.offline:
            return None
        explicit = (self.fast_model if tier == "fast" else self.nano_model).strip().strip("\"'")
        if explicit:
            return explicit
        primary = self.model.strip().strip("\"'")
        low = primary.lower()
        if low in {"openai:gpt-5.4", "openai-chat:gpt-5.4"}:
            prefix = primary.split(":", 1)[0]
            return f"{prefix}:gpt-5.4-mini" if tier == "fast" else f"{prefix}:gpt-5.4-nano"
        if low in {"openai:gpt-5", "openai-chat:gpt-5"}:
            prefix = primary.split(":", 1)[0]
            return f"{prefix}:gpt-5-mini" if tier == "fast" else f"{prefix}:gpt-5-nano"
        if low in {"openai:gpt-4.1", "openai-chat:gpt-4.1"}:
            prefix = primary.split(":", 1)[0]
            return f"{prefix}:gpt-4.1-mini"
        return None

    def model_chain_for_tier(self, tier: Literal["primary", "fast", "nano"] = "primary") -> list[str]:
        base = self.model_chain
        if tier == "primary" or self.offline:
            return base
        ordered: list[str] = []
        if tier == "nano":
            nano = self._inferred_tier_model("nano")
            if nano:
                ordered.append(nano)
            fast = self._inferred_tier_model("fast")
            if fast and fast not in ordered:
                ordered.append(fast)
        elif tier == "fast":
            fast = self._inferred_tier_model("fast")
            if fast:
                ordered.append(fast)
        for m in base:
            if m and m not in ordered:
                ordered.append(m)
        return ordered

    @property
    def offline(self) -> bool:
        return self.model.strip().strip("\"'") in OFFLINE_MODELS


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()
