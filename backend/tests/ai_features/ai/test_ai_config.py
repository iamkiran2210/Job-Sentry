import pytest

from app.ai_features.ai.errors import AIError, AIErrorKind, classify_exception
from app.ai_features.ai.models import build_model, check_ai_config
from app.ai_features.ai.settings import AISettings


def S(**kw):
    return AISettings(_env_file=None, **kw)


def test_defaults_are_offline_dev():
    s = S()
    assert (s.model, s.engine, s.env, s.is_production, s.offline) == (
        "heuristic",
        "pydantic_ai",
        "development",
        False,
        True,
    )
    assert s.model_chain == ["heuristic"]


def test_env_vars_drive_everything(monkeypatch):
    monkeypatch.setenv("AI_MODEL", "anthropic:claude-sonnet-5-5")
    monkeypatch.setenv("AI_FALLBACK_MODELS", " openai:gpt-5 , ollama:llama3.2 ")
    monkeypatch.setenv("APP_ENV", "production")  # shares your app's environment variable
    s = AISettings(_env_file=None)
    assert (
            s.model_chain == ["anthropic:claude-sonnet-5-5", "openai:gpt-5", "ollama:llama3.2"]
            and s.is_production
            and not s.offline
    )


@pytest.mark.parametrize("model", ["heuristic", "test"])
def test_production_refuses_offline_models(model):
    with pytest.raises(AIError) as e:
        check_ai_config(S(env="production", model=model))
    assert e.value.kind == AIErrorKind.NOT_CONFIGURED and "not allowed" in e.value.detail


def test_production_with_real_model_but_missing_key_fails_fast(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AIError) as e:
        check_ai_config(S(env="production", model="anthropic:claude-sonnet-5-5"))
    assert e.value.kind == AIErrorKind.NOT_CONFIGURED and not e.value.retryable


def test_real_model_with_key_passes_and_fallback_chain_builds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = S(
        env="production",
        model="anthropic:claude-sonnet-5-5",
        fallback_models="openai:gpt-5",
    )
    info = check_ai_config(s)
    assert info["offline"] is False and info["models"] == [
        "anthropic:claude-sonnet-5-5",
        "openai:gpt-5",
    ]
    assert type(build_model(s, "resume_profile")).__name__ == "FallbackModel"


def test_dspy_engine_rules():
    check_ai_config(S(engine="dspy", model="heuristic"))  # offline DSPy LM is allowed for dev
    with pytest.raises(AIError):
        check_ai_config(S(engine="dspy", model="test"))


def test_classification_table():
    from pydantic_ai.exceptions import (
        ModelHTTPError,
        ModelRateLimitError,
        UnexpectedModelBehavior,
        UsageLimitExceeded,
        UserError,
    )

    def c(exc):
        e = classify_exception(exc)
        return e.kind, e.retryable

    assert c(UserError("no key")) == (AIErrorKind.NOT_CONFIGURED, False)
    assert c(ModelHTTPError(401, "m")) == (AIErrorKind.NOT_CONFIGURED, False)
    assert c(ModelHTTPError(503, "m")) == (AIErrorKind.UNAVAILABLE, True)
    assert c(ModelHTTPError(429, "m")) == (AIErrorKind.UNAVAILABLE, True)
    assert c(ModelHTTPError(400, "m")) == (AIErrorKind.UNAVAILABLE, False)
    assert c(ModelRateLimitError("m", "rl")) == (AIErrorKind.UNAVAILABLE, True)
    assert c(UnexpectedModelBehavior("bad")) == (AIErrorKind.INVALID_OUTPUT, True)
    assert c(UsageLimitExceeded("cap")) == (AIErrorKind.INVALID_OUTPUT, False)
    assert c(TimeoutError()) == (AIErrorKind.UNAVAILABLE, True)
    assert c(RuntimeError("???")) == (
        AIErrorKind.UNAVAILABLE,
        True,
    )  # unknown => bounded retry upstream
    assert c(
        ExceptionGroup("all failed", [ModelHTTPError(400, "m"), ModelHTTPError(503, "m")])
    ) == (AIErrorKind.UNAVAILABLE, True)
    assert "secret" not in classify_exception(RuntimeError("secret resume text")).detail
