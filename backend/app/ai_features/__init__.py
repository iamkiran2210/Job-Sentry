"""
AI features for Job Sentry (resume ingestion, candidate extraction, AI requirement suggestions).
Self-contained: copy this folder into backend/app/ and wire it with three lines (see README.md).

    from app.ai_features import router as ai_features_router          # 1. routes
    import app.ai_features.models                                      # 2. tables (in models/__init__.py)
    app.include_router(ai_features_router, prefix=settings.API_V1_STR)

Imports are lazy on purpose: importing `app.ai_features.models` from your models/__init__.py must not pull in the
router (and through it your auth/job code), which would create a circular import.
"""

from __future__ import annotations

from typing import Any

__all__ = ["router", "startup_check"]


def __getattr__(name: str) -> Any:
    if name == "router":
        from .api import router

        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def startup_check() -> dict[str, Any]:
    """Optional: call from your app lifespan / worker start to fail fast on bad AI config
    (e.g. AI_ENV=production with AI_MODEL=heuristic, or a missing provider API key)."""
    from .ai.models import check_ai_config
    from .ai.settings import get_ai_settings

    return check_ai_config(get_ai_settings())
