"""Provider-independent AI errors. Messages never contain document text."""

from __future__ import annotations

from enum import StrEnum


class AIErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"  # missing key, bad model id, offline model in production
    UNAVAILABLE = "unavailable"  # provider down / rate-limited / timed out / rejected
    INVALID_OUTPUT = "invalid_output"  # model answered but not with valid structured data


class AIError(Exception):
    def __init__(self, kind: AIErrorKind, *, retryable: bool = False, detail: str = "") -> None:
        super().__init__(detail or kind.value)
        self.kind = kind
        self.retryable = retryable
        self.detail = detail or kind.value


_AUTH = {
    "ModelAuthenticationError",
    "AuthenticationError",
    "PermissionDeniedError",
    "UserError",
}
_CONFIG = {"LMConfigurationError", "LMNotConfiguredError"}
_TRANSIENT = {
    "ModelRateLimitError",
    "ModelServerError",
    "ModelConnectionError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "RunTimedOut",
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "Timeout",
    "ServiceUnavailableError",
    "InternalServerError",
    "TimeoutException",
    "ConnectError",
    "ReadError",
    "TimeoutError",
}
_PERMANENT_REJECT = {
    "ModelQuotaExceededError",
    "ModelRequestRejectedError",
    "LMInvalidRequestError",
    "BadRequestError",
    "NotFoundError",
}
_BAD_OUTPUT = {
    "UnexpectedModelBehavior",
    "AdapterParseError",
    "ValidationError",
    "JSONDecodeError",
}
_NO_RETRY_OUTPUT = {"UsageLimitExceeded", "ContentFilterError"}


def classify_exception(exc: BaseException) -> AIError:
    """Map Pydantic AI / DSPy(LiteLLM) / httpx exceptions to AIError by class name (no hard imports)."""
    if isinstance(exc, AIError):
        return exc
    if isinstance(exc, BaseExceptionGroup):  # FallbackModel: every model failed
        errs = [classify_exception(e) for e in exc.exceptions]
        return next(
            (e for e in errs if e.retryable),
            errs[0] if errs else AIError(AIErrorKind.UNAVAILABLE, retryable=True),
        )
    names = {c.__name__ for c in type(exc).__mro__}
    if names & _CONFIG:
        return AIError(
            AIErrorKind.NOT_CONFIGURED,
            detail="AI model configuration is invalid",
        )
    if names & _AUTH:
        return AIError(
            AIErrorKind.NOT_CONFIGURED,
            detail=f"AI provider is not configured or credentials were rejected",
        )
    if names & _NO_RETRY_OUTPUT:
        return AIError(AIErrorKind.INVALID_OUTPUT, detail="Model output was rejected")
    if "ModelHTTPError" in names:
        status = getattr(exc, "status_code", 0) or 0
        if status in (401, 403):
            return AIError(
                AIErrorKind.NOT_CONFIGURED,
                detail=f"AI provider credentials were rejected",
            )
        return AIError(
            AIErrorKind.UNAVAILABLE,
            retryable=status >= 500 or status in (408, 409, 429),
            detail=f"AI provider returned HTTP {status}",
        )
    if names & _TRANSIENT:
        return AIError(
            AIErrorKind.UNAVAILABLE,
            retryable=True,
            detail="AI provider temporarily unavailable",
        )
    if names & _PERMANENT_REJECT:
        return AIError(
            AIErrorKind.UNAVAILABLE,
            retryable=False,
            detail="AI provider rejected the request",
        )
    if names & _BAD_OUTPUT:
        return AIError(
            AIErrorKind.INVALID_OUTPUT,
            retryable=True,
            detail="Model output failed validation",
        )
    return AIError(
        AIErrorKind.UNAVAILABLE,
        retryable=True,
        detail=f"Unexpected AI error ({type(exc).__name__})",
    )
